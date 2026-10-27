"""register_workflow / update_workflow: pack a local CWL, upload, create,
deploy.

cwltool is faked (see conftest), because the server never reads the CWL —
it passes the path to ``cwltool --pack`` and uploads what that prints. The
one test that runs the real thing is marked ``requires_cwltool``.
"""

import json
import re

import httpx
import pytest

from .conftest import (
    GOOD_TOOL_INPUTS,
    GOOD_TOOL_OUTPUTS,
    PACKED_STDOUT,
    requires_cwltool,
    stored,
)
from .fake_ngs360 import OMICS_ENGINE

pytestmark = pytest.mark.anyio


# --- success -------------------------------------------------------------------

async def test_register_new_workflow_end_to_end(tools, fake, fake_cwltool, git_repo, cwl_file):
    result = await tools.register_workflow(
        str(git_repo / cwl_file.name), "Good tool",
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


async def test_cwltool_is_invoked_on_the_given_path(tools, fake, fake_cwltool, cwl_file):
    await tools.register_workflow(str(cwl_file), "t")
    assert fake_cwltool.args == ["--quiet", "--disable-color", "--pack", str(cwl_file)]


async def test_cwltool_stdout_is_what_gets_uploaded(tools, fake, fake_cwltool, cwl_file):
    # Not the source file: the packed output is what NGS360 stores.
    result = await tools.register_workflow(str(cwl_file), "t")
    assert fake.uploads[result["file_id"]] == PACKED_STDOUT
    assert cwl_file.read_bytes() != PACKED_STDOUT


async def test_upload_form_fields(tools, fake, fake_cwltool, cwl_file):
    result = await tools.register_workflow(str(cwl_file), "t")
    form = fake.files[result["file_id"]]["form"]
    assert re.fullmatch(r"example_tool\.\d{8}T\d{6}Z\.cwl", form["filename"])
    assert form["relative_path"] == "workflow_definition_file"
    assert form["project_id"] == "P-00000000-0001"


async def test_git_provenance_from_a_clean_checkout(
        tools, fake, fake_cwltool, git_repo, cwl_file):
    await tools.register_workflow(str(git_repo / cwl_file.name), "t")
    attrs = {a["key"]: a["value"] for a in fake.latest_version()["attributes"]}
    assert re.fullmatch(r"[0-9a-f]{40}", attrs["git_commit"])
    assert attrs["git_repo"] == "https://example.com/org/workflows.git"
    assert attrs["git_ref"] == "main"


async def test_git_provenance_marks_a_dirty_tree(
        tools, fake, fake_cwltool, git_repo, cwl_file):
    tracked = git_repo / cwl_file.name
    tracked.write_text(tracked.read_text() + "\n# local edit\n")
    await tools.register_workflow(str(tracked), "t")
    attrs = {a["key"]: a["value"] for a in fake.latest_version()["attributes"]}
    assert attrs["git_commit"].endswith("+dirty")


async def test_no_git_attributes_outside_a_checkout(tools, fake, fake_cwltool, cwl_file):
    await tools.register_workflow(str(cwl_file), "t")
    assert fake.latest_version()["attributes"] is None


async def test_update_adds_a_version(tools, fake, fake_cwltool, git_repo, cwl_file):
    workflow_id = fake.add_workflow(versions=2)
    result = await tools.update_workflow(
        str(git_repo / cwl_file.name), workflow_id,
        inputs=GOOD_TOOL_INPUTS, outputs=GOOD_TOOL_OUTPUTS)
    assert result["version_num"] == 3
    assert result["inputs_recorded"] == 4
    assert fake.latest_version(workflow_id)["inputs"] == stored(GOOD_TOOL_INPUTS)
    assert ("POST", "/workflows") not in fake.writes(), "must not create a workflow"
    assert len(fake.deployments) == 1


# --- the schema is recorded as given ---------------------------------------------

async def test_no_schema_given_leaves_it_null(tools, fake, fake_cwltool, cwl_file):
    result = await tools.register_workflow(str(cwl_file), "t")
    assert result["inputs_recorded"] is None and result["outputs_recorded"] is None
    version = fake.latest_version(result["workflow_id"])
    assert version["inputs"] is None and version["outputs"] is None
    assert len(fake.deployments) == 1


async def test_empty_lists_are_recorded_as_empty(tools, fake, fake_cwltool, cwl_file):
    result = await tools.register_workflow(str(cwl_file), "t", inputs=[], outputs=[])
    assert (result["inputs_recorded"], result["outputs_recorded"]) == (0, 0)
    version = fake.latest_version(result["workflow_id"])
    assert version["inputs"] == [] and version["outputs"] == []


# --- refused before anything is created ------------------------------------------

async def test_missing_cwl_file(tools, fake, fake_cwltool):
    with pytest.raises(ValueError, match="CWL file not found"):
        await tools.register_workflow("/does/not/exist.cwl", "t")
    with pytest.raises(ValueError, match="CWL file not found"):
        await tools.update_workflow("/does/not/exist.cwl", "w1")
    assert fake.requests == []


@pytest.mark.parametrize("tool, args, sibling", [
    ("register_workflow", {"name": "t"}, "register_workflow_from_file_id"),
    ("update_workflow", {"workflow_id": "w1"}, "update_workflow_from_file_id"),
])
async def test_refused_under_remote_transport(
        tools, fake, monkeypatch, cwl_file, tool, args, sibling):
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    with pytest.raises(RuntimeError, match=f"Use {sibling} instead"):
        await getattr(tools, tool)(cwl_path=str(cwl_file), **args)
    assert fake.requests == []


async def test_cwl_that_will_not_pack(tools, fake, fake_cwltool, cwl_file):
    fake_cwltool.fail()
    with pytest.raises(RuntimeError, match="cwltool --pack .* failed") as info:
        await tools.register_workflow(str(cwl_file), "t")
    assert fake_cwltool.stderr in str(info.value), "cwltool's reason must be relayed"
    assert fake.requests == []


async def test_cwltool_not_installed(tools, fake, monkeypatch, tmp_path, cwl_file):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(RuntimeError, match="cwltool is not on PATH"):
        await tools.register_workflow(str(cwl_file), "t")
    assert fake.requests == []


async def test_update_unknown_workflow_uploads_nothing(tools, fake, fake_cwltool, cwl_file):
    with pytest.raises(httpx.HTTPStatusError, match="404 Not Found"):
        await tools.update_workflow(str(cwl_file), "nope")
    assert fake.writes() == [] and fake.files == {}


async def test_expired_token(tools_with_token, fake, fake_cwltool, cwl_file):
    tools = tools_with_token("expired")
    with pytest.raises(httpx.HTTPStatusError, match="401 Unauthorized"):
        await tools.register_workflow(str(cwl_file), "t")
    assert fake.files == {} and fake.workflows == {}


async def test_upload_fails(tools, fake, fake_cwltool, cwl_file):
    fake.fail("POST", "/files/upload", 500)
    with pytest.raises(httpx.HTTPStatusError, match="500 Internal Server Error"):
        await tools.register_workflow(str(cwl_file), "t")
    assert fake.workflows == {}


async def test_upload_response_without_id(tools, fake, fake_cwltool, cwl_file):
    fake.fail("POST", "/files/upload", 201, {"ok": True})
    with pytest.raises(RuntimeError, match="missing 'id'"):
        await tools.register_workflow(str(cwl_file), "t")
    assert fake.workflows == {}


# --- failures part-way through leave earlier steps in place -------------------------
#
# The chain is not transactional: nothing rolls back what already
# succeeded. These pin that down, so a change to it is visible.

async def test_workflow_create_fails_after_upload(tools, fake, fake_cwltool, cwl_file):
    fake.fail("POST", "/workflows", 500)
    with pytest.raises(httpx.HTTPStatusError, match="500 Internal Server Error"):
        await tools.register_workflow(str(cwl_file), "t")
    assert len(fake.files) == 1, "the uploaded file is not cleaned up"
    assert fake.workflows == {}


async def test_version_create_fails_after_workflow(tools, fake, fake_cwltool, cwl_file):
    fake.fail("POST", "/workflows/[^/]+/versions", 500)
    with pytest.raises(httpx.HTTPStatusError, match="500 Internal Server Error"):
        await tools.register_workflow(str(cwl_file), "t")
    (workflow_id,) = fake.workflows
    assert len(fake.files) == 1
    assert fake.versions[workflow_id] == [], "no version was created"


async def test_deploy_fails_but_the_version_can_still_be_deployed(
        tools, fake, fake_cwltool, cwl_file):
    fake.fail("POST", "/workflows/[^/]+/versions/\\d+/deployments", 502)
    with pytest.raises(httpx.HTTPStatusError, match="502 Bad Gateway"):
        await tools.register_workflow(str(cwl_file), "t")
    (workflow_id,) = fake.workflows
    assert len(fake.versions[workflow_id]) == 1, "the version survives"
    assert fake.deployments == []

    fake._faults.clear()                        # the cause is fixed
    await tools.create_workflow_deployment(workflow_id, 1, OMICS_ENGINE)
    assert len(fake.deployments) == 1
    assert len(fake.versions[workflow_id]) == 1, "deploying must not add a version"


async def test_update_version_create_fails_after_upload(
        tools, fake, fake_cwltool, cwl_file):
    workflow_id = fake.add_workflow()
    before = len(fake.versions[workflow_id])
    fake.fail("POST", "/workflows/[^/]+/versions", 500)
    with pytest.raises(httpx.HTTPStatusError, match="500 Internal Server Error"):
        await tools.update_workflow(str(cwl_file), workflow_id)
    assert len(fake.files) == 1, "the uploaded file is not cleaned up"
    assert len(fake.versions[workflow_id]) == before


# --- the real cwltool ----------------------------------------------------------------

@requires_cwltool
def test_real_cwltool_accepts_the_flags_we_pass(tmp_path):
    """Smoke test for the one thing the fake cannot check.

    Every other test here fakes cwltool, so a flag it no longer accepts, or
    output that stopped being JSON, would go unnoticed. This packs a minimal
    CWL with the real tool and the real arguments.
    """
    from ngs360_mcp_server.tools.workflows import _pack_cwl

    source = tmp_path / "minimal.cwl"
    source.write_text(
        "cwlVersion: v1.2\n"
        "class: CommandLineTool\n"
        "baseCommand: [echo]\n"
        "inputs:\n"
        "  message:\n"
        "    type: string\n"
        "    inputBinding: {position: 1}\n"
        "outputs: []\n"
    )
    packed = json.loads(_pack_cwl(str(source)))
    assert packed["id"] == "#main"
    assert [p["id"] for p in packed["inputs"]] == ["#main/message"]


@requires_cwltool
def test_real_cwltool_failure_is_relayed_without_colour_codes(tmp_path):
    source = tmp_path / "broken.cwl"
    source.write_text(
        "cwlVersion: v1.2\n"
        "class: CommandLineTool\n"
        "baseCommand: [echo]\n"
        "inputs:\n"
        "  message:\n"
        "    type: string\n"
        "   label: wrong indentation\n"
        "outputs: []\n"
    )
    from ngs360_mcp_server.tools.workflows import _pack_cwl

    with pytest.raises(RuntimeError, match="cwltool --pack .* failed") as info:
        _pack_cwl(str(source))
    # --disable-color is why this holds; without it cwltool emits ANSI codes.
    assert "\x1b[" not in str(info.value)
    assert "message" in str(info.value) or "validation" in str(info.value).lower()


async def test_path_with_shell_metacharacters_is_one_argument(
        tools, fake, fake_cwltool, tmp_path):
    """_pack_cwl runs cwltool without a shell, so a path is never split."""
    odd = tmp_path / "a b; echo pwned .cwl"
    odd.write_text("x\n")
    await tools.register_workflow(str(odd), "t")
    assert fake_cwltool.args[-1:] != [";"], "the path was shell-interpreted"
    assert str(odd) in " ".join(fake_cwltool.args)
