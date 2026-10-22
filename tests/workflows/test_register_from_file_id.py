"""register_workflow_from_file_id / update_workflow_from_file_id: the CWL is
already uploaded, so the tools only create, record and deploy."""

import httpx
import pytest

from .conftest import GOOD_TOOL_INPUTS, GOOD_TOOL_OUTPUTS, stored
from .fake_ngs360 import OMICS_ENGINE

pytestmark = pytest.mark.anyio

MISSING_FILE = "11111111-2222-3333-4444-555555555555"


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


async def test_file_is_checked_before_anything_is_created(tools, fake, uploaded):
    await tools.register_workflow_from_file_id(uploaded, "wf")
    assert fake.calls()[:2] == [("GET", f"/files/{uploaded}"), ("POST", "/workflows")]


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
    # The version create fails after the workflow was made, so the error
    # also says how to finish (see test_error_messages).
    with pytest.raises(RuntimeError, match=r"422 .*inputs\.0\.required: Field required"):
        await tools.register_workflow_from_file_id(
            uploaded, "wf", inputs=[{"id": "x", "type": "File"}])
    (workflow_id,) = fake.workflows
    assert fake.versions[workflow_id] == []


# --- refused before anything is created ------------------------------------------

@pytest.mark.parametrize("file_id, reason", [
    (MISSING_FILE, f"File {MISSING_FILE} not found"),
    ("not-a-uuid", "path.file_id: Input should be a valid UUID"),
])
async def test_unknown_file_id_creates_nothing(tools, fake, file_id, reason):
    with pytest.raises(ValueError) as info:
        await tools.register_workflow_from_file_id(file_id, "wf")
    msg = str(info.value)
    assert f"file_id '{file_id}' does not exist on NGS360, so nothing was created" in msg
    assert reason in msg
    assert fake.writes() == []


async def test_update_unknown_file_id_creates_nothing(tools, fake):
    workflow_id = fake.add_workflow()
    with pytest.raises(ValueError, match="does not exist on NGS360"):
        await tools.update_workflow_from_file_id(MISSING_FILE, workflow_id)
    assert fake.writes() == []


async def test_update_unknown_workflow_is_checked_first(tools, fake, uploaded):
    with pytest.raises(httpx.HTTPStatusError, match="404 .*: Workflow not found"):
        await tools.update_workflow_from_file_id(uploaded, "nope")
    assert fake.writes() == []
    assert not any(path.startswith("/files") for _, path in fake.calls())


async def test_file_lookup_failing_otherwise_is_not_reported_as_missing(tools, fake, uploaded):
    fake.fail("GET", f"/files/{uploaded}", 500)
    with pytest.raises(httpx.HTTPStatusError, match="500 .*injected 500"):
        await tools.register_workflow_from_file_id(uploaded, "wf")
    assert fake.writes() == []


async def test_expired_token(tools_with_token, fake, uploaded):
    tools = tools_with_token("expired")
    with pytest.raises(httpx.HTTPStatusError, match="401 .*Could not validate credentials"):
        await tools.register_workflow_from_file_id(uploaded, "wf")
    assert fake.workflows == {}


# --- failures part-way through -------------------------------------------------------

async def test_workflow_create_fails(tools, fake, uploaded):
    # Nothing was created by this call, so the plain API error is reported.
    fake.fail("POST", "/workflows", 500)
    with pytest.raises(httpx.HTTPStatusError, match="500 .*injected 500"):
        await tools.register_workflow_from_file_id(uploaded, "wf")


async def test_version_create_fails(tools, fake, uploaded):
    fake.fail("POST", "/workflows/[^/]+/versions", 500)
    with pytest.raises(RuntimeError) as info:
        await tools.register_workflow_from_file_id(uploaded, "wf")
    (workflow_id,) = fake.workflows
    msg = str(info.value)
    assert msg.startswith("Failed while creating the version: 500")
    assert "uploaded" not in msg, "this call uploaded nothing"
    assert (f"update_workflow_from_file_id(file_id='{uploaded}', "
            f"workflow_id='{workflow_id}')") in msg


async def test_deploy_fails(tools, fake, uploaded):
    fake.fail("POST", "/workflows/[^/]+/versions/\\d+/deployments", 502)
    with pytest.raises(RuntimeError, match="Failed while deploying to Omics: 502") as info:
        await tools.register_workflow_from_file_id(uploaded, "wf")
    (workflow_id,) = fake.workflows
    assert f"create_workflow_deployment(workflow_id='{workflow_id}', version_num=1" \
        in str(info.value)


async def test_update_deploy_fails(tools, fake, uploaded):
    workflow_id = fake.add_workflow(versions=1)
    fake.fail("POST", "/workflows/[^/]+/versions/\\d+/deployments", 502)
    with pytest.raises(RuntimeError) as info:
        await tools.update_workflow_from_file_id(uploaded, workflow_id)
    msg = str(info.value)
    assert f"created version 2 of workflow {workflow_id}" in msg
    assert "created workflow" not in msg
