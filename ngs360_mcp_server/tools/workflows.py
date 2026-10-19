"""MCP tools for the Workflows API."""

import functools
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from ngs360_mcp_server.client import NGS360Client


# Constants baked into register_ngs360_workflow.sh. Kept identical so
# MCP-registered workflows are indistinguishable from shell-registered
# ones downstream (same project prefix, same relative_path, same engine).
_OMICS_ENGINE = "AWSHealthOmics (us-east)"
_UPLOAD_PROJECT_ID = "P-00000000-0001"
_UPLOAD_RELATIVE_PATH = "workflow_definition_file"


def _describe_http_error(exc: httpx.HTTPStatusError) -> str:
    """Describe an API error including the API's own explanation.

    httpx's message carries only the status and URL, so without this a
    tool error reaches the model as "404 Not Found for url ..." with the
    reason (which file, which field) thrown away. FastAPI puts that
    reason in ``detail``: a string, or for a 422 a list of
    ``{loc, msg}`` entries.
    """
    resp = exc.response
    try:
        body = resp.json()
        detail = body.get("detail", body)
    except (ValueError, AttributeError):
        detail = resp.text.strip()[:500]
    if isinstance(detail, list):
        detail = "; ".join(
            ": ".join(filter(None, [".".join(str(p) for p in e.get("loc", [])),
                                    str(e.get("msg"))]))
            if isinstance(e, dict) else str(e)
            for e in detail
        )
    # Host and path only: a presigned S3 URL's query string is a bearer
    # credential and must not end up in an error shown to the model.
    url = resp.request.url
    message = (
        f"{resp.status_code} {resp.reason_phrase} from "
        f"{resp.request.method} {url.host}{url.path}"
    )
    return f"{message}: {detail}" if detail else message


def _surface_api_errors(fn):
    """Re-raise API errors from a tool with the API's reason attached.

    Still raises ``httpx.HTTPStatusError``, so the error type the MCP
    layer reports is unchanged — only the message gains the detail.
    """
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except httpx.HTTPStatusError as exc:
            raise httpx.HTTPStatusError(
                _describe_http_error(exc),
                request=exc.request,
                response=exc.response,
            ) from None
    return wrapper


def _require_stdio_transport(tool_name: str, sibling: str) -> None:
    """Guard for tools that need local filesystem access on the MCP
    server host.

    Under remote (streamable-http) transport the "local" path arg
    resolves on the *deployed* server host, not the caller's machine —
    so a path like /tmp/wgs.cwl either doesn't exist or is silently the
    wrong file. Fail loud instead of silently succeeding, and point the
    caller at the sibling tool that accepts an already-uploaded file id.
    """
    if os.environ.get("MCP_TRANSPORT") == "streamable-http":
        raise RuntimeError(
            f"{tool_name} needs a file on the MCP server's local "
            "filesystem, which is not available under remote "
            f"(streamable-http) transport. Use {sibling} instead — see "
            "its docstring for step-by-step instructions on packing and "
            "uploading the CWL manually before calling it."
        )


def _git_attributes_from_args(
    git_commit: str | None,
    git_repo: str | None,
    git_ref: str | None,
) -> list[dict[str, str]]:
    """Assemble the git-attributes list from explicit arg values.

    Used by the ``*_from_file_id`` composites, where the CWL is not on
    the server's filesystem so we can't run ``git rev-parse`` ourselves.
    Callers who have git provenance (from their own local checkout)
    pass it in; unprovided keys simply don't get attached.
    """
    attrs: list[dict[str, str]] = []
    if git_commit:
        attrs.append({"key": "git_commit", "value": git_commit})
    if git_repo:
        attrs.append({"key": "git_repo", "value": git_repo})
    if git_ref:
        attrs.append({"key": "git_ref", "value": git_ref})
    return attrs


