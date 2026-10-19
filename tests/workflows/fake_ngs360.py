"""In-memory stand-in for the NGS360 API and S3.

Served through ``httpx.MockTransport``, so tools run against the real
NGS360Client and the real HTTP stack with no network. The routes follow
APIServer's workflow and file routes closely enough to matter: auth on
writes, UUID path validation (422), 404s, WorkflowVersionCreate body
validation, 204 on delete, and ``ngs360://`` resolved only at deploy
time — which is what made an unknown file_id dangerous.
"""

import json
import re
import uuid
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

API_URL = "https://api.test"
S3_HOST = "s3.test"
TOKEN = "test-token"
OMICS_ENGINE = "AWSHealthOmics (us-east)"


# Mirrors APIServer api/workflow/models.py, so a body the real API would
# reject with 422 is rejected here too.
class _Attribute(BaseModel):
    key: str
    value: str


class _WorkflowInput(BaseModel):
    id: str
    type: str
    required: bool
    doc: str | None = None
    default: Any | None = None


class _WorkflowOutput(BaseModel):
    id: str
    type: str
    doc: str | None = None


class _WorkflowVersionCreate(BaseModel):
    definition_uri: str
    attributes: list[_Attribute] | None = None
    inputs: list[_WorkflowInput] | None = None
    outputs: list[_WorkflowOutput] | None = None


def _multipart_fields(request: httpx.Request) -> dict[str, bytes]:
    boundary = re.search(r"boundary=(.+)", request.headers["content-type"]).group(1)
    fields = {}
    for part in request.content.split(b"--" + boundary.encode()):
        if b'name="' not in part:
            continue
        head, _, body = part.partition(b"\r\n\r\n")
        name = re.search(rb'name="([^"]+)"', head).group(1).decode()
        fields[name] = body[:-2] if body.endswith(b"\r\n") else body
    return fields


def _json(status: int, body: Any) -> httpx.Response:
    return httpx.Response(status, json=body)


def _detail(status: int, detail: Any) -> httpx.Response:
    return _json(status, {"detail": detail})


