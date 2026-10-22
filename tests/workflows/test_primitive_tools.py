"""The single-call workflow tools: list/get/create, versions, aliases,
deployments."""

import json

import httpx
import pytest

from .conftest import GOOD_TOOL_INPUTS, GOOD_TOOL_OUTPUTS, stored
from .fake_ngs360 import OMICS_ENGINE

pytestmark = pytest.mark.anyio


# --- workflows ---------------------------------------------------------------

async def test_list_workflows_sends_paging_params(tools, fake):
    fake.add_workflow("a")
    result = await tools.list_workflows(page=2, per_page=5, sort_by="created_on",
                                        sort_order="desc")
    assert [w["name"] for w in result] == ["a"]
    params = fake.requests[-1].url.params
    assert dict(params) == {"page": "2", "per_page": "5", "sort_by": "created_on",
                            "sort_order": "desc"}


async def test_get_workflow(tools, fake):
    workflow_id = fake.add_workflow("wgs")
    assert (await tools.get_workflow(workflow_id))["name"] == "wgs"


async def test_get_workflow_unknown_id_reports_the_api_reason(tools, fake):
    with pytest.raises(httpx.HTTPStatusError, match="404 Not Found .*: Workflow not found"):
        await tools.get_workflow("nope")


async def test_create_workflow(tools, fake):
    result = await tools.create_workflow("wgs")
    assert fake.workflows[result["id"]] == {"id": result["id"], "name": "wgs",
                                            "attributes": None}


async def test_create_workflow_with_attributes(tools, fake):
    attrs = [{"key": "category", "value": "alignment"}]
    result = await tools.create_workflow("wgs", attributes=attrs)
    assert fake.workflows[result["id"]]["attributes"] == attrs


async def test_create_workflow_omits_empty_attributes(tools, fake):
    await tools.create_workflow("wgs", attributes=[])
    assert json.loads(fake.requests[-1].content) == {"name": "wgs"}


# --- versions ----------------------------------------------------------------

async def test_create_version_records_the_given_schema(tools, fake):
    workflow_id = fake.add_workflow(versions=0)
    await tools.create_workflow_version(workflow_id, "ngs360://f1",
                                        inputs=GOOD_TOOL_INPUTS,
                                        outputs=GOOD_TOOL_OUTPUTS)
    version = fake.latest_version(workflow_id)
    assert version["inputs"] == stored(GOOD_TOOL_INPUTS)
    assert version["outputs"] == stored(GOOD_TOOL_OUTPUTS, output=True)
    assert fake.deployments == [], "the primitive must not deploy"


async def test_create_version_never_reads_the_definition(tools, fake):
    workflow_id = fake.add_workflow(versions=0)
    await tools.create_workflow_version(workflow_id, "ngs360://f1", inputs=GOOD_TOOL_INPUTS)
    assert fake.calls() == [("POST", f"/workflows/{workflow_id}/versions")]


async def test_create_version_without_schema_leaves_it_null(tools, fake):
    workflow_id = fake.add_workflow(versions=0)
    await tools.create_workflow_version(workflow_id, "s3://bucket/x.cwl")
    assert json.loads(fake.requests[-1].content) == {"definition_uri": "s3://bucket/x.cwl"}
    version = fake.latest_version(workflow_id)
    assert version["inputs"] is None and version["outputs"] is None


async def test_create_version_sends_empty_lists_as_empty(tools, fake):
    # [] means "declares no parameters", which is not the same as null.
    workflow_id = fake.add_workflow(versions=0)
    await tools.create_workflow_version(workflow_id, "ngs360://f1", inputs=[], outputs=[])
    version = fake.latest_version(workflow_id)
    assert version["inputs"] == [] and version["outputs"] == []


async def test_create_version_one_side_only(tools, fake):
    workflow_id = fake.add_workflow(versions=0)
    await tools.create_workflow_version(workflow_id, "ngs360://f1", outputs=GOOD_TOOL_OUTPUTS)
    version = fake.latest_version(workflow_id)
    assert version["inputs"] is None
    assert version["outputs"] == stored(GOOD_TOOL_OUTPUTS, output=True)


async def test_create_version_malformed_schema_names_the_field(tools, fake):
    # Called directly, the typed arguments aren't enforced, so this is the
    # API's own validation (see test_mcp_interface for the MCP-level check).
    workflow_id = fake.add_workflow(versions=0)
    with pytest.raises(httpx.HTTPStatusError, match=r"422 .*inputs\.0\.required: Field required"):
        await tools.create_workflow_version(
            workflow_id, "ngs360://f1", inputs=[{"id": "x", "type": "File"}])
    assert fake.versions[workflow_id] == []


async def test_list_and_get_versions(tools, fake):
    workflow_id = fake.add_workflow(versions=2)
    assert [v["version"] for v in await tools.list_workflow_versions(workflow_id)] == [1, 2]
    assert (await tools.get_workflow_version(workflow_id, 2))["version"] == 2


async def test_get_missing_version(tools, fake):
    workflow_id = fake.add_workflow(versions=1)
    with pytest.raises(httpx.HTTPStatusError, match="Version not found"):
        await tools.get_workflow_version(workflow_id, 9)


