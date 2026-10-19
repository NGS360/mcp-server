"""The workflow tools as a model sees them, through a real MCP session."""

import json

import pytest

from .conftest import PACKED

pytestmark = pytest.mark.anyio

ALL_WORKFLOW_TOOLS = {
    "list_workflows", "get_workflow", "create_workflow",
    "create_workflow_version", "list_workflow_versions", "get_workflow_version",
    "set_workflow_alias", "list_workflow_aliases", "delete_workflow_alias",
    "create_workflow_deployment", "list_workflow_deployments",
    "delete_workflow_deployment",
    "register_workflow", "update_workflow",
    "register_workflow_from_file_id", "update_workflow_from_file_id",
}


async def test_every_tool_is_exposed_with_its_docs(mcp_server):
    tools = {t.name: t for t in await mcp_server.list_tools()}
    assert set(tools) == ALL_WORKFLOW_TOOLS
    for tool in tools.values():
        assert tool.description, f"{tool.name} has no description"


async def test_error_wrapping_keeps_tool_signatures(mcp_server):
    tools = {t.name: t for t in await mcp_server.list_tools()}
    schema = tools["register_workflow_from_file_id"].inputSchema
    assert set(schema["required"]) == {"file_id", "name"}
    assert {"git_commit", "git_repo", "git_ref"} <= set(schema["properties"])


async def test_success_result(mcp_call, fake):
    file_id = fake.add_file((PACKED / "good_workflow.json").read_bytes())
    result = await mcp_call("register_workflow_from_file_id",
                            {"file_id": file_id, "name": "wf"})
    assert not result.isError
    payload = json.loads(result.content[0].text)
    assert payload["inputs_recorded"] == 5 and payload["version_num"] == 1


async def test_api_error_reaches_the_model_with_its_reason(mcp_call, fake):
    result = await mcp_call("get_workflow", {"workflow_id": "nope"})
    assert result.isError
    assert result.content[0].text == (
        "Error executing tool get_workflow: 404 Not Found from "
        "GET api.test/api/v1/workflows/nope: Workflow not found")


async def test_missing_required_argument(mcp_call, fake):
    result = await mcp_call("register_workflow", {"cwl_path": "/x.cwl"})
    assert result.isError and "name" in result.content[0].text
    assert fake.requests == []


async def test_wrong_argument_type(mcp_call, fake):
    result = await mcp_call("register_workflow_from_file_id", {"file_id": 123, "name": "wf"})
    assert result.isError and "file_id" in result.content[0].text
    assert fake.requests == []
