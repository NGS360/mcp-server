"""register_workflow_from_file_id / update_workflow_from_file_id: the CWL is
already uploaded, so the tools only create, record and deploy."""

import httpx
import pytest

from .conftest import GOOD_TOOL_INPUTS, GOOD_TOOL_OUTPUTS, stored
from .fake_ngs360 import OMICS_ENGINE

pytestmark = pytest.mark.anyio


@pytest.fixture
def uploaded(fake):
    return fake.add_file(b'{"id": "#main"}')


# --- success -------------------------------------------------------------------

async def test_register_records_the_given_schema(tools, fake, uploaded):
    result = await tools.register_workflow_from_file_id(
        uploaded, "wf", inputs=GOOD_TOOL_INPUTS, outputs=GOOD_TOOL_OUTPUTS)
    workflow_id = result["workflow_id"]
    assert result == {
        "workflow_id": workflow_id,
        "version_num": 1,
        "file_id": uploaded,
        "omics_arn": "arn:aws:omics:us-east-1:000000000000:workflow/1",
        "inputs_recorded": 4,
        "outputs_recorded": 1,
    }
    version = fake.latest_version(workflow_id)
    assert version["definition_uri"] == f"ngs360://{uploaded}"
    assert version["inputs"] == stored(GOOD_TOOL_INPUTS)
    assert version["outputs"] == stored(GOOD_TOOL_OUTPUTS, output=True)
    assert version["attributes"] is None
    assert fake.deployments[0]["engine"] == OMICS_ENGINE


async def test_no_schema_given_leaves_it_null(tools, fake, uploaded):
    result = await tools.register_workflow_from_file_id(uploaded, "wf")
    assert result["inputs_recorded"] is None and result["outputs_recorded"] is None
    version = fake.latest_version()
    assert version["inputs"] is None and version["outputs"] is None
    assert len(fake.deployments) == 1


async def test_empty_lists_are_recorded_as_empty(tools, fake, uploaded):
    await tools.register_workflow_from_file_id(uploaded, "wf", inputs=[], outputs=[])
    version = fake.latest_version()
    assert version["inputs"] == [] and version["outputs"] == []


async def test_git_provenance_from_arguments(tools, fake, uploaded):
    await tools.register_workflow_from_file_id(
        uploaded, "wf", git_commit="abc123", git_repo="https://example.com/r.git",
        git_ref="main")
    assert fake.latest_version()["attributes"] == [
        {"key": "git_commit", "value": "abc123"},
        {"key": "git_repo", "value": "https://example.com/r.git"},
        {"key": "git_ref", "value": "main"},
    ]


async def test_git_provenance_partial(tools, fake, uploaded):
    await tools.register_workflow_from_file_id(uploaded, "wf", git_commit="abc123")
    assert fake.latest_version()["attributes"] == [{"key": "git_commit", "value": "abc123"}]


async def test_update_adds_a_version(tools, fake, uploaded):
    workflow_id = fake.add_workflow(versions=1)
    result = await tools.update_workflow_from_file_id(
        uploaded, workflow_id, inputs=GOOD_TOOL_INPUTS, outputs=GOOD_TOOL_OUTPUTS)
    assert result["version_num"] == 2
    assert result["inputs_recorded"] == 4
    assert fake.latest_version(workflow_id)["inputs"] == stored(GOOD_TOOL_INPUTS)
    assert ("POST", "/workflows") not in fake.writes()
    assert len(fake.deployments) == 1


async def test_malformed_schema_is_rejected_by_the_api(tools, fake, uploaded):
    # Reached only when the caller bypasses the typed arguments; through
    # MCP a bad entry is rejected first (see test_mcp_interface).
    with pytest.raises(httpx.HTTPStatusError, match="422 Unprocessable Entity"):
        await tools.register_workflow_from_file_id(
            uploaded, "wf", inputs=[{"id": "x", "type": "File"}])
    (workflow_id,) = fake.workflows
    assert fake.versions[workflow_id] == []


# --- refused before anything is created ------------------------------------------

async def test_update_unknown_workflow_is_checked_first(tools, fake, uploaded):
    with pytest.raises(httpx.HTTPStatusError, match="404 Not Found"):
        await tools.update_workflow_from_file_id(uploaded, "nope")
    assert fake.writes() == []
    assert not any(path.startswith("/files") for _, path in fake.calls())


async def test_expired_token(tools_with_token, fake, uploaded):
    tools = tools_with_token("expired")
    with pytest.raises(httpx.HTTPStatusError, match="401 Unauthorized"):
        await tools.register_workflow_from_file_id(uploaded, "wf")
    assert fake.workflows == {}


# --- failures part-way through leave earlier steps in place -------------------------

async def test_workflow_create_fails(tools, fake, uploaded):
    fake.fail("POST", "/workflows", 500)
    with pytest.raises(httpx.HTTPStatusError, match="500 Internal Server Error"):
        await tools.register_workflow_from_file_id(uploaded, "wf")
    assert fake.workflows == {}


async def test_version_create_fails(tools, fake, uploaded):
    fake.fail("POST", "/workflows/[^/]+/versions", 500)
    with pytest.raises(httpx.HTTPStatusError, match="500 Internal Server Error"):
        await tools.register_workflow_from_file_id(uploaded, "wf")
    (workflow_id,) = fake.workflows
    assert fake.versions[workflow_id] == [], "the workflow row is left behind"


async def test_deploy_fails_but_the_version_survives(tools, fake, uploaded):
    fake.fail("POST", "/workflows/[^/]+/versions/\\d+/deployments", 502)
    with pytest.raises(httpx.HTTPStatusError, match="502 Bad Gateway"):
        await tools.register_workflow_from_file_id(uploaded, "wf")
    (workflow_id,) = fake.workflows
    assert len(fake.versions[workflow_id]) == 1
    assert fake.deployments == []


async def test_update_deploy_fails(tools, fake, uploaded):
    workflow_id = fake.add_workflow(versions=1)
    fake.fail("POST", "/workflows/[^/]+/versions/\\d+/deployments", 502)
    with pytest.raises(httpx.HTTPStatusError, match="502 Bad Gateway"):
        await tools.update_workflow_from_file_id(uploaded, workflow_id)
    assert len(fake.versions[workflow_id]) == 2, "the new version survives"
    assert fake.deployments == []
