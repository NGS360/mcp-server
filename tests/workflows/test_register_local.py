"""register_workflow / update_workflow: pack a local CWL, upload, create,
deploy. Most tests need cwltool on PATH and are skipped without it."""

import json
import re
import shutil

import httpx
import pytest

from .conftest import (
    CWL,
    GOOD_TOOL_INPUTS,
    GOOD_TOOL_OUTPUTS,
    requires_cwltool,
    stored,
)
from .fake_ngs360 import OMICS_ENGINE

pytestmark = pytest.mark.anyio

ANSI_ESCAPE = re.compile(r"\x1b\[")


# --- success -------------------------------------------------------------------

@requires_cwltool
async def test_register_new_workflow_end_to_end(tools, fake, git_repo):
    result = await tools.register_workflow(
        str(git_repo / "good_tool.cwl"), "Good tool",
        inputs=GOOD_TOOL_INPUTS, outputs=GOOD_TOOL_OUTPUTS)

    workflow_id = result["workflow_id"]
    assert result == {
        "workflow_id": workflow_id,
        "version_num": 1,
        "file_id": result["file_id"],
        "omics_arn": "arn:aws:omics:us-east-1:000000000000:workflow/1",
        "inputs_recorded": 4,
        "outputs_recorded": 1,
    }
    assert fake.writes() == [
        ("POST", "/files/upload"),
        ("POST", "/workflows"),
        ("POST", f"/workflows/{workflow_id}/versions"),
        ("POST", f"/workflows/{workflow_id}/versions/1/deployments"),
    ]
    assert fake.workflows[workflow_id]["name"] == "Good tool"

    version = fake.latest_version(workflow_id)
    assert version["definition_uri"] == f"ngs360://{result['file_id']}"
    assert version["inputs"] == stored(GOOD_TOOL_INPUTS)
    assert version["outputs"] == stored(GOOD_TOOL_OUTPUTS, output=True)
    assert fake.deployments[0]["engine"] == OMICS_ENGINE


@requires_cwltool
async def test_upload_form_and_packed_content(tools, fake, git_repo):
    result = await tools.register_workflow(str(git_repo / "good_tool.cwl"), "Good tool")
    record = fake.files[result["file_id"]]
    assert re.fullmatch(r"good_tool\.\d{8}T\d{6}Z\.cwl", record["form"]["filename"])
    assert record["form"]["relative_path"] == "workflow_definition_file"
    assert record["form"]["project_id"] == "P-00000000-0001"
    uploaded = json.loads(fake.uploads[result["file_id"]])
    assert uploaded["id"] == "#main", "the packed CWL is what gets uploaded"


@requires_cwltool
async def test_git_provenance_from_a_clean_checkout(tools, fake, git_repo):
    await tools.register_workflow(str(git_repo / "good_tool.cwl"), "t")
    attrs = {a["key"]: a["value"] for a in fake.latest_version()["attributes"]}
    assert re.fullmatch(r"[0-9a-f]{40}", attrs["git_commit"])
    assert attrs["git_repo"] == "https://example.com/org/workflows.git"
    assert attrs["git_ref"] == "main"


@requires_cwltool
async def test_git_provenance_marks_a_dirty_tree(tools, fake, git_repo):
    cwl = git_repo / "good_tool.cwl"
    cwl.write_text(cwl.read_text() + "\n# local edit\n")
    await tools.register_workflow(str(cwl), "t")
    attrs = {a["key"]: a["value"] for a in fake.latest_version()["attributes"]}
    assert attrs["git_commit"].endswith("+dirty")


@requires_cwltool
async def test_no_git_attributes_outside_a_checkout(tools, fake, tmp_path):
    shutil.copy(CWL / "good_tool.cwl", tmp_path / "good_tool.cwl")
    await tools.register_workflow(str(tmp_path / "good_tool.cwl"), "t")
    assert fake.latest_version()["attributes"] is None


@requires_cwltool
async def test_update_adds_a_version(tools, fake, git_repo):
    workflow_id = fake.add_workflow(versions=2)
    result = await tools.update_workflow(
        str(git_repo / "good_tool.cwl"), workflow_id,
        inputs=GOOD_TOOL_INPUTS, outputs=GOOD_TOOL_OUTPUTS)
    assert result["version_num"] == 3
    assert result["inputs_recorded"] == 4
    assert fake.latest_version(workflow_id)["inputs"] == stored(GOOD_TOOL_INPUTS)
    assert ("POST", "/workflows") not in fake.writes(), "must not create a workflow"
    assert len(fake.deployments) == 1


# --- the schema is recorded as given ---------------------------------------------

@requires_cwltool
async def test_no_schema_given_leaves_it_null(tools, fake):
    result = await tools.register_workflow(str(CWL / "good_tool.cwl"), "t")
    assert result["inputs_recorded"] is None and result["outputs_recorded"] is None
    version = fake.latest_version(result["workflow_id"])
    assert version["inputs"] is None and version["outputs"] is None
    assert len(fake.deployments) == 1


@requires_cwltool
async def test_empty_lists_are_recorded_as_empty(tools, fake):
    result = await tools.register_workflow(str(CWL / "good_tool.cwl"), "t",
                                           inputs=[], outputs=[])
    assert (result["inputs_recorded"], result["outputs_recorded"]) == (0, 0)
    version = fake.latest_version(result["workflow_id"])
    assert version["inputs"] == [] and version["outputs"] == []


# --- refused before anything is created ------------------------------------------

