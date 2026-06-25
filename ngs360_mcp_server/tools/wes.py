"""MCP tools for the GA4GH Workflow Execution Service (WES) API."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ngs360_mcp_server.wes_client import WESClient


def register_wes_tools(mcp: FastMCP, wes_client: WESClient) -> None:
    """Register all GA4GH WES-related tools with the MCP server."""

    @mcp.tool()
    async def wes_get_service_info() -> dict:
        """Get information about the WES service.

        Returns supported workflow types, WES versions, filesystem protocols,
        workflow engine versions, default parameters, and system state counts.
        """
        return await wes_client.get("/service-info")

    @mcp.tool()
    async def wes_list_runs(
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> dict:
        """List workflow runs from the WES service.

        Returns a paginated list of workflow runs the caller has permission to see.

        Args:
            page_size: Number of runs to return per page
            page_token: Token for retrieving the next page of results
        """
        params: dict[str, Any] = {}
        if page_size is not None:
            params["page_size"] = page_size
        if page_token is not None:
            params["page_token"] = page_token
        return await wes_client.get("/runs", params=params)

    @mcp.tool()
    async def wes_run_workflow(
        workflow_url: str,
        workflow_type: str,
        workflow_type_version: str,
        workflow_params: dict[str, Any] | None = None,
        workflow_engine: str | None = None,
        workflow_engine_version: str | None = None,
        workflow_engine_parameters: dict[str, str] | None = None,
        tags: dict[str, str] | None = None,
    ) -> dict:
        """Submit a new workflow run to the WES service.

        Args:
            workflow_url: URL or relative path to the workflow definition (CWL/WDL)
            workflow_type: Workflow language type (e.g., "CWL", "WDL")
            workflow_type_version: Version of the workflow language (e.g., "v1.0")
            workflow_params: Input parameters for the workflow (JSON object)
            workflow_engine: Workflow engine to use (e.g., "cromwell", "toil")
            workflow_engine_version: Version of the workflow engine
            workflow_engine_parameters: Additional engine-specific parameters
            tags: Arbitrary key-value tags for the run
        """
        body: dict[str, Any] = {
            "workflow_url": workflow_url,
            "workflow_type": workflow_type,
            "workflow_type_version": workflow_type_version,
        }
        if workflow_params is not None:
            body["workflow_params"] = workflow_params
        if workflow_engine is not None:
            body["workflow_engine"] = workflow_engine
        if workflow_engine_version is not None:
            body["workflow_engine_version"] = workflow_engine_version
        if workflow_engine_parameters is not None:
            body["workflow_engine_parameters"] = workflow_engine_parameters
        if tags is not None:
            body["tags"] = tags
        return await wes_client.post("/runs", json=body)

    @mcp.tool()
    async def wes_get_run_log(run_id: str) -> dict:
        """Get detailed information about a workflow run.

        Returns the run request, state, run log (stdout/stderr), task logs,
        and output files.

        Args:
            run_id: The workflow run identifier
        """
        return await wes_client.get(f"/runs/{run_id}")

    @mcp.tool()
    async def wes_get_run_status(run_id: str) -> dict:
        """Get the current status of a workflow run.

        Returns an abbreviated status with the run_id and state
        (UNKNOWN, QUEUED, INITIALIZING, RUNNING, PAUSED, COMPLETE,
        EXECUTOR_ERROR, SYSTEM_ERROR, CANCELED, CANCELING, PREEMPTED).

        Args:
            run_id: The workflow run identifier
        """
        return await wes_client.get(f"/runs/{run_id}/status")

    @mcp.tool()
    async def wes_cancel_run(run_id: str) -> dict:
        """Cancel a running workflow.

        Args:
            run_id: The workflow run identifier to cancel
        """
        return await wes_client.post(f"/runs/{run_id}/cancel")

    @mcp.tool()
    async def wes_list_tasks(
        run_id: str,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> dict:
        """List tasks for a workflow run.

        Returns a paginated list of tasks executed as part of the workflow run.

        Args:
            run_id: The workflow run identifier
            page_size: Number of tasks to return per page
            page_token: Token for retrieving the next page of results
        """
        params: dict[str, Any] = {}
        if page_size is not None:
            params["page_size"] = page_size
        if page_token is not None:
            params["page_token"] = page_token
        return await wes_client.get(f"/runs/{run_id}/tasks", params=params)

    @mcp.tool()
    async def wes_get_task(run_id: str, task_id: str) -> dict:
        """Get details of a specific task within a workflow run.

        Returns log information including name, command, start/end time,
        stdout, stderr, exit code, and system logs.

        Args:
            run_id: The workflow run identifier
            task_id: The task identifier
        """
        return await wes_client.get(f"/runs/{run_id}/tasks/{task_id}")
