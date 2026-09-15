"""MCP tools for the Workflows API."""

import os
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any

from mcp.server.fastmcp import FastMCP

from ngs360_mcp_server.client import NGS360Client


# Constants baked into register_ngs360_workflow.sh. Kept identical so
# MCP-registered workflows are indistinguishable from shell-registered
# ones downstream (same project prefix, same relative_path, same engine).
_OMICS_ENGINE = "AWSHealthOmics (us-east)"
_UPLOAD_PROJECT_ID = "P-00000000-0001"
_UPLOAD_RELATIVE_PATH = "workflow_definition_file"


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
    proc = subprocess.run(
        ["cwltool", "--quiet", "--pack", src],
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


async def _create_version_and_deploy(
    client: NGS360Client,
    workflow_id: str,
    file_id: str,
    attributes: list[dict[str, str]],
) -> tuple[int, str]:
    """Create a new WorkflowVersion pointing at ``file_id`` and deploy it
    to Omics via the auto-register path. Returns (version_num, arn).

    Extracted so register_workflow and update_workflow share the tail
    end of the chain — the only thing that differs between them is
    whether a Workflow row already exists.
    """
    version_body: dict[str, Any] = {"definition_uri": f"ngs360://{file_id}"}
    if attributes:
        version_body["attributes"] = attributes
    version_resp = await client.post(
        f"/workflows/{workflow_id}/versions", json=version_body,
    )
    version_num = int(version_resp["version"])

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
    async def get_workflow(workflow_id: str) -> dict:
        """Get details of a specific workflow.

        Args:
            workflow_id: The workflow UUID
        """
        return await client.get(f"/workflows/{workflow_id}")

    @mcp.tool()
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
    async def create_workflow_version(
        workflow_id: str, definition_uri: str
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

        Args:
            workflow_id: The workflow UUID
            definition_uri: URI to the workflow definition file
        """
        return await client.post(
            f"/workflows/{workflow_id}/versions",
            json={"definition_uri": definition_uri},
        )

    @mcp.tool()
    async def list_workflow_versions(workflow_id: str) -> list:
        """List all versions of a workflow.

        Args:
            workflow_id: The workflow UUID
        """
        return await client.get(f"/workflows/{workflow_id}/versions")

    @mcp.tool()
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
    async def delete_workflow_alias(workflow_id: str, alias: str) -> None:
        """Remove an alias from a workflow.

        Args:
            workflow_id: The workflow UUID
            alias: Alias name to remove
        """
        await client.delete(f"/workflows/{workflow_id}/aliases/{alias}")

    @mcp.tool()
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
    async def register_workflow(
        cwl_path: str,
        name: str,
    ) -> dict:
        """Register a NEW workflow on NGS360, end-to-end.

        Runs the pack → upload → create-workflow → create-version →
        deploy chain that register_ngs360_workflow.sh does from the CLI.
        On mid-chain failure earlier steps' resources (uploaded file,
        created workflow row) remain in NGS360; recover by continuing
        manually or by calling update_workflow with the returned
        workflow_id from a partial run.

        Git provenance (git_commit, git_repo, git_ref) is captured from
        the CWL's containing directory and attached to the version as
        attributes. A dirty working tree records git_commit as
        ``<sha>+dirty``. If cwl_path is not in a git checkout, no
        git_* attributes are recorded.

        Deploys to ``AWSHealthOmics (us-east)`` — the server auto-
        registers on Omics via a Lambda and returns the ARN.

        Args:
            cwl_path: Local path (on the MCP server's filesystem) to the
                source .cwl file. Packed with cwltool; its containing
                directory is inspected for git provenance.
            name: Human-readable workflow name shown in the NGS360 UI
                and Omics console.

        Returns:
            workflow_id: NGS360 Workflow UUID
            version_num: WorkflowVersion number (always 1 for a new workflow)
            file_id: NGS360 File UUID of the packed CWL
            omics_arn: Full Omics workflow ARN
        """
        if not os.path.isfile(cwl_path):
            raise ValueError(f"CWL file not found: {cwl_path}")

        packed = _pack_cwl(cwl_path)
        attributes = _git_attributes_for_path(cwl_path)
        upload_name = _timestamped_upload_name(cwl_path)
        file_id = await _upload_packed_cwl(client, packed, upload_name)

        wf_resp = await client.post("/workflows", json={"name": name})
        workflow_id = str(wf_resp["id"])

        version_num, omics_arn = await _create_version_and_deploy(
            client, workflow_id, file_id, attributes,
        )
        return {
            "workflow_id": workflow_id,
            "version_num": version_num,
            "file_id": file_id,
            "omics_arn": omics_arn,
        }

    @mcp.tool()
    async def update_workflow(
        cwl_path: str,
        workflow_id: str,
    ) -> dict:
        """Add a new version to an EXISTING workflow and deploy it.

        Runs pack → upload → create-version → deploy against the given
        workflow_id. Skips the workflow-creation step of
        register_workflow. Everything else (git capture, timestamped
        upload, Omics auto-register) matches.

        Args:
            cwl_path: Local path to the source .cwl file.
            workflow_id: NGS360 Workflow UUID to add a new version under.

        Returns:
            workflow_id: echo of the argument
            version_num: new WorkflowVersion number (server auto-increments)
            file_id: NGS360 File UUID of the packed CWL
            omics_arn: Full Omics workflow ARN for this new version
        """
        if not os.path.isfile(cwl_path):
            raise ValueError(f"CWL file not found: {cwl_path}")

        packed = _pack_cwl(cwl_path)
        attributes = _git_attributes_for_path(cwl_path)
        upload_name = _timestamped_upload_name(cwl_path)
        file_id = await _upload_packed_cwl(client, packed, upload_name)

        version_num, omics_arn = await _create_version_and_deploy(
            client, workflow_id, file_id, attributes,
        )
        return {
            "workflow_id": workflow_id,
            "version_num": version_num,
            "file_id": file_id,
            "omics_arn": omics_arn,
        }