class FakeNGS360:
    def __init__(self) -> None:
        self.files: dict[str, dict] = {}        # file id -> record
        self.s3: dict[str, bytes] = {}          # object key -> bytes
        self.workflows: dict[str, dict] = {}    # workflow id -> record
        self.versions: dict[str, list[dict]] = {}
        self.aliases: dict[str, dict[str, int]] = {}
        self.deployments: list[dict] = []
        self.requests: list[httpx.Request] = []
        self._faults: list[tuple[str, str, httpx.Response]] = []
        self.s3_saw_authorization = False

    # ---- test setup -------------------------------------------------------
    def add_file(self, content: bytes, filename: str = "seeded.packed.cwl") -> str:
        file_id = str(uuid.uuid4())
        key = f"workflow_definition_file/{filename}"
        self.files[file_id] = {"id": file_id, "uri": f"s3://test-bucket/{key}",
                               "filename": filename}
        self.s3[key] = content
        return file_id

    def add_workflow(self, name: str = "existing", versions: int = 1) -> str:
        workflow_id = uuid.uuid4().hex
        self.workflows[workflow_id] = {"id": workflow_id, "name": name, "attributes": None}
        self.versions[workflow_id] = []
        self.aliases[workflow_id] = {}
        for _ in range(versions):
            self._new_version(workflow_id, {"definition_uri": "ngs360://seeded"})
        return workflow_id

    def fail(self, method: str, path_regex: str, status: int,
             body: Any = None, *, text: str | None = None) -> None:
        """Make requests matching ``method`` and ``path_regex`` fail.

        ``method`` "S3" targets the object store; the regex is matched
        against the API path with its /api/v1 prefix removed.
        """
        if text is not None:
            resp = httpx.Response(status, text=text)
        else:
            resp = _json(status, body if body is not None else {"detail": f"injected {status}"})
        self._faults.append((method, path_regex, resp))

    # ---- inspection -------------------------------------------------------
    def calls(self, method: str | None = None) -> list[tuple[str, str]]:
        out = []
        for r in self.requests:
            m = "S3" if r.url.host == S3_HOST else r.method
            if method is None or m == method:
                out.append((m, r.url.path.removeprefix("/api/v1")))
        return out

    def writes(self) -> list[tuple[str, str]]:
        return [c for c in self.calls() if c[0] not in ("GET", "S3")]

    def latest_version(self, workflow_id: str | None = None) -> dict:
        workflow_id = workflow_id or next(reversed(self.workflows))
        return self.versions[workflow_id][-1]

    # ---- transport --------------------------------------------------------
    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == S3_HOST:
            return self._s3(request)
        path = request.url.path.removeprefix("/api/v1")
        for method, regex, resp in self._faults:
            if method == request.method and re.fullmatch(regex, path):
                return resp
        return self._api(request, path)

    def _s3(self, request: httpx.Request) -> httpx.Response:
        if "authorization" in request.headers:
            self.s3_saw_authorization = True
        for method, regex, resp in self._faults:
            if method == "S3" and re.search(regex, request.url.path):
                return resp
        key = request.url.path.lstrip("/")
        if key not in self.s3:
            return httpx.Response(404, text="<Error><Code>NoSuchKey</Code></Error>")
        return httpx.Response(200, content=self.s3[key])

    def _new_version(self, workflow_id: str, body: dict) -> dict:
        versions = self.versions[workflow_id]
        row = {"id": str(uuid.uuid4()), "workflow_id": workflow_id,
               "version": max((v["version"] for v in versions), default=0) + 1,
               "attributes": None, "inputs": None, "outputs": None, **body}
        versions.append(row)
        return row

    def _version(self, workflow_id: str, version_num: int) -> dict | None:
        return next((v for v in self.versions.get(workflow_id, [])
                     if v["version"] == version_num), None)

    def _api(self, request: httpx.Request, path: str) -> httpx.Response:
        method = request.method
        authed = request.headers.get("authorization") == f"Bearer {TOKEN}"
        unauthorized = _detail(401, "Could not validate credentials")
        body = json.loads(request.content) if request.content and \
            request.headers.get("content-type", "").startswith("application/json") else None

        # --- files ---------------------------------------------------------
        if method == "POST" and path == "/files/upload":
            if not authed:
                return unauthorized
            fields = _multipart_fields(request)
            file_id = self.add_file(fields["content"], fields["filename"].decode())
            self.files[file_id]["form"] = {k: v.decode() for k, v in fields.items()
                                           if k != "content"}
            return _json(201, self.files[file_id])

        if method == "GET" and path == "/files/download-url":
            if not authed:
                return unauthorized
            key = request.url.params["path"].split("/", 3)[3]
            return _json(200, {"url": f"https://{S3_HOST}/{key}?X-Amz-Signature=secret",
                               "expires_in": 3600})

        if method == "GET" and (m := re.fullmatch(r"/files/([^/]+)", path)):
            try:
                file_id = str(uuid.UUID(m.group(1)))
            except ValueError:
                return _detail(422, [{"loc": ["path", "file_id"],
                                      "msg": "Input should be a valid UUID"}])
            if file_id not in self.files:
                return _detail(404, f"File {file_id} not found")
            return _json(200, self.files[file_id])

        # --- workflows -----------------------------------------------------
        if path == "/workflows":
            if method == "GET":
                return _json(200, list(self.workflows.values()))
            if not authed:
                return unauthorized
            workflow_id = uuid.uuid4().hex
            self.workflows[workflow_id] = {"id": workflow_id, "name": body["name"],
                                           "attributes": body.get("attributes")}
            self.versions[workflow_id] = []
            self.aliases[workflow_id] = {}
            return _json(201, self.workflows[workflow_id])

        m = re.fullmatch(r"/workflows/([^/]+)(/.*)?", path)
        if not m:
            return _detail(404, f"no fake route for {method} {path}")
        workflow_id, rest = m.group(1), m.group(2) or ""
        if workflow_id not in self.workflows:
            return _detail(404, "Workflow not found")
        if method != "GET" and not authed:
            return unauthorized

        if rest == "" and method == "GET":
            return _json(200, self.workflows[workflow_id])

        if rest == "/versions":
            if method == "GET":
                return _json(200, self.versions[workflow_id])
            try:
                parsed = _WorkflowVersionCreate.model_validate(body)
            except ValidationError as exc:
                return _detail(422, exc.errors(include_url=False, include_input=False))
            # APIServer stores model_dump(): absent optional fields become null.
            return _json(201, self._new_version(workflow_id, parsed.model_dump()))

        if m := re.fullmatch(r"/versions/(\d+)", rest):
            version = self._version(workflow_id, int(m.group(1)))
            return _json(200, version) if version else _detail(404, "Version not found")

        if m := re.fullmatch(r"/aliases/([^/]+)", rest):
            alias = m.group(1)
            if method == "PUT":
                version_num = body["version_num"]
                if not self._version(workflow_id, version_num):
                    return _detail(404, f"Version {version_num} not found")
                self.aliases[workflow_id][alias] = version_num
                return _json(200, {"alias": alias, "version": version_num})
            if method == "DELETE":
                if self.aliases[workflow_id].pop(alias, None) is None:
                    return _detail(404, "Alias not found")
                return httpx.Response(204)

        if rest == "/aliases" and method == "GET":
            wanted = request.url.params.get("alias")
            return _json(200, [{"alias": a, "version": v}
                               for a, v in self.aliases[workflow_id].items()
                               if wanted in (None, a)])

        if rest == "/deployments" and method == "GET":
            return _json(200, self._deployments(workflow_id, None, request))

        if m := re.fullmatch(r"/versions/(\d+)/deployments", rest):
            version_num = int(m.group(1))
            version = self._version(workflow_id, version_num)
            if not version:
                return _detail(404, "Version not found")
            if method == "GET":
                return _json(200, self._deployments(workflow_id, version_num, request))
            return self._deploy(workflow_id, version, body)

        if m := re.fullmatch(r"/versions/(\d+)/deployments/([^/]+)", rest):
            if method == "DELETE":
                before = len(self.deployments)
                self.deployments = [d for d in self.deployments if d["id"] != m.group(2)]
                if len(self.deployments) == before:
                    return _detail(404, "Deployment not found")
                return httpx.Response(204)

        return _detail(404, f"no fake route for {method} {path}")

    def _deployments(self, workflow_id, version_num, request) -> list[dict]:
        engine = request.url.params.get("engine")
        return [d for d in self.deployments
                if d["workflow_id"] == workflow_id
                and version_num in (None, d["version"])
                and engine in (None, d["engine"])]

    def _deploy(self, workflow_id: str, version: dict, body: dict) -> httpx.Response:
        engine, external_id = body["engine"], body.get("external_id")
        if external_id is None:
            if engine != OMICS_ENGINE:
                return _detail(400, f"external_id is required for engine '{engine}'")
            # The real API resolves the definition here, on its way to the
            # Omics Lambda — not when the version row was created.
            uri = version["definition_uri"]
            if uri.startswith("ngs360://"):
                raw = uri[len("ngs360://"):]
                try:
                    file_id = str(uuid.UUID(raw))
                except ValueError:
                    return _detail(400, f"Invalid NGS360 file id in definition_uri '{uri}'")
                if file_id not in self.files:
                    return _detail(404, f"NGS360 file '{raw}' not found.")
            external_id = f"arn:aws:omics:us-east-1:000000000000:workflow/{version['version']}"
        row = {"id": str(uuid.uuid4()), "workflow_id": workflow_id,
               "version": version["version"], "engine": engine, "external_id": external_id}
        self.deployments.append(row)
        return _json(201, row)
