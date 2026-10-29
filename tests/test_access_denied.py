"""401 and 403 from NGS360 must reach the model as final, readable tool errors.

Before this, every call ran raise_for_status(), so a refusal surfaced as an
httpx.HTTPStatusError traceback and a model would retry it. NGS360 enforces RBAC
per user, so a refusal is the answer for this caller, not a transient fault.
"""

import asyncio

import httpx
import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from ngs360_mcp_server.client import NGS360AccessDenied, NGS360Client


def client_answering(status: int, **response) -> NGS360Client:
    """An NGS360Client whose every request gets this response."""
    client = NGS360Client(base_url="http://ngs360.test", token="t")
    client._client = httpx.AsyncClient(
        base_url="http://ngs360.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(status, **response)),
    )
    return client


def call(client: NGS360Client, method: str):
    args = {"json": {}} if method in ("post", "put", "patch") else {}
    return asyncio.run(getattr(client, method)("/projects/P-1", **args))


@pytest.mark.parametrize("method", ["get", "post", "put", "patch", "delete"])
def test_403_is_access_denied_on_every_verb(method):
    client = client_answering(
        403, json={"detail": "Project P-1 is restricted to its members."})
    with pytest.raises(NGS360AccessDenied) as exc:
        call(client, method)
    assert exc.value.status_code == 403
    message = str(exc.value)
    assert message.startswith("Permission denied: Project P-1 is restricted")
    assert "Not retryable" in message


def test_post_form_is_covered_too():
    client = client_answering(403, json={"detail": "Missing permission: job:submit"})
    with pytest.raises(NGS360AccessDenied):
        asyncio.run(client.post_form("/runs", data={"a": "b"}))


def test_401_says_the_credential_is_the_problem():
    client = client_answering(401, json={"detail": "Could not validate credentials"})
    with pytest.raises(NGS360AccessDenied) as exc:
        call(client, "get")
    assert exc.value.status_code == 401
    assert str(exc.value).startswith("Not authenticated: Could not validate credentials")


def test_a_non_json_body_is_still_reported():
    client = client_answering(403, text="Forbidden by proxy")
    with pytest.raises(NGS360AccessDenied) as exc:
        call(client, "get")
    assert "Forbidden by proxy" in str(exc.value)


def test_other_errors_are_unchanged():
    """Only refusals are final. A 404 or a 500 keeps its existing behaviour."""
    for status in (404, 500):
        with pytest.raises(httpx.HTTPStatusError):
            call(client_answering(status, json={"detail": "x"}), "get")


def test_success_is_unchanged():
    assert call(client_answering(200, json={"ok": True}), "get") == {"ok": True}


def test_the_model_sees_the_message_as_the_tool_error():
    """End to end through FastMCP, which is what an agent actually receives."""
    mcp = FastMCP("test")
    client = client_answering(403, json={"detail": "Missing permission: sample:create"})

    @mcp.tool()
    async def add_sample() -> dict:
        return await client.post("/projects/P-1/samples", json={})

    with pytest.raises(ToolError) as exc:
        asyncio.run(mcp.call_tool("add_sample", {}))
    assert "Permission denied: Missing permission: sample:create" in str(exc.value)
    assert "Do not retry" in str(exc.value)