# --- aliases -----------------------------------------------------------------

@pytest.mark.parametrize("version_num, expected", [
    (2, 2), ("2", 2), ("latest", 3), ("  Latest ", 3),
])
async def test_set_alias(tools, fake, version_num, expected):
    workflow_id = fake.add_workflow(versions=3)
    await tools.set_workflow_alias(workflow_id, "production", version_num)
    assert fake.aliases[workflow_id] == {"production": expected}


async def test_set_alias_latest_uses_highest_number_not_list_order(tools, fake):
    workflow_id = fake.add_workflow(versions=3)
    fake.versions[workflow_id].reverse()          # API sorts by created_at
    await tools.set_workflow_alias(workflow_id, "production", "latest")
    assert fake.aliases[workflow_id] == {"production": 3}


async def test_set_alias_rejects_garbage_without_calling_the_api(tools, fake):
    workflow_id = fake.add_workflow()
    with pytest.raises(ValueError, match="integer or the literal string 'latest'"):
        await tools.set_workflow_alias(workflow_id, "production", "newest")
    assert fake.writes() == []


async def test_set_alias_latest_with_no_versions(tools, fake):
    workflow_id = fake.add_workflow(versions=0)
    with pytest.raises(RuntimeError, match="no registered versions"):
        await tools.set_workflow_alias(workflow_id, "production", "latest")


async def test_list_and_delete_aliases(tools, fake):
    workflow_id = fake.add_workflow(versions=2)
    fake.aliases[workflow_id] = {"production": 1, "development": 2}

    assert len(await tools.list_workflow_aliases(workflow_id)) == 2
    assert await tools.list_workflow_aliases(workflow_id, alias="production") == \
        [{"alias": "production", "version": 1}]
    assert fake.requests[-1].url.params["alias"] == "production"

    assert await tools.delete_workflow_alias(workflow_id, "production") is None
    assert fake.aliases[workflow_id] == {"development": 2}


async def test_delete_missing_alias(tools, fake):
    workflow_id = fake.add_workflow()
    with pytest.raises(httpx.HTTPStatusError, match="Alias not found"):
        await tools.delete_workflow_alias(workflow_id, "production")


# --- deployments ---------------------------------------------------------------

async def test_deployment_with_external_id_is_stored_as_given(tools, fake):
    workflow_id = fake.add_workflow()
    result = await tools.create_workflow_deployment(
        workflow_id, 1, "Arvados", external_id="zzzzz-7fd4e-0123456789abcde")
    assert result["external_id"] == "zzzzz-7fd4e-0123456789abcde"
    assert json.loads(fake.requests[-1].content) == {
        "engine": "Arvados", "external_id": "zzzzz-7fd4e-0123456789abcde"}


async def test_omics_deployment_without_external_id_auto_registers(tools, fake):
    workflow_id = fake.add_workflow(versions=0)
    file_id = fake.add_file(b"{}")
    fake._new_version(workflow_id, {"definition_uri": f"ngs360://{file_id}"})
    result = await tools.create_workflow_deployment(workflow_id, 1, OMICS_ENGINE)
    assert result["external_id"].startswith("arn:aws:omics:")
    assert json.loads(fake.requests[-1].content) == {"engine": OMICS_ENGINE}


async def test_non_omics_deployment_needs_external_id(tools, fake):
    workflow_id = fake.add_workflow()
    with pytest.raises(httpx.HTTPStatusError, match="external_id is required"):
        await tools.create_workflow_deployment(workflow_id, 1, "Arvados")


async def test_list_deployments_all_versions_or_one(tools, fake):
    workflow_id = fake.add_workflow(versions=2)
    for version in (1, 2):
        await tools.create_workflow_deployment(workflow_id, version, "Arvados",
                                               external_id=f"x{version}")

    assert len(await tools.list_workflow_deployments(workflow_id)) == 2
    assert fake.requests[-1].url.path.endswith(f"/workflows/{workflow_id}/deployments")

    only_v2 = await tools.list_workflow_deployments(workflow_id, version_num=2)
    assert [d["external_id"] for d in only_v2] == ["x2"]
    assert fake.requests[-1].url.path.endswith("/versions/2/deployments")


async def test_list_deployments_passes_filters(tools, fake):
    workflow_id = fake.add_workflow()
    await tools.list_workflow_deployments(workflow_id, alias="production", engine="Arvados")
    assert dict(fake.requests[-1].url.params) == {"alias": "production", "engine": "Arvados"}


async def test_delete_deployment(tools, fake):
    workflow_id = fake.add_workflow()
    deployment = await tools.create_workflow_deployment(workflow_id, 1, "Arvados",
                                                        external_id="x")
    assert await tools.delete_workflow_deployment(workflow_id, 1, deployment["id"]) is None
    assert fake.deployments == []


async def test_writes_need_a_valid_token(tools_with_token, fake):
    tools = tools_with_token("expired")
    with pytest.raises(httpx.HTTPStatusError, match="401 .*Could not validate credentials"):
        await tools.create_workflow("wgs")
    assert fake.workflows == {}
