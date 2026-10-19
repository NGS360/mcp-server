"""register_workflow_from_file_id / update_workflow_from_file_id: the CWL is
already uploaded, so the server downloads it to read the schema."""

import httpx
import pytest

from .conftest import (
    CWL,
    GOOD_WORKFLOW_INPUTS,
    GOOD_WORKFLOW_OUTPUTS,
    PACKED,
    stored,
)
from .fake_ngs360 import OMICS_ENGINE

pytestmark = pytest.mark.anyio

MISSING_FILE = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def packed_file(fake):
    return fake.add_file((PACKED / "good_workflow.json").read_bytes())


# --- success -------------------------------------------------------------------

async def test_register_reads_schema_from_the_uploaded_file(tools, fake, packed_file):
    result = await tools.register_workflow_from_file_id(packed_file, "wf")
    workflow_id = result["workflow_id"]
    assert result == {
        "workflow_id": workflow_id,
        "version_num": 1,
        "file_id": packed_file,
        "omics_arn": "arn:aws:omics:us-east-1:000000000000:workflow/1",
        "inputs_recorded": 5,
        "outputs_recorded": 1,
    }
    version = fake.latest_version(workflow_id)
    assert version["definition_uri"] == f"ngs360://{packed_file}"
    assert version["inputs"] == stored(GOOD_WORKFLOW_INPUTS)
    assert version["outputs"] == stored(GOOD_WORKFLOW_OUTPUTS, output=True)
    assert version["attributes"] is None
    assert fake.deployments[0]["engine"] == OMICS_ENGINE


async def test_download_path_and_no_token_sent_to_s3(tools, fake, packed_file):
    await tools.register_workflow_from_file_id(packed_file, "wf")
    reads = [c for c in fake.calls() if c[0] in ("GET", "S3")]
    assert reads == [
        ("GET", f"/files/{packed_file}"),
        ("GET", "/files/download-url"),
        ("S3", "/workflow_definition_file/seeded.packed.cwl"),
    ]
    assert not fake.s3_saw_authorization


async def test_schema_is_read_before_anything_is_created(tools, fake, packed_file):
    await tools.register_workflow_from_file_id(packed_file, "wf")
    calls = fake.calls()
    assert calls.index(("S3", "/workflow_definition_file/seeded.packed.cwl")) < \
        calls.index(("POST", "/workflows"))


async def test_git_provenance_from_arguments(tools, fake, packed_file):
    await tools.register_workflow_from_file_id(
        packed_file, "wf", git_commit="abc123", git_repo="https://example.com/r.git",
        git_ref="main")
    assert fake.latest_version()["attributes"] == [
        {"key": "git_commit", "value": "abc123"},
        {"key": "git_repo", "value": "https://example.com/r.git"},
        {"key": "git_ref", "value": "main"},
    ]


async def test_git_provenance_partial(tools, fake, packed_file):
    await tools.register_workflow_from_file_id(packed_file, "wf", git_commit="abc123")
    assert fake.latest_version()["attributes"] == [{"key": "git_commit", "value": "abc123"}]


async def test_update_adds_a_version(tools, fake, packed_file):
    workflow_id = fake.add_workflow(versions=1)
    result = await tools.update_workflow_from_file_id(packed_file, workflow_id)
    assert result["version_num"] == 2
    assert result["inputs_recorded"] == 5
    assert ("POST", "/workflows") not in fake.writes()
    assert len(fake.deployments) == 1


# --- schema problems never block registration --------------------------------------

@pytest.mark.parametrize("content, reason", [
    ((CWL / "fail_remote_unpacked.cwl").read_bytes(), "cwltool --pack"),
    ((CWL / "fail_remote_not_cwl.json").read_bytes(), "#main"),
    ((CWL / "fail_remote_two_entry_processes.json").read_bytes(), "#main"),
    ((PACKED / "fail_schema_inf_default.json").read_bytes(), "Out of range float"),
])
async def test_unreadable_upload_still_registers(tools, fake, content, reason):
    file_id = fake.add_file(content)
    result = await tools.register_workflow_from_file_id(file_id, "wf")
    assert result["inputs_recorded"] is None
    assert reason in result["io_warning"]
    assert fake.latest_version()["inputs"] is None
    assert len(fake.deployments) == 1


