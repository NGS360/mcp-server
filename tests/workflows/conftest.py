"""Fixtures for the workflow-tool tests.

``fake``      the in-memory NGS360 API every request is routed to
``tools``     the workflow tools as plain async functions, for asserting
              on results and on the exceptions they raise
``mcp_call``  invoke a tool through a real in-memory MCP client session,
              for asserting on exactly what a model receives
``cwl_file``  a file for the local tools to pack
``fake_cwltool``  a stand-in for cwltool on PATH

The server does not read CWL — it hands the path to ``cwltool --pack`` and
uploads whatever that prints — so these tests don't need valid CWL. They
fake cwltool instead, which keeps them fast and runnable without it. The
one test that needs the real thing is marked ``requires_cwltool``.
"""

import os
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from ngs360_mcp_server.client import NGS360Client
from ngs360_mcp_server.tools.workflows import register_workflows_tools

from .fake_ngs360 import API_URL, TOKEN, FakeNGS360

requires_cwltool = pytest.mark.skipif(
    shutil.which("cwltool") is None,
    reason="cwltool is not on PATH (pip install cwltool)",
)

# What the fake cwltool prints: the shape of a packed lone tool, so a
# test can tell the uploaded bytes came from cwltool's stdout and not
# from the source file.
PACKED_STDOUT = (
    b'{"class": "CommandLineTool", "cwlVersion": "v1.2", "id": "#main",\n'
    b' "inputs": [], "outputs": []}\n'
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _stdio_transport(monkeypatch):
    # The local-file tools refuse to run under streamable-http.
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)


class FakeCwltool:
    """A stand-in for cwltool on PATH.

    Prints PACKED_STDOUT and exits 0, until ``fail()`` is called. Records
    the arguments it was given, so a test can check the server invokes it
    correctly — the one thing about packing that is the server's own
    behaviour rather than cwltool's.
    """

    def __init__(self, bin_dir: Path):
        self._script = bin_dir / "cwltool"
        self._argv = bin_dir / "argv"
        self._stderr = "ERROR Tool definition failed validation: not valid CWL"
        self._write(exit_code=0)

    def _write(self, exit_code: int) -> None:
        self._script.write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s" "$*" > {self._argv}\n'
            + (f'echo "{self._stderr}" >&2\nexit {exit_code}\n'
               if exit_code else
               f"cat <<'PACKED'\n{PACKED_STDOUT.decode().rstrip()}\nPACKED\n")
        )
        self._script.chmod(0o755)

    def fail(self, exit_code: int = 1) -> None:
        """Make the next pack fail, as a malformed CWL would."""
        self._write(exit_code)

    @property
    def stderr(self) -> str:
        return self._stderr

    @property
    def args(self) -> list[str]:
        """The arguments cwltool was last called with."""
        return self._argv.read_text().split()


@pytest.fixture
def fake_cwltool(tmp_path, monkeypatch) -> FakeCwltool:
    """Put a fake cwltool first on PATH.

    Prepended rather than replacing PATH so git — which the provenance
    capture shells out to — still resolves.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    return FakeCwltool(bin_dir)


@pytest.fixture
def cwl_file(tmp_path) -> Path:
    """A file for the local tools to pack.

    Its contents are never read: the server passes the path to cwltool
    and uploads what cwltool prints.
    """
    path = tmp_path / "example_tool.cwl"
    path.write_text("# stands in for a CWL file; never parsed by the server\n")
    return path


@pytest.fixture
def fake(monkeypatch) -> FakeNGS360:
    """Route every httpx.AsyncClient to one FakeNGS360."""
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
def git_repo(tmp_path, cwl_file) -> Path:
    """A throwaway git checkout holding the CWL file, committed clean."""
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copy(cwl_file, repo / cwl_file.name)

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


# A schema of the kind a model would pass after reading a workflow's CWL,
# following the tools' schema guide. The server records it as given, so
# the values only have to be representative: a label-derived doc, an
# optional input, an enum with a default.
GOOD_TOOL_INPUTS = [
    {"id": "source_file", "type": "File", "required": True,
     "doc": "Source file to copy"},
    {"id": "target_filename", "type": "string", "required": True,
     "doc": "Name for the output file"},
    {"id": "verbose", "type": "boolean?", "required": False,
     "doc": "Print each file as it is copied"},
    {"id": "mode", "type": "enum(fast|safe)", "required": False,
     "doc": "Copy strategy", "default": "safe"},
]
GOOD_TOOL_OUTPUTS = [{"id": "copied_file", "type": "File", "doc": "The copy"}]


def stored(entries: list[dict], *, output: bool = False) -> list[dict]:
    """What the API stores for the given entries: model_dump() keeps
    absent optional fields as null."""
    keys = ("id", "doc", "type") if output else ("id", "doc", "type", "default", "required")
    return [{k: e.get(k) for k in keys} for e in entries]