async def test_missing_cwl_file(tools, fake):
    with pytest.raises(ValueError, match="CWL file not found"):
        await tools.register_workflow("/does/not/exist.cwl", "t")
    with pytest.raises(ValueError, match="CWL file not found"):
        await tools.update_workflow("/does/not/exist.cwl", "w1")
    assert fake.requests == []


@pytest.mark.parametrize("tool, args, sibling", [
    ("register_workflow", {"name": "t"}, "register_workflow_from_file_id"),
    ("update_workflow", {"workflow_id": "w1"}, "update_workflow_from_file_id"),
])
async def test_refused_under_remote_transport(tools, fake, monkeypatch, tool, args, sibling):
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    with pytest.raises(RuntimeError, match=f"Use {sibling} instead"):
        await getattr(tools, tool)(cwl_path=str(CWL / "good_tool.cwl"), **args)
    assert fake.requests == []


@requires_cwltool
@pytest.mark.parametrize("fixture", [
    "fail_pack_yaml_indent.cwl",
    "fail_pack_unknown_type.cwl",
    "fail_pack_missing_run.cwl",
    "fail_pack_duplicate_ids.cwl",
])
async def test_cwl_that_will_not_pack(tools, fake, fixture):
    with pytest.raises(RuntimeError, match="cwltool --pack .* failed") as info:
        await tools.register_workflow(str(CWL / fixture), "t")
    assert not ANSI_ESCAPE.search(str(info.value)), "colour codes leaked into the error"
    assert fake.requests == []


async def test_cwltool_not_installed(tools, fake, monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(RuntimeError, match="cwltool is not on PATH"):
        await tools.register_workflow(str(CWL / "good_tool.cwl"), "t")
    assert fake.requests == []


@requires_cwltool
async def test_update_unknown_workflow_uploads_nothing(tools, fake):
    with pytest.raises(httpx.HTTPStatusError, match="404 .*: Workflow not found"):
        await tools.update_workflow(str(CWL / "good_tool.cwl"), "nope")
    assert fake.writes() == [] and fake.files == {}


@requires_cwltool
async def test_expired_token(tools_with_token, fake):
    tools = tools_with_token("expired")
    with pytest.raises(httpx.HTTPStatusError, match="401 .*Could not validate credentials"):
        await tools.register_workflow(str(CWL / "good_tool.cwl"), "t")
    assert fake.files == {} and fake.workflows == {}


@requires_cwltool
async def test_upload_fails(tools, fake):
    fake.fail("POST", "/files/upload", 500)
    with pytest.raises(httpx.HTTPStatusError, match="500 .*injected 500"):
        await tools.register_workflow(str(CWL / "good_tool.cwl"), "t")
    assert fake.workflows == {}


@requires_cwltool
async def test_upload_response_without_id(tools, fake):
    fake.fail("POST", "/files/upload", 201, {"ok": True})
    with pytest.raises(RuntimeError, match="missing 'id'"):
        await tools.register_workflow(str(CWL / "good_tool.cwl"), "t")
    assert fake.workflows == {}


# --- failures part-way through: say what exists and how to finish ---------------------

@requires_cwltool
async def test_workflow_create_fails_after_upload(tools, fake):
    fake.fail("POST", "/workflows", 500)
    with pytest.raises(RuntimeError) as info:
        await tools.register_workflow(str(CWL / "good_tool.cwl"), "t")
    (file_id,) = fake.files
    msg = str(info.value)
    assert msg.startswith("Failed while creating the workflow: 500")
    assert f"uploaded the packed CWL as file {file_id}" in msg
    assert f"register_workflow_from_file_id(file_id='{file_id}', name=...)" in msg


@requires_cwltool
async def test_version_create_fails_after_workflow(tools, fake):
    fake.fail("POST", "/workflows/[^/]+/versions", 500)
    with pytest.raises(RuntimeError) as info:
        await tools.register_workflow(str(CWL / "good_tool.cwl"), "t")
    (file_id,), (workflow_id,) = fake.files, fake.workflows
    msg = str(info.value)
    assert msg.startswith("Failed while creating the version")
    assert f"created workflow {workflow_id}" in msg
    assert (f"update_workflow_from_file_id(file_id='{file_id}', "
            f"workflow_id='{workflow_id}')") in msg


@requires_cwltool
async def test_deploy_fails_and_the_suggested_recovery_works(tools, fake):
    fake.fail("POST", "/workflows/[^/]+/versions/\\d+/deployments", 502)
    with pytest.raises(RuntimeError) as info:
        await tools.register_workflow(str(CWL / "good_tool.cwl"), "t")
    (workflow_id,) = fake.workflows
    msg = str(info.value)
    assert msg.startswith("Failed while deploying to Omics: 502")
    assert f"created version 1 of workflow {workflow_id}" in msg
    assert f"create_workflow_deployment(workflow_id='{workflow_id}', version_num=1" in msg

    fake._faults.clear()                        # the cause is fixed
    await tools.create_workflow_deployment(workflow_id, 1, OMICS_ENGINE)
    assert len(fake.deployments) == 1
    assert len(fake.versions[workflow_id]) == 1, "recovery must not duplicate the version"


@requires_cwltool
async def test_update_version_fails_after_upload(tools, fake):
    workflow_id = fake.add_workflow()
    fake.fail("POST", "/workflows/[^/]+/versions", 500)
    with pytest.raises(RuntimeError) as info:
        await tools.update_workflow(str(CWL / "good_tool.cwl"), workflow_id)
    (file_id,) = fake.files
    msg = str(info.value)
    assert "uploaded the packed CWL" in msg
    assert "created workflow" not in msg, "the workflow already existed"
    assert (f"update_workflow_from_file_id(file_id='{file_id}', "
            f"workflow_id='{workflow_id}')") in msg
