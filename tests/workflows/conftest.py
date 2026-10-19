"""Fixtures for the workflow-tool tests.

``fake``    the in-memory NGS360 API + S3 every request is routed to
``tools``   the workflow tools as plain async functions, for asserting
            on results and on the exceptions they raise
``mcp_call``  invoke a tool through a real in-memory MCP client session,
            for asserting on exactly what a model receives
"""

import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from ngs360_mcp_server.client import NGS360Client
from ngs360_mcp_server.tools.workflows import register_workflows_tools

from .fake_ngs360 import API_URL, TOKEN, FakeNGS360

DATA = Path(__file__).parent / "data"
CWL = DATA / "cwl"
PACKED = DATA / "packed"

requires_cwltool = pytest.mark.skipif(
    shutil.which("cwltool") is None,
    reason="cwltool is not on PATH (pip install cwltool)",
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _stdio_transport(monkeypatch):
    # The local-file tools refuse to run under streamable-http.
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)


@pytest.fixture
def fake(monkeypatch) -> FakeNGS360:
    """Route every httpx.AsyncClient — the API client and the S3 fetch — to
    one FakeNGS360."""
    fake = FakeNGS360()
    real = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(fake.handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return fake


class _ToolRecorder:
    """Stands in for FastMCP: collects the functions registered as tools."""

    def __init__(self) -> None:
        self.fns = {}

    def tool(self, *args, **kwargs):
        def register(fn):
            self.fns[fn.__name__] = fn
            return fn
        return register


def _make_client(token: str = TOKEN) -> NGS360Client:
    return NGS360Client(base_url=API_URL, token=token)


@pytest.fixture
def tools(fake):
    recorder = _ToolRecorder()
    register_workflows_tools(recorder, _make_client())
    return type("Tools", (), recorder.fns)


@pytest.fixture
def tools_with_token(fake):
    """Factory for tools whose client sends a given token."""
    def make(token: str):
        recorder = _ToolRecorder()
        register_workflows_tools(recorder, _make_client(token))
        return type("Tools", (), recorder.fns)
    return make


@pytest.fixture
def mcp_server(fake):
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("ngs360-test")
    register_workflows_tools(server, _make_client())
    return server


@pytest.fixture
def mcp_call(mcp_server):
    from mcp.shared.memory import create_connected_server_and_client_session

    async def call(tool: str, arguments: dict):
        async with create_connected_server_and_client_session(
            mcp_server._mcp_server
        ) as session:
            return await session.call_tool(tool, arguments)
    return call


@pytest.fixture
def git_repo(tmp_path) -> Path:
    """A throwaway git checkout holding good_tool.cwl, committed clean."""
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copy(CWL / "good_tool.cwl", repo / "good_tool.cwl")

    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True,
                       capture_output=True)

    git("init", "-b", "main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "test")
    git("remote", "add", "origin", "https://example.com/org/workflows.git")
    git("add", ".")
    git("commit", "-m", "init")
    return repo


# Hand-checked against tests/workflows/data/cwl/*.cwl. cwltool --pack
# sorts parameters by id, which is why the order differs from the source.
GOOD_TOOL_INPUTS = [
    {"id": "mode", "type": "enum(fast|safe)", "required": False,
     "doc": "Copy strategy", "default": "safe"},
    {"id": "source_file", "type": "File", "required": True,
     "doc": "Source file to copy"},                       # from `label`
    {"id": "target_filename", "type": "string", "required": True,
     "doc": "Name for the output file"},
    {"id": "verbose", "type": "boolean?", "required": False,
     "doc": "Print each file as it is copied"},
]
GOOD_TOOL_OUTPUTS = [{"id": "copied_file", "type": "File", "doc": "The copy"}]

GOOD_WORKFLOW_INPUTS = [
    {"id": "contamination_values", "type": "(float|string)[]?", "required": False,
     "doc": "Per-caller contamination estimates"},
    {"id": "min_quality", "type": "int", "required": False,
     "doc": "Minimum base quality", "default": 20},
    {"id": "reads", "type": "File[]", "required": True,
     "doc": "Input reads, one file per lane"},
    {"id": "reference", "type": "File?", "required": False,
     "doc": "Optional reference genome"},
    {"id": "sample_id", "type": "string", "required": True,
     "doc": "Sample ID"},                                  # from `label`
]
GOOD_WORKFLOW_OUTPUTS = [{"id": "line_counts", "type": "File",
                          "doc": "Line counts for all reads"}]


def stored(entries: list[dict], *, output: bool = False) -> list[dict]:
    """What the API stores for parsed entries: model_dump() keeps absent
    optional fields as null."""
    keys = ("id", "doc", "type") if output else ("id", "doc", "type", "default", "required")
    return [{k: e.get(k) for k in keys} for e in entries]
