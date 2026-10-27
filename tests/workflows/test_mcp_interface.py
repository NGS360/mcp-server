"""The workflow tools as a model sees them, through a real MCP session."""

import json

import pytest

from .conftest import GOOD_TOOL_INPUTS, GOOD_TOOL_OUTPUTS, stored

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

TOOLS_TAKING_A_SCHEMA = {
    "create_workflow_version",
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


@pytest.mark.parametrize("tool", sorted(TOOLS_TAKING_A_SCHEMA))
async def test_schema_tools_carry_the_guide_and_typed_arguments(mcp_server, tool):
    described = {t.name: t for t in await mcp_server.list_tools()}[tool]
    assert "Recording the workflow's inputs and outputs" in described.description
    assert "required" in described.description and "label" in described.description

    defs = described.inputSchema["$defs"]
    assert set(defs["WorkflowInput"]["required"]) == {"id", "type", "required"}
    assert set(defs["WorkflowInput"]["properties"]) == {"id", "type", "required",
                                                       "doc", "default"}
    assert set(defs["WorkflowOutput"]["required"]) == {"id", "type"}
    assert "inputs" not in described.inputSchema.get("required", [])


async def test_guide_is_indented_like_the_rest_of_the_docstring(mcp_server):
    described = {t.name: t for t in await mcp_server.list_tools()}["register_workflow"]
    line = next(l for l in described.description.splitlines()
                if "Recording the workflow's inputs and outputs" in l)
    assert line.startswith(" " * 8) and not line.startswith(" " * 9)


async def test_schema_sent_through_mcp_is_recorded_as_given(mcp_call, fake):
    file_id = fake.add_file(b"{}")
    result = await mcp_call("register_workflow_from_file_id", {
        "file_id": file_id, "name": "wf",
        "inputs": GOOD_TOOL_INPUTS, "outputs": GOOD_TOOL_OUTPUTS,
    })
    assert not result.isError, result.content[0].text
    payload = json.loads(result.content[0].text)
    assert (payload["inputs_recorded"], payload["outputs_recorded"]) == (4, 1)
    version = fake.latest_version()
    assert version["inputs"] == stored(GOOD_TOOL_INPUTS)
    assert version["outputs"] == stored(GOOD_TOOL_OUTPUTS, output=True)


@pytest.mark.parametrize("bad_entry, field", [
    ({"id": "x", "type": "File"}, "required"),                    # missing
    ({"id": "x", "type": "File", "required": "maybe"}, "required"),  # wrong type
    ({"type": "File", "required": True}, "id"),
])
async def test_malformed_schema_entry_is_rejected_before_any_request(
        mcp_call, fake, bad_entry, field):
    file_id = fake.add_file(b"{}")
    result = await mcp_call("register_workflow_from_file_id",
                            {"file_id": file_id, "name": "wf", "inputs": [bad_entry]})
    assert result.isError
    assert "inputs" in result.content[0].text and field in result.content[0].text
    assert fake.requests == []


async def test_api_error_reaches_the_model(mcp_call, fake):
    result = await mcp_call("get_workflow", {"workflow_id": "nope"})
    assert result.isError
    assert "404 Not Found" in result.content[0].text


async def test_missing_required_argument(mcp_call, fake):
    result = await mcp_call("register_workflow", {"cwl_path": "/x.cwl"})
    assert result.isError and "name" in result.content[0].text
    assert fake.requests == []


async def test_wrong_argument_type(mcp_call, fake):
    result = await mcp_call("register_workflow_from_file_id", {"file_id": 123, "name": "wf"})
    assert result.isError and "file_id" in result.content[0].text
    assert fake.requests == []


# --- pointing the model at the recorded schema when launching -----------------

async def test_get_workflow_version_advertises_the_schema(mcp_server):
    """A model only looks up the schema if told the response carries it."""
    described = {t.name: t for t in await mcp_server.list_tools()}["get_workflow_version"]
    assert "inputs" in described.description
    assert "wes_run_workflow" in described.description


async def test_wes_run_workflow_guides_assembling_params():
    """The launch tool has to point at get_workflow_version itself: it is
    where a model starts when asked to run a workflow."""
    from mcp.server.fastmcp import FastMCP

    from ngs360_mcp_server.client import NGS360Client
    from ngs360_mcp_server.tools.wes import register_wes_tools

    server = FastMCP("ngs360-test")
    register_wes_tools(server, NGS360Client(base_url="https://api.test",
                                            path_prefix="/ga4gh/wes/v1"))
    described = {t.name: t for t in await server.list_tools()}["wes_run_workflow"]
    text = described.description

    # The workflow_params entry cross-references this heading by name.
    assert "Helping the user assemble workflow_params" in text
    assert "get_workflow_version" in text, "does not say where the schema lives"
    assert "list_workflow_aliases" in text, "no way to resolve an alias to a version"
    # Guidance, not a gate: a mismatch is reported, the run still goes ahead.
    assert "submit anyway" in text
    # And a version with no recorded schema must not be treated as an error.
    assert "null" in text and "not recorded" in text