def _pack_cwl(src: str) -> bytes:
    """Run ``cwltool --pack`` against ``src`` and return the packed bytes.

    Shells out rather than importing cwltool so mcp-server install stays
    lean for users who never register workflows — cwltool has a large
    dep tree. Matches register_ngs360_workflow.sh's approach exactly.
    """
    if not shutil.which("cwltool"):
        raise RuntimeError(
            "cwltool is not on PATH — install it (pip install cwltool) "
            "before calling register_workflow / update_workflow."
        )
    # --disable-color: the stderr ends up in an error message for the
    # model, where ANSI colour codes are just noise.
    proc = subprocess.run(
        ["cwltool", "--quiet", "--disable-color", "--pack", src],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(
            f"cwltool --pack {src} failed (exit {proc.returncode}): {stderr}"
        )
    return proc.stdout


def _git_attributes_for_path(src: str) -> list[dict[str, str]]:
    """Capture git provenance for the CWL's containing directory.

    Mirrors register_ngs360_workflow.sh's git_attributes_json function.
    Returns a list of ``{key, value}`` dicts suitable for the API's
    ``WorkflowVersionCreate.attributes`` field. Empty list if ``src`` is
    not in a git checkout.
    """
    dir_ = os.path.dirname(os.path.abspath(src)) or "."

    def _git(*args: str) -> str | None:
        try:
            proc = subprocess.run(
                ["git", "-C", dir_, *args],
                capture_output=True, check=False, text=True,
            )
        except (FileNotFoundError, OSError):
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout.strip() or None

    commit = _git("rev-parse", "HEAD")
    if not commit:
        return []

    # Dirty tree makes the SHA alone a lie — mark it so retrieval sees
    # +dirty and can prompt a re-check.
    diff = subprocess.run(
        ["git", "-C", dir_, "diff", "--quiet", "HEAD", "--"],
        capture_output=True, check=False,
    )
    if diff.returncode != 0:
        commit = f"{commit}+dirty"

    repo = _git("remote", "get-url", "origin") or ""
    ref = _git("rev-parse", "--abbrev-ref", "HEAD") or ""

    attrs: list[dict[str, str]] = [{"key": "git_commit", "value": commit}]
    if repo:
        attrs.append({"key": "git_repo", "value": repo})
    if ref:
        attrs.append({"key": "git_ref", "value": ref})
    return attrs


def _timestamped_upload_name(src: str) -> str:
    """Compose ``<basename>.<UTC-stamp>.cwl`` so re-runs of the composite
    don't overwrite prior uploads under the same project/relative_path.
    Matches the shell script's naming convention."""
    base = os.path.basename(src)
    if base.endswith(".cwl"):
        base = base[:-4]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{base}.{stamp}.cwl"


async def _upload_packed_cwl(
    client: NGS360Client, packed_bytes: bytes, upload_name: str,
) -> str:
    """POST packed CWL bytes to /files/upload; return the created file id."""
    resp = await client.post_form(
        "/files/upload",
        data={
            "filename": upload_name,
            "relative_path": _UPLOAD_RELATIVE_PATH,
            "project_id": _UPLOAD_PROJECT_ID,
        },
        files={"content": (upload_name, packed_bytes)},
    )
    if not isinstance(resp, dict) or "id" not in resp:
        raise RuntimeError(
            f"unexpected /files/upload response (missing 'id'): {resp}"
        )
    return str(resp["id"])


# ----------------------------------------------------------------------
# Input/output schema capture
#
# Every registration path records the workflow's parameter schema on the
# WorkflowVersion (the API's inputs/outputs JSON columns), so consumers
# can see what a workflow needs without re-reading its CWL.
#
# Capture is best-effort by design: it is enrichment, and failing a
# registration that otherwise succeeded would be the worse outcome. The
# helpers below therefore return a warning string instead of raising,
# and the composites surface it on their result as ``io_warning`` so a
# silent fallback to null inputs/outputs cannot go unnoticed.
# ----------------------------------------------------------------------

_NGS360_URI_SCHEME = "ngs360://"


def _cwl_short_id(raw_id: Any) -> str:
    """``#main/sample_id`` -> ``sample_id``; also shortens enum symbols."""
    return str(raw_id).rsplit("/", 1)[-1]


def _cwl_type(spec: Any) -> str:
    """Render a packed CWL type in CWL's shorthand.

    Packing normalizes ``File?`` to ``["null", "File"]`` and ``File[]``
    to an array dict, so only those forms need handling. Unions render
    as ``(float|string)`` and enums keep their symbols as
    ``enum(WES|WGS)`` — the allowed values are most of the point of
    knowing a parameter is an enum.
    """
    if isinstance(spec, list):
        members = [_cwl_type(m) for m in spec if m != "null"]
        rendered = members[0] if len(members) == 1 else f"({'|'.join(members)})"
        return f"{rendered}?" if "null" in spec else rendered
    if isinstance(spec, dict):
        kind = spec.get("type")
        if kind == "array":
            return f"{_cwl_type(spec['items'])}[]"
        if kind == "enum":
            return f"enum({'|'.join(_cwl_short_id(s) for s in spec['symbols'])})"
        if kind == "record":
            return f"record({','.join(_cwl_short_id(f['name']) for f in spec['fields'])})"
        return _cwl_type(kind)
    return str(spec)


def _cwl_doc(param: dict) -> str | None:
    """Prefer ``doc``, fall back to ``label``; ``doc`` may be a list."""
    text = param.get("doc") or param.get("label")
    if isinstance(text, list):
        text = "\n".join(text)
    return text.strip() if text else None


def _io_from_packed_bytes(
    packed: bytes,
) -> tuple[list[dict] | None, list[dict] | None, str | None]:
    """Extract (inputs, outputs, warning) from ``cwltool --pack`` output.

    Shapes match the API's WorkflowInput / WorkflowOutput models. An
    input is ``required`` unless its type is optional or it declares a
    default.

    Assumes cwltool's packed form, which the local flows guarantee by
    packing first. The remote flows parse whatever was uploaded, so
    anything unexpected is caught here and reported as a warning rather
    than raised: schema capture is enrichment and must never fail a
    registration. On failure both lists are ``None``, never ``[]`` —
    the columns are nullable precisely so "never captured" stays
    distinguishable from "declares no parameters".
    """
    def fail(reason: str) -> tuple[None, None, str]:
        return None, None, f"inputs/outputs were not recorded: {reason}"

    try:
        doc = json.loads(packed)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return fail(
            "definition is not JSON. Expected the output of 'cwltool --pack "
            f"<file>.cwl'; a source .cwl in YAML will not parse ({exc})"
        )

    try:
        # A lone tool packs to a bare process; a workflow packs to a
        # $graph of every process it references. Either way cwltool
        # names the entry "#main", and only its parameters are the
        # workflow's own.
        graph = doc.get("$graph", [doc])
        main = next((p for p in graph if p.get("id") == "#main"), None)
        if main is None:
            return fail("no '#main' process found; is this cwltool --pack output?")

        inputs = []
        for param in main.get("inputs", []):
            type_str = _cwl_type(param["type"])
            entry: dict[str, Any] = {
                "id": _cwl_short_id(param["id"]),
                "type": type_str,
                "required": not (type_str.endswith("?") or "default" in param),
            }
            if text := _cwl_doc(param):
                entry["doc"] = text
            if "default" in param:
                entry["default"] = param["default"]
            inputs.append(entry)

        outputs = []
        for param in main.get("outputs", []):
            entry = {"id": _cwl_short_id(param["id"]), "type": _cwl_type(param["type"])}
            if text := _cwl_doc(param):
                entry["doc"] = text
            outputs.append(entry)

        # cwltool writes a `.inf` / `.nan` default as bare Infinity / NaN,
        # which json.loads accepts but the request body cannot carry.
        json.dumps([inputs, outputs], allow_nan=False)
    except Exception as exc:  # deliberately broad; see docstring
        return fail(f"could not read the packed CWL ({type(exc).__name__}: {exc})")

    return inputs, outputs, None


async def _presigned_bytes(client: NGS360Client, s3_uri: str) -> bytes:
    """Fetch the contents of an s3:// object via the API's presigned URL.

    Two hops: GET /files/download-url signs the object with the caller's
    own credential, then the URL itself is fetched. The second request
    deliberately uses a throwaway httpx client rather than NGS360Client
    — the presigned URL points at S3, not the API, and the shared
    client would both prefix the API path and attach the NGS360
    Authorization header to a foreign host.
    """
    presigned = await client.get("/files/download-url", params={"path": s3_uri})
    if not isinstance(presigned, dict) or not presigned.get("url"):
        raise RuntimeError(
            f"unexpected /files/download-url response for {s3_uri}: {presigned}"
        )
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as http:
        resp = await http.get(str(presigned["url"]))
        resp.raise_for_status()
        return resp.content


async def _definition_bytes(
    client: NGS360Client, definition_uri: str,
) -> bytes:
    """Download the CWL a definition_uri points at.

    Handles both schemes the API accepts: ``ngs360://<file-id>`` is
    resolved through GET /files/{id} to its underlying s3:// URI, and
    ``s3://`` is presigned directly.
    """
    if definition_uri.startswith(_NGS360_URI_SCHEME):
        file_id = definition_uri[len(_NGS360_URI_SCHEME):].strip("/")
        try:
            record = await client.get(f"/files/{file_id}")
        except httpx.HTTPStatusError as exc:
            # 404: no such file; 422: not a UUID. Raised as ValueError,
            # which _io_for_definition_uri deliberately lets through.
            if exc.response.status_code in (404, 422):
                raise ValueError(
                    f"file_id '{file_id}' does not exist on NGS360, so "
                    f"nothing was created ({_describe_http_error(exc)}). "
                    "Check the id returned by the upload."
                ) from exc
            raise
        if not isinstance(record, dict) or not record.get("uri"):
            raise RuntimeError(
                f"file {file_id} has no 'uri' to download: {record}"
            )
        return await _presigned_bytes(client, str(record["uri"]))

    if definition_uri.startswith("s3://"):
        return await _presigned_bytes(client, definition_uri)

    raise RuntimeError(
        f"cannot download definition_uri '{definition_uri}' — expected "
        "'ngs360://<file-id>' or 's3://'"
    )


async def _io_for_definition_uri(
    client: NGS360Client, definition_uri: str,
) -> tuple[list[dict] | None, list[dict] | None, str | None]:
    """Extract (inputs, outputs, warning) for an already-uploaded CWL.

    This is what makes schema capture work when the CWL is *not* on the
    MCP server's filesystem — the remote-transport flows, where the
    caller packed and uploaded the file themselves and hands over only
    a file id. Rather than asking them to also transcribe the parameter
    list, the server downloads the very bytes it is about to register
    and reads the schema off them. That also makes the recorded schema
    provably the one belonging to the stored definition.

    A file_id that does not exist is the one failure that is raised
    rather than warned about. The API resolves ``ngs360://`` only at
    deploy time, so a mistyped id would otherwise get a workflow and
    version created before the deploy step fails, leaving both pointing
    at nothing. Every caller runs this before creating anything.
    """
    try:
        raw = await _definition_bytes(client, definition_uri)
    except (httpx.HTTPError, RuntimeError, KeyError) as exc:
        reason = (
            _describe_http_error(exc)
            if isinstance(exc, httpx.HTTPStatusError) else str(exc)
        )
        return None, None, (
            "inputs/outputs were not recorded: could not download "
            f"{definition_uri} to read its schema ({reason}). The version "
            "was still created; re-record the schema later if needed."
        )
    return _io_from_packed_bytes(raw)


async def _check_workflow_exists(
    client: NGS360Client, workflow_id: str,
) -> None:
    """Verify a workflow exists before doing pack + upload work.

    Mirrors register_ngs360_workflow.sh's check_workflow_exists. Fails
    fast on a wrong workflow_id or wrong-environment mistake, saving
    the 30-90s of cwltool --pack + upload that would otherwise be
    wasted before create_workflow_version hits 404. GET is anonymous;
    the response body is discarded, only the status matters.
    """
    await client.get(f"/workflows/{workflow_id}")


async def _resolve_latest_version(
    client: NGS360Client, workflow_id: str,
) -> int:
    """Return the highest version number registered under ``workflow_id``.

    Uses ``max(v["version"] for v in versions)`` rather than trusting the
    list order — /workflows/{id}/versions sorts by created_at, which
    usually but not always aligns with the auto-increment version number.
    Mirrors register_ngs360_workflow.sh's resolve_latest_version helper.
    """
    versions = await client.get(f"/workflows/{workflow_id}/versions")
    if not isinstance(versions, list) or not versions:
        raise RuntimeError(
            f"workflow {workflow_id} has no registered versions to alias — "
            "register at least one version before setting an alias."
        )
    return max(int(v["version"]) for v in versions)


def _partial_failure_error(
    progress: dict[str, Any], exc: Exception,
) -> RuntimeError | None:
    """Explain a composite that failed after it had already created things.

    The chain is not transactional: the upload, the workflow row and the
    version row each persist the moment they are made, and nothing rolls
    them back. Instead of leaving the caller to discover them, say what
    exists and which call finishes the job reusing it — running the
    composite again from scratch would upload and create it all twice.

    Returns None when nothing was created yet, in which case the original
    error already tells the whole story.
    """
    created_any = (
        progress.get("uploaded")
        or progress.get("created_workflow")
        or "version_num" in progress
    )
    if not created_any:
        return None

    file_id = progress["file_id"]
    workflow_id = progress.get("workflow_id")
    version_num = progress.get("version_num")

    done = []
    if progress.get("uploaded"):
        done.append(f"uploaded the packed CWL as file {file_id}")
    if progress.get("created_workflow"):
        done.append(f"created workflow {workflow_id}")
    if version_num is not None:
        done.append(f"created version {version_num} of workflow {workflow_id}")

    if version_num is not None:
        step = "deploying to Omics"
        finish = (
            f"create_workflow_deployment(workflow_id='{workflow_id}', "
            f"version_num={version_num}, engine='{_OMICS_ENGINE}'). If the "
            "error was a timeout the workflow may already be registered on "
            "Omics; in that case pass its ARN as external_id instead"
        )
    elif workflow_id:
        step = "creating the version"
        finish = (
            f"update_workflow_from_file_id(file_id='{file_id}', "
            f"workflow_id='{workflow_id}')"
        )
    else:
        step = "creating the workflow"
        finish = f"register_workflow_from_file_id(file_id='{file_id}', name=...)"

    reason = (
        _describe_http_error(exc)
        if isinstance(exc, httpx.HTTPStatusError) else str(exc)
    )
    return RuntimeError(
        f"Failed while {step}: {reason}. Already done, and not rolled "
        f"back: {'; '.join(done)}. Once the cause is fixed, finish with "
        f"{finish} rather than starting over."
    )


async def _create_version_and_deploy(
    client: NGS360Client,
    workflow_id: str,
    file_id: str,
    attributes: list[dict[str, str]],
    inputs: list[dict] | None = None,
    outputs: list[dict] | None = None,
    progress: dict[str, Any] | None = None,
) -> tuple[int, str]:
    """Create a new WorkflowVersion pointing at ``file_id`` and deploy it
    to Omics via the auto-register path. Returns (version_num, arn).

    Extracted so register_workflow and update_workflow share the tail
    end of the chain — the only thing that differs between them is
    whether a Workflow row already exists.

    ``inputs``/``outputs`` are the CWL parameter schema (see
    _io_from_packed_bytes). Empty lists are sent as-is rather than
    dropped: a workflow genuinely declaring no outputs is a fact worth
    recording, and distinguishable from "never captured" (null) only if
    the empty list survives.

    ``progress`` gets ``version_num`` once the version exists, so a
    failed deploy can be reported by _partial_failure_error.
    """
    version_body: dict[str, Any] = {"definition_uri": f"ngs360://{file_id}"}
    if attributes:
        version_body["attributes"] = attributes
    if inputs is not None:
        version_body["inputs"] = inputs
    if outputs is not None:
        version_body["outputs"] = outputs
    version_resp = await client.post(
        f"/workflows/{workflow_id}/versions", json=version_body,
    )
    version_num = int(version_resp["version"])
    if progress is not None:
        progress["version_num"] = version_num

    # No external_id → server invokes the Omics register lambda and
    # returns the ARN. See create_workflow_deployment above.
    deploy_resp = await client.post(
        f"/workflows/{workflow_id}/versions/{version_num}/deployments",
        json={"engine": _OMICS_ENGINE},
    )
    return version_num, str(deploy_resp["external_id"])


def register_workflows_tools(mcp: FastMCP, client: NGS360Client) -> None:
    """Register all workflow-related tools with the MCP server."""

    @mcp.tool()
    @_surface_api_errors
    async def list_workflows(
        page: int = 1,
        per_page: int = 20,
        sort_by: str = "name",
        sort_order: str = "asc",
    ) -> list:
        """List workflows with pagination and sorting.

        Args:
            page: Page number (1-indexed)
            per_page: Number of items per page
            sort_by: Field to sort by
            sort_order: Sort order (asc or desc)
        """
        params = {
            "page": page,
            "per_page": per_page,
            "sort_by": sort_by,
            "sort_order": sort_order,
        }
        return await client.get("/workflows", params=params)

    @mcp.tool()
    @_surface_api_errors
    async def get_workflow(workflow_id: str) -> dict:
        """Get details of a specific workflow.

        Args:
            workflow_id: The workflow UUID
        """
        return await client.get(f"/workflows/{workflow_id}")

    @mcp.tool()
    @_surface_api_errors
    async def create_workflow(
        name: str,
        attributes: list[dict[str, str]] | None = None,
    ) -> dict:
        """Create a new workflow identity (row only, no version/deploy).

        For end-to-end CWL registration (pack → upload → create → deploy),
        prefer ``register_workflow`` — it wraps this call plus the version
        create and Omics deployment in a single tool call, and captures
        git provenance from the CWL's directory. Use this primitive only
        when you need to create the Workflow row without a version yet.

        Args:
            name: Workflow name
            attributes: Optional key-value attributes
                        [{"key": "category", "value": "alignment"}]
        """
        body: dict[str, Any] = {"name": name}
        if attributes:
            body["attributes"] = attributes
        return await client.post("/workflows", json=body)

    @mcp.tool()
    @_surface_api_errors
    async def create_workflow_version(
        workflow_id: str,
        definition_uri: str,
        inputs: list[dict] | None = None,
        outputs: list[dict] | None = None,
        capture_io: bool = True,
    ) -> dict:
        """Create a new version for a workflow (row only, no deploy).

        For adding a new version end-to-end (pack CWL → upload → create
        version → deploy), prefer ``update_workflow`` — it wraps this
        call plus the upload and Omics deployment, and captures git
        provenance from the CWL's directory. Use this primitive only
        when you already have a ``definition_uri`` (e.g. a pre-existing
        ``ngs360://<file_id>`` reference) and want to create the version
        row without deploying.

        Version number is auto-incremented.

        The CWL's input/output schema is recorded on the version. By
        default it is read off the definition itself: the server
        downloads ``definition_uri`` and parses its parameters, so the
        stored schema is provably the one belonging to the stored
        definition. Failure to download or parse is not fatal — the
        version is still created, and the response carries an
        ``io_warning``.

        Args:
            workflow_id: The workflow UUID
            definition_uri: URI to the workflow definition file —
                ``ngs360://<file_id>`` or ``s3://...``
            inputs: Optional explicit input schema, which skips the
                download-and-parse. Each entry is
                ``{"id", "type", "required", "doc"?, "default"?}``.
                Supply this only to correct or supplement what the CWL
                declares; normally leave it unset.
            outputs: Optional explicit output schema. Each entry is
                ``{"id", "type", "doc"?}``.
            capture_io: Set False to create the version with no schema
                at all (neither parsed nor supplied). Use when the
                definition is not reachable and the schema is unknown.
        """
        body: dict[str, Any] = {"definition_uri": definition_uri}
        io_warning: str | None = None

        if inputs is not None or outputs is not None:
            # Caller knows better than the file — take what they gave
            # and don't second-guess it with a download.
            if inputs is not None:
                body["inputs"] = inputs
            if outputs is not None:
                body["outputs"] = outputs
        elif capture_io:
            parsed_in, parsed_out, io_warning = await _io_for_definition_uri(
                client, definition_uri,
            )
            if parsed_in is not None:
                body["inputs"] = parsed_in
            if parsed_out is not None:
                body["outputs"] = parsed_out

        resp = await client.post(
            f"/workflows/{workflow_id}/versions", json=body,
        )
        if io_warning and isinstance(resp, dict):
            resp = {**resp, "io_warning": io_warning}
        return resp

    @mcp.tool()
    @_surface_api_errors
    async def list_workflow_versions(workflow_id: str) -> list:
        """List all versions of a workflow.

        Args:
            workflow_id: The workflow UUID
        """
        return await client.get(f"/workflows/{workflow_id}/versions")

    @mcp.tool()
    @_surface_api_errors
    async def get_workflow_version(
        workflow_id: str, version_num: int
    ) -> dict:
        """Get a specific workflow version.

        Args:
            workflow_id: The workflow UUID
            version_num: The version number (integer 1, 2, 3, ...), not
                the version UUID.
        """
        return await client.get(
            f"/workflows/{workflow_id}/versions/{version_num}"
        )

    @mcp.tool()
    @_surface_api_errors
    async def set_workflow_alias(
        workflow_id: str,
        alias: str,
        version_num: int | str,
    ) -> dict:
        """Set or update a workflow version alias (e.g., 'production').

        Idempotent — creates the alias if new, moves it if it already
        exists.

        Args:
            workflow_id: The workflow UUID
            alias: Alias name (e.g., production, development)
            version_num: Which version to point the alias at. Pass an
                integer (1, 2, 3, ...) for a specific version, or the
                literal string ``"latest"`` to resolve to the highest
                version registered under the workflow (mirrors
                register_ngs360_workflow.sh's ``--version latest``).
                Required — no implicit default, because "which version"
                is a decision the caller must make explicitly.
        """
        if isinstance(version_num, str):
            if version_num.strip().lower() == "latest":
                version_num = await _resolve_latest_version(client, workflow_id)
            else:
                # Defensive: LLM callers sometimes pass integers as
                # strings. Accept a numeric string; reject anything else
                # rather than sending garbage to the API.
                try:
                    version_num = int(version_num)
                except ValueError as exc:
                    raise ValueError(
                        f"version_num must be an integer or the literal "
                        f"string 'latest' (got: {version_num!r})"
                    ) from exc
        return await client.put(
            f"/workflows/{workflow_id}/aliases/{alias}",
            json={"version_num": version_num},
        )

    @mcp.tool()
    @_surface_api_errors
    async def list_workflow_aliases(
        workflow_id: str, alias: str | None = None
    ) -> list:
        """List aliases for a workflow.

        Args:
            workflow_id: The workflow UUID
            alias: Optional filter to a specific alias name
        """
        params = {}
        if alias:
            params["alias"] = alias
        return await client.get(
            f"/workflows/{workflow_id}/aliases", params=params
        )

    @mcp.tool()
    @_surface_api_errors
    async def delete_workflow_alias(workflow_id: str, alias: str) -> None:
        """Remove an alias from a workflow.

        Args:
            workflow_id: The workflow UUID
            alias: Alias name to remove
        """
        await client.delete(f"/workflows/{workflow_id}/aliases/{alias}")

    @mcp.tool()
    @_surface_api_errors
    async def create_workflow_deployment(
        workflow_id: str,
        version_num: int,
        engine: str,
        external_id: str | None = None,
    ) -> dict:
        """Deploy a workflow version on a specific platform.

        For end-to-end CWL registration onto AWS HealthOmics, prefer
        ``register_workflow`` (new workflow) or ``update_workflow`` (new
        version of an existing workflow) — those composites call this
        deployment step for you after packing and uploading the CWL. Use
        this primitive directly for non-Omics engines (Arvados /
        SevenBridges) or for the repair-by-external_id path where the
        Omics registration already completed on AWS but the deployment
        row was lost (e.g. after a Lambda read timeout on the API side).

        Two supported flows on the server side:

        * Caller supplies ``external_id`` — trusted and stored as-is. Use
          for Arvados / SevenBridges where the workflow was registered
          out-of-band and you already have its id.
        * Caller omits ``external_id`` with engine
          ``"AWSHealthOmics (us-east)"`` — the server registers the
          workflow on AWS HealthOmics via a Lambda and returns the ARN
          as the deployment's ``external_id``. This is the auto-register
          path that ``register_workflow`` builds on.

        For any other engine, ``external_id`` is required — the server
        returns 400 if it is not supplied.

        Args:
            workflow_id: The workflow UUID.
            version_num: The version number (integer 1, 2, 3, ...), not
                the version UUID. Matches the API's path parameter.
            engine: Platform name — e.g. "Arvados", "SevenBridges",
                "AWSHealthOmics (us-east)".
            external_id: Workflow identifier on the external platform.
                Omit to trigger the Omics auto-register flow (only valid
                when ``engine == "AWSHealthOmics (us-east)"``).
        """
        body: dict[str, Any] = {"engine": engine}
        if external_id is not None:
            body["external_id"] = external_id
        return await client.post(
            f"/workflows/{workflow_id}/versions/{version_num}/deployments",
            json=body,
        )

    @mcp.tool()
    @_surface_api_errors
    async def list_workflow_deployments(
        workflow_id: str,
        version_num: int | None = None,
        alias: str | None = None,
        engine: str | None = None,
    ) -> list:
        """List deployments for a workflow.

        Can list across all versions or for a specific version.

        Args:
            workflow_id: The workflow UUID
            version_num: Optional version number (integer). If omitted,
                deployments across all versions are returned.
            alias: Optional alias filter (resolves to version)
            engine: Optional engine/platform filter
        """
        params: dict[str, Any] = {}
        if alias:
            params["alias"] = alias
        if engine:
            params["engine"] = engine

        if version_num is not None:
            return await client.get(
                f"/workflows/{workflow_id}/versions/{version_num}/deployments",
                params=params,
            )
        return await client.get(
            f"/workflows/{workflow_id}/deployments", params=params
        )

    @mcp.tool()
    @_surface_api_errors
    async def delete_workflow_deployment(
        workflow_id: str, version_num: int, deployment_id: str
    ) -> None:
        """Remove a platform deployment.

        Args:
            workflow_id: The workflow UUID
            version_num: The version number (integer 1, 2, 3, ...), not
                the version UUID.
            deployment_id: The deployment UUID
        """
        await client.delete(
            f"/workflows/{workflow_id}/versions/{version_num}"
            f"/deployments/{deployment_id}"
        )

    # ------------------------------------------------------------------
    # Composite tools — pack → upload → create → deploy in one call
    # ------------------------------------------------------------------

    @mcp.tool()
    @_surface_api_errors
    async def register_workflow(
        cwl_path: str,
        name: str,
    ) -> dict:
        """Register a NEW workflow on NGS360, end-to-end.

        Runs the pack → upload → create-workflow → create-version →
        deploy chain that register_ngs360_workflow.sh does from the CLI.
        On mid-chain failure earlier steps' resources (uploaded file,
        created workflow row, version) remain in NGS360. The error then
        lists what was created and names the call that finishes the job
        reusing it; follow that rather than re-running this tool, which
        would upload and create everything again.

        Git provenance (git_commit, git_repo, git_ref) is captured from
        the CWL's containing directory and attached to the version as
        attributes. A dirty working tree records git_commit as
        ``<sha>+dirty``. If cwl_path is not in a git checkout, no
        git_* attributes are recorded.

        Deploys to ``AWSHealthOmics (us-east)`` — the server auto-
        registers on Omics via a Lambda and returns the ARN.

        The workflow's input/output schema (parameter ids, types,
        required-ness, docs and defaults) is read from the packed CWL
        and recorded on the version, so later callers can see what the
        workflow needs without re-reading its definition.

        Args:
            cwl_path: Local path (on the MCP server's filesystem) to the
                source .cwl file. Packed with cwltool; its containing
                directory is inspected for git provenance.
            name: Human-readable workflow name shown in the NGS360 UI
                and Omics console. Prefer the CWL file's top-level
                ``label`` field if present — that's the workflow
                author's canonical name (e.g. "WES alignment
                (Translational)"). Fall back to the filename without
                ``.cwl`` if the CWL has no label.

        Returns:
            workflow_id: NGS360 Workflow UUID
            version_num: WorkflowVersion number (always 1 for a new workflow)
            file_id: NGS360 File UUID of the packed CWL
            omics_arn: Full Omics workflow ARN
            inputs_recorded / outputs_recorded: how many parameters were
                recorded, or null if the schema could not be read
            io_warning: present only when the schema could not be read —
                registration still succeeded. Relay it to the user.

        Under remote MCP transport (streamable-http) this tool cannot
        work — cwl_path resolves on the server host, not the caller's
        machine. Use ``register_workflow_from_file_id`` instead after
        packing and uploading the CWL manually; see that tool's
        docstring for the step-by-step curl guidance.
        """
        _require_stdio_transport(
            "register_workflow", "register_workflow_from_file_id",
        )
        if not os.path.isfile(cwl_path):
            raise ValueError(f"CWL file not found: {cwl_path}")

        packed = _pack_cwl(cwl_path)
        attributes = _git_attributes_for_path(cwl_path)
        inputs, outputs, io_warning = _io_from_packed_bytes(packed)
        upload_name = _timestamped_upload_name(cwl_path)
        progress: dict[str, Any] = {}
        try:
            file_id = await _upload_packed_cwl(client, packed, upload_name)
            progress.update(file_id=file_id, uploaded=True)

            wf_resp = await client.post("/workflows", json={"name": name})
            workflow_id = str(wf_resp["id"])
            progress.update(workflow_id=workflow_id, created_workflow=True)

            version_num, omics_arn = await _create_version_and_deploy(
                client, workflow_id, file_id, attributes, inputs, outputs,
                progress,
            )
        except Exception as exc:
            if err := _partial_failure_error(progress, exc):
                raise err from exc
            raise
        result = {
            "workflow_id": workflow_id,
            "version_num": version_num,
            "file_id": file_id,
            "omics_arn": omics_arn,
            "inputs_recorded": len(inputs) if inputs is not None else None,
            "outputs_recorded": len(outputs) if outputs is not None else None,
        }
        if io_warning:
            result["io_warning"] = io_warning
        return result

    @mcp.tool()
    @_surface_api_errors
    async def update_workflow(
        cwl_path: str,
        workflow_id: str,
    ) -> dict:
        """Add a new version to an EXISTING workflow and deploy it.

        Runs pack → upload → create-version → deploy against the given
        workflow_id. Skips the workflow-creation step of
        register_workflow. Everything else (git capture, input/output
        schema capture, timestamped upload, Omics auto-register)
        matches.

        Args:
            cwl_path: Local path to the source .cwl file.
            workflow_id: NGS360 Workflow UUID to add a new version under.

        Returns:
            workflow_id: echo of the argument
            version_num: new WorkflowVersion number (server auto-increments)
            file_id: NGS360 File UUID of the packed CWL
            omics_arn: Full Omics workflow ARN for this new version
            inputs_recorded / outputs_recorded: how many parameters were
                recorded, or null if the schema could not be read
            io_warning: present only when the schema could not be read —
                the new version was still created. Relay it to the user.

        Under remote MCP transport (streamable-http) this tool cannot
        work — cwl_path resolves on the server host, not the caller's
        machine. Use ``update_workflow_from_file_id`` instead after
        packing and uploading the CWL manually; see that tool's
        docstring for the step-by-step curl guidance.
        """
        _require_stdio_transport(
            "update_workflow", "update_workflow_from_file_id",
        )
        if not os.path.isfile(cwl_path):
            raise ValueError(f"CWL file not found: {cwl_path}")

        # Preflight the workflow_id before packing/uploading — a wrong id
        # or wrong-environment mistake used to strand a packed CWL upload
        # in S3 before the deploy step surfaced the 404.
        await _check_workflow_exists(client, workflow_id)

        packed = _pack_cwl(cwl_path)
        attributes = _git_attributes_for_path(cwl_path)
        inputs, outputs, io_warning = _io_from_packed_bytes(packed)
        upload_name = _timestamped_upload_name(cwl_path)
        progress: dict[str, Any] = {"workflow_id": workflow_id}
        try:
            file_id = await _upload_packed_cwl(client, packed, upload_name)
            progress.update(file_id=file_id, uploaded=True)

            version_num, omics_arn = await _create_version_and_deploy(
                client, workflow_id, file_id, attributes, inputs, outputs,
                progress,
            )
        except Exception as exc:
            if err := _partial_failure_error(progress, exc):
                raise err from exc
            raise
        result = {
            "workflow_id": workflow_id,
            "version_num": version_num,
            "file_id": file_id,
            "omics_arn": omics_arn,
            "inputs_recorded": len(inputs) if inputs is not None else None,
            "outputs_recorded": len(outputs) if outputs is not None else None,
        }
        if io_warning:
            result["io_warning"] = io_warning
        return result

    # ------------------------------------------------------------------
    # Composite tools for remote MCP (no local filesystem) — caller has
    # already uploaded the packed CWL and hands us the file_id.
    # ------------------------------------------------------------------

    @mcp.tool()
    @_surface_api_errors
    async def register_workflow_from_file_id(
        file_id: str,
        name: str,
        git_commit: str | None = None,
        git_repo: str | None = None,
        git_ref: str | None = None,
    ) -> dict:
        """Register a NEW workflow when the caller already has a packed
        CWL uploaded to NGS360 (i.e. has a ``file_id`` in hand). Use
        this when running under remote MCP transport (no local
        filesystem) or in any other flow where the CWL is already
        uploaded.

        Runs create-workflow → create-version → deploy against the
        given ``file_id``. Skips packing, uploading, and local git-
        provenance capture. Git values may be passed in explicitly for
        the same traceability the local composite provides.

        Deploys to ``AWSHealthOmics (us-east)`` — the server auto-
        registers on Omics via a Lambda and returns the ARN.

        The input/output schema needs nothing from the caller: the
        server downloads the uploaded file and reads the parameters off
        it, exactly as the local composite reads them off the bytes it
        packed. Do not ask the user to transcribe their workflow's
        parameters.

        If the caller does NOT yet have a file_id, guide the user
        through these steps first (in a UI or chat, before calling
        this tool):

          1. Install cwltool (once, per machine):
                 pip install cwltool

          2. Pack the CWL locally:
                 cwltool --pack <path/to/workflow.cwl> > packed.cwl

          3. Set NGS360 auth env vars (once, per shell):
                 export NGS360_API_ENDPOINT=<your NGS360 API base URL, ending in /api/v1>
                 export NGS360_AUTH_TOKEN=<their bearer token>

          4. Upload the packed CWL and capture the file id from the JSON
             response (its ``id`` field):
                 curl -s -X POST "$NGS360_API_ENDPOINT/files/upload" \\
                   -H "Authorization: Bearer $NGS360_AUTH_TOKEN" \\
                   -F "filename=<name>.packed.cwl" \\
                   -F "relative_path=workflow_definition_file" \\
                   -F "project_id=P-00000000-0001" \\
                   -F "content=@packed.cwl"

          5. Optional but strongly encouraged — capture git provenance
             so the version has the same traceability tags as a
             locally-registered workflow:
                 git rev-parse HEAD                    # → git_commit
                 git remote get-url origin             # → git_repo
                 git rev-parse --abbrev-ref HEAD       # → git_ref

          6. Call this tool with the file_id and (optional) git values.

        Args:
            file_id: NGS360 File UUID of the already-uploaded packed CWL.
            name: Human-readable workflow name shown in the NGS360 UI
                and Omics console. Prefer the CWL file's top-level
                ``label`` field if the user has it; otherwise the base
                filename without ``.cwl``.
            git_commit: Optional git SHA (or ``<sha>+dirty``) captured
                from the CWL's source repo. Skipped if not provided.
            git_repo: Optional git repo URL (e.g. ``git remote get-url
                origin`` output). Skipped if not provided.
            git_ref: Optional branch/tag name from the CWL's source
                repo (e.g. ``main``). Skipped if not provided.

        Returns:
            workflow_id: NGS360 Workflow UUID
            version_num: WorkflowVersion number (always 1 for a new workflow)
            file_id: echo of the argument
            omics_arn: Full Omics workflow ARN
            inputs_recorded / outputs_recorded: how many parameters were
                recorded, or null if the schema could not be read
            io_warning: present only when the schema could not be read —
                registration still succeeded. Relay it to the user.
        """
        attributes = _git_attributes_from_args(git_commit, git_repo, git_ref)
        inputs, outputs, io_warning = await _io_for_definition_uri(
            client, f"ngs360://{file_id}",
        )

        progress: dict[str, Any] = {"file_id": file_id}
        try:
            wf_resp = await client.post("/workflows", json={"name": name})
            workflow_id = str(wf_resp["id"])
            progress.update(workflow_id=workflow_id, created_workflow=True)

            version_num, omics_arn = await _create_version_and_deploy(
                client, workflow_id, file_id, attributes, inputs, outputs,
                progress,
            )
        except Exception as exc:
            if err := _partial_failure_error(progress, exc):
                raise err from exc
            raise
        result = {
            "workflow_id": workflow_id,
            "version_num": version_num,
            "file_id": file_id,
            "omics_arn": omics_arn,
            "inputs_recorded": len(inputs) if inputs is not None else None,
            "outputs_recorded": len(outputs) if outputs is not None else None,
        }
        if io_warning:
            result["io_warning"] = io_warning
        return result

    @mcp.tool()
    @_surface_api_errors
    async def update_workflow_from_file_id(
        file_id: str,
        workflow_id: str,
        git_commit: str | None = None,
        git_repo: str | None = None,
        git_ref: str | None = None,
    ) -> dict:
        """Add a new version to an EXISTING workflow when the caller
        already has the packed CWL uploaded to NGS360. Remote-MCP
        counterpart to ``update_workflow``.

        Runs create-version → deploy against the given ``file_id`` and
        ``workflow_id``. Preflight-checks that the workflow exists
        before doing any work. The input/output schema is read from the
        uploaded file by the server — nothing for the caller to supply.

        If the caller does NOT yet have a file_id, walk the user
        through the pack + upload steps documented on
        ``register_workflow_from_file_id`` — the same procedure
        applies. Only the last step (which tool to call) differs.

        Args:
            file_id: NGS360 File UUID of the already-uploaded packed CWL.
            workflow_id: NGS360 Workflow UUID to add the new version under.
            git_commit: Optional. See register_workflow_from_file_id docs.
            git_repo: Optional. See register_workflow_from_file_id docs.
            git_ref: Optional. See register_workflow_from_file_id docs.

        Returns:
            workflow_id: echo of the argument
            version_num: new WorkflowVersion number
            file_id: echo of the argument
            omics_arn: Full Omics workflow ARN for this new version
            inputs_recorded / outputs_recorded: how many parameters were
                recorded, or null if the schema could not be read
            io_warning: present only when the schema could not be read —
                the new version was still created. Relay it to the user.
        """
        await _check_workflow_exists(client, workflow_id)
        attributes = _git_attributes_from_args(git_commit, git_repo, git_ref)
        inputs, outputs, io_warning = await _io_for_definition_uri(
            client, f"ngs360://{file_id}",
        )

        progress: dict[str, Any] = {"file_id": file_id, "workflow_id": workflow_id}
        try:
            version_num, omics_arn = await _create_version_and_deploy(
                client, workflow_id, file_id, attributes, inputs, outputs,
                progress,
            )
        except Exception as exc:
            if err := _partial_failure_error(progress, exc):
                raise err from exc
            raise
        result = {
            "workflow_id": workflow_id,
            "version_num": version_num,
            "file_id": file_id,
            "omics_arn": omics_arn,
            "inputs_recorded": len(inputs) if inputs is not None else None,
            "outputs_recorded": len(outputs) if outputs is not None else None,
        }
        if io_warning:
            result["io_warning"] = io_warning
        return result