async def test_no_parameters_recorded_as_empty_lists(tools, fake):
    file_id = fake.add_file((PACKED / "pass_no_parameters.json").read_bytes())
    result = await tools.register_workflow_from_file_id(file_id, "wf")
    assert "io_warning" not in result
    assert fake.latest_version()["inputs"] == []


@pytest.mark.parametrize("fault, reason", [
    (("GET", "/files/download-url", 403), "injected 403"),
    (("GET", "/files/download-url", 200, {"expires_in": 60}), "unexpected /files/download-url"),
    (("S3", ".", 403, None), "AccessDenied"),
    (("S3", ".", 200, None), "not JSON"),
])
async def test_download_problems_warn_but_register(tools, fake, packed_file, fault, reason):
    method, path, status, *body = fault
    if method == "S3":
        text = "<Error>AccessDenied</Error>" if status == 403 else "<html>login</html>"
        fake.fail(method, path, status, text=text)
    else:
        fake.fail(method, path, status, *body)
    result = await tools.register_workflow_from_file_id(packed_file, "wf")
    assert reason in result["io_warning"]
    assert "X-Amz-Signature" not in result["io_warning"]
    assert fake.latest_version()["inputs"] is None
    assert len(fake.deployments) == 1


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


async def test_update_unknown_workflow_does_not_download(tools, fake, packed_file):
    with pytest.raises(httpx.HTTPStatusError, match="404 .*: Workflow not found"):
        await tools.update_workflow_from_file_id(packed_file, "nope")
    assert fake.writes() == []
    assert not any("/files" in path for _, path in fake.calls())


async def test_expired_token(tools_with_token, fake, packed_file):
    tools = tools_with_token("expired")
    with pytest.raises(httpx.HTTPStatusError, match="401 .*Could not validate credentials"):
        await tools.register_workflow_from_file_id(packed_file, "wf")
    assert fake.workflows == {}


# --- failures part-way through -------------------------------------------------------

async def test_workflow_create_fails(tools, fake, packed_file):
    # Nothing was created by this call, so the plain API error is reported.
    fake.fail("POST", "/workflows", 500)
    with pytest.raises(httpx.HTTPStatusError, match="500 .*injected 500"):
        await tools.register_workflow_from_file_id(packed_file, "wf")


async def test_version_create_fails(tools, fake, packed_file):
    fake.fail("POST", "/workflows/[^/]+/versions", 500)
    with pytest.raises(RuntimeError) as info:
        await tools.register_workflow_from_file_id(packed_file, "wf")
    (workflow_id,) = fake.workflows
    msg = str(info.value)
    assert msg.startswith("Failed while creating the version: 500")
    assert "uploaded" not in msg, "this call uploaded nothing"
    assert (f"update_workflow_from_file_id(file_id='{packed_file}', "
            f"workflow_id='{workflow_id}')") in msg


async def test_deploy_fails(tools, fake, packed_file):
    fake.fail("POST", "/workflows/[^/]+/versions/\\d+/deployments", 502)
    with pytest.raises(RuntimeError, match="Failed while deploying to Omics: 502") as info:
        await tools.register_workflow_from_file_id(packed_file, "wf")
    (workflow_id,) = fake.workflows
    assert f"create_workflow_deployment(workflow_id='{workflow_id}', version_num=1" \
        in str(info.value)


async def test_update_deploy_fails(tools, fake, packed_file):
    workflow_id = fake.add_workflow(versions=1)
    fake.fail("POST", "/workflows/[^/]+/versions/\\d+/deployments", 502)
    with pytest.raises(RuntimeError) as info:
        await tools.update_workflow_from_file_id(packed_file, workflow_id)
    msg = str(info.value)
    assert f"created version 2 of workflow {workflow_id}" in msg
    assert "created workflow" not in msg
