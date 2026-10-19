"""Reading the input/output schema off packed CWL."""

import json

import pytest

from ngs360_mcp_server.tools.workflows import (
    _cwl_doc,
    _cwl_short_id,
    _cwl_type,
    _io_from_packed_bytes,
)

from .conftest import (
    CWL,
    GOOD_TOOL_INPUTS,
    GOOD_TOOL_OUTPUTS,
    GOOD_WORKFLOW_INPUTS,
    GOOD_WORKFLOW_OUTPUTS,
    PACKED,
)


@pytest.mark.parametrize("spec, expected", [
    ("File", "File"),
    (["null", "File"], "File?"),
    ({"type": "array", "items": "File"}, "File[]"),
    (["null", {"type": "array", "items": "string"}], "string[]?"),
    ({"type": "array", "items": ["null", "File"]}, "File?[]"),
    ({"type": "array", "items": {"type": "array", "items": "File"}}, "File[][]"),
    (["int", "string"], "(int|string)"),
    (["null", {"type": "array", "items": ["float", "string"]}], "(float|string)[]?"),
    ({"type": "enum", "symbols": ["#main/assay/WES", "#main/assay/WGS"]}, "enum(WES|WGS)"),
    ({"type": "record", "fields": [{"name": "#main/r/a"}, {"name": "#main/r/b"}]},
     "record(a,b)"),
    ({"type": "File"}, "File"),
])
def test_cwl_type(spec, expected):
    assert _cwl_type(spec) == expected


def test_short_id_strips_the_namespace():
    assert _cwl_short_id("#main/sample_id") == "sample_id"
    assert _cwl_short_id("#main/assay/WES") == "WES"


@pytest.mark.parametrize("param, expected", [
    ({"doc": "  The doc  "}, "The doc"),
    ({"label": "Only a label"}, "Only a label"),
    ({"doc": "doc wins", "label": "label loses"}, "doc wins"),
    ({"doc": ["first para", "second para"]}, "first para\nsecond para"),
    ({}, None),
])
def test_cwl_doc(param, expected):
    assert _cwl_doc(param) == expected


def test_lone_tool_pack():
    inputs, outputs, warning = _io_from_packed_bytes((PACKED / "good_tool.json").read_bytes())
    assert warning is None
    assert inputs == GOOD_TOOL_INPUTS
    assert outputs == GOOD_TOOL_OUTPUTS


def test_workflow_pack_reads_only_main():
    raw = (PACKED / "good_workflow.json").read_bytes()
    graph_ids = [p["id"] for p in json.loads(raw)["$graph"]]
    assert len(graph_ids) > 1, "fixture should pack to a multi-process $graph"

    inputs, outputs, warning = _io_from_packed_bytes(raw)
    assert warning is None
    assert inputs == GOOD_WORKFLOW_INPUTS
    assert outputs == GOOD_WORKFLOW_OUTPUTS
    assert "files" not in {i["id"] for i in inputs}, "step tool's input leaked in"


def test_no_parameters_records_empty_lists_not_none():
    inputs, outputs, warning = _io_from_packed_bytes(
        (PACKED / "pass_no_parameters.json").read_bytes())
    assert (inputs, outputs, warning) == ([], [], None)


def test_byte_order_mark_is_tolerated():
    raw = b"\xef\xbb\xbf" + (PACKED / "good_tool.json").read_bytes()
    inputs, _, warning = _io_from_packed_bytes(raw)
    assert warning is None and inputs == GOOD_TOOL_INPUTS


def test_infinite_default_is_refused():
    # cwltool packs `default: .inf` as the bare literal Infinity, which is
    # not JSON and would corrupt the request body.
    raw = (PACKED / "fail_schema_inf_default.json").read_bytes()
    assert b"Infinity" in raw
    inputs, outputs, warning = _io_from_packed_bytes(raw)
    assert inputs is None and outputs is None
    assert "Out of range float" in warning


@pytest.mark.parametrize("label, raw, reason", [
    ("unpacked YAML", (CWL / "fail_remote_unpacked.cwl").read_bytes(), "cwltool --pack"),
    ("JSON, not CWL", (CWL / "fail_remote_not_cwl.json").read_bytes(), "#main"),
    ("two Workflows, no #main",
     (CWL / "fail_remote_two_entry_processes.json").read_bytes(), "#main"),
    ("empty", b"", "not JSON"),
    ("binary", b"\xff\xfe\x00junk", "not JSON"),
    ("top-level list", b"[1, 2]", "could not read"),
    ("top-level scalar", b"42", "could not read"),
    ("null", b"null", "could not read"),
    ("$graph is a dict", b'{"$graph": {"id": "#main"}}', "could not read"),
    ("$graph of non-dicts", b'{"$graph": ["x", 3]}', "could not read"),
    ("inputs is a string", b'{"id": "#main", "inputs": "oops"}', "could not read"),
    ("param without type", b'{"id": "#main", "inputs": [{"id": "#main/x"}]}', "KeyError"),
    ("param without id", b'{"id": "#main", "inputs": [{"type": "File"}]}', "KeyError"),
    ("enum without symbols",
     b'{"id": "#main", "inputs": [{"id": "#main/e", "type": {"type": "enum"}}]}', "KeyError"),
    ("NaN inside a list default",
     b'{"id": "#main", "inputs": [{"id": "#main/x", "type": "float", "default": [1, NaN]}]}',
     "Out of range float"),
])
def test_unreadable_definitions_warn_and_record_nothing(label, raw, reason):
    """Never raises; returns None (never []) so the columns stay NULL."""
    inputs, outputs, warning = _io_from_packed_bytes(raw)
    assert inputs is None and outputs is None, label
    assert warning.startswith("inputs/outputs were not recorded")
    assert reason in warning, warning
