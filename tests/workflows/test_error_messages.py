"""Error reporting: API reasons surfaced, partial failures explained."""

import inspect

import httpx
import pytest

from ngs360_mcp_server.tools.workflows import (
    _OMICS_ENGINE,
    _describe_http_error,
    _partial_failure_error,
    _surface_api_errors,
)


def _error(status, *, json=None, text=None, url="https://api.test/api/v1/workflows/w1"):
    request = httpx.Request("POST", url)
    if json is not None:
        response = httpx.Response(status, json=json, request=request)
    else:
        response = httpx.Response(status, text=text or "", request=request)
    return httpx.HTTPStatusError("raw httpx message", request=request, response=response)


class TestDescribeHttpError:
    def test_string_detail(self):
        msg = _describe_http_error(_error(404, json={"detail": "Workflow not found"}))
        assert msg == "404 Not Found from POST api.test/api/v1/workflows/w1: Workflow not found"

    def test_validation_detail_names_the_field(self):
        exc = _error(422, json={"detail": [
            {"loc": ["body", "inputs", 0, "required"], "msg": "Field required"},
            {"loc": ["body", "name"], "msg": "Input should be a valid string"},
        ]})
        assert _describe_http_error(exc).endswith(
            ": body.inputs.0.required: Field required; "
            "body.name: Input should be a valid string")

    def test_validation_entry_without_loc(self):
        exc = _error(422, json={"detail": [{"msg": "Input should be a valid UUID"}]})
        assert _describe_http_error(exc).endswith(": Input should be a valid UUID")

    def test_validation_entry_with_null_fields_does_not_crash(self):
        # A crash here would replace the API's error with a TypeError.
        exc = _error(422, json={"detail": [{"loc": None, "msg": "bad"}, {"loc": ["x"]}]})
        assert _describe_http_error(exc).endswith(": bad; x")

    def test_non_json_body(self):
        exc = _error(502, text="<html>Bad Gateway</html>")
        assert _describe_http_error(exc).endswith(": <html>Bad Gateway</html>")

    def test_empty_body(self):
        assert _describe_http_error(_error(500, text="")) == \
            "500 Internal Server Error from POST api.test/api/v1/workflows/w1"

    def test_query_string_is_never_included(self):
        # A presigned URL's query string is a bearer credential.
        exc = _error(403, text="AccessDenied",
                     url="https://s3.test/key.cwl?X-Amz-Signature=secret")
        msg = _describe_http_error(exc)
        assert "secret" not in msg and "X-Amz" not in msg
        assert "s3.test/key.cwl" in msg


class TestSurfaceApiErrors:
    @pytest.mark.anyio
    async def test_reraises_with_detail_and_same_type(self):
        @_surface_api_errors
        async def tool():
            raise _error(404, json={"detail": "Workflow not found"})

        with pytest.raises(httpx.HTTPStatusError, match="Workflow not found") as info:
            await tool()
        assert info.value.response.status_code == 404

    @pytest.mark.anyio
    async def test_other_exceptions_pass_through(self):
        @_surface_api_errors
        async def tool():
            raise ValueError("bad input")

        with pytest.raises(ValueError, match="bad input"):
            await tool()

    def test_preserves_what_fastmcp_reads(self):
        async def tool(workflow_id: str, version_num: int = 1) -> dict:
            """Docstring."""

        wrapped = _surface_api_errors(tool)
        assert wrapped.__name__ == "tool"
        assert wrapped.__doc__ == "Docstring."
        assert inspect.signature(wrapped) == inspect.signature(tool)
        assert inspect.iscoroutinefunction(wrapped)


class TestPartialFailureError:
    def test_nothing_created_keeps_the_original_error(self):
        assert _partial_failure_error({}, RuntimeError("x")) is None
        # update_workflow starts with a workflow that already existed.
        assert _partial_failure_error({"workflow_id": "w1"}, RuntimeError("x")) is None

    def test_failed_creating_workflow_after_upload(self):
        err = _partial_failure_error(
            {"file_id": "f1", "uploaded": True}, _error(500, json={"detail": "db down"}))
        msg = str(err)
        assert msg.startswith("Failed while creating the workflow: 500")
        assert "db down" in msg
        assert "uploaded the packed CWL as file f1" in msg
        assert "register_workflow_from_file_id(file_id='f1', name=...)" in msg

    def test_failed_creating_version(self):
        msg = str(_partial_failure_error(
            {"file_id": "f1", "workflow_id": "w1", "created_workflow": True},
            RuntimeError("boom")))
        assert msg.startswith("Failed while creating the version: boom")
        assert "created workflow w1" in msg
        assert "uploaded" not in msg, "the file was pre-existing, not uploaded here"
        assert "update_workflow_from_file_id(file_id='f1', workflow_id='w1')" in msg

    def test_failed_deploying(self):
        msg = str(_partial_failure_error(
            {"file_id": "f1", "uploaded": True, "workflow_id": "w1",
             "created_workflow": True, "version_num": 3},
            RuntimeError("lambda timeout")))
        assert msg.startswith("Failed while deploying to Omics: lambda timeout")
        assert "created version 3 of workflow w1" in msg
        assert (f"create_workflow_deployment(workflow_id='w1', version_num=3, "
                f"engine='{_OMICS_ENGINE}')") in msg
        assert "external_id" in msg
