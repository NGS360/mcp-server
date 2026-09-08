"""MCP tools for the GA4GH Workflow Execution Service (WES) API."""

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from ngs360_mcp_server.client import NGS360Client


def register_wes_tools(mcp: FastMCP, wes_client: NGS360Client) -> None:
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
        filters: dict[str, Any] | None = None,
    ) -> dict:
        """List workflow runs from the WES service.

        Args:
            page_size: Number of runs to return per page
            page_token: Token for retrieving the next page of results
            filters: Server-side filter as a dict. Keys match WorkflowRun
                column names, e.g. workflow_url, state, project, user_id;
                nested `tags` matches on tag values, e.g.
                {"tags": {"ProjectId": "P-XXXX"}}. Unknown keys are
                silently ignored server-side.
        """
        params: dict[str, Any] = {}
        if page_size is not None:
            params["page_size"] = page_size
        if page_token is not None:
            params["page_token"] = page_token
        if filters is not None:
            params["filters"] = json.dumps(filters)
        return await wes_client.get("/runs", params=params)

    @mcp.tool()
    async def wes_run_workflow(
        workflow_url: str,
        workflow_type: str,
        workflow_type_version: str,
        workflow_params: dict[str, Any] | None = None,
        workflow_engine: str | None = None,
        workflow_engine_version: str | None = None,
        workflow_engine_parameters: dict[str, Any] | None = None,
        tags: dict[str, str] | None = None,
    ) -> dict:
        """Submit a new workflow run to the WES service.

        Returns 200 + a run_id even when the run fails synchronously at
        the WES service (e.g. workflow not deployed, file resolution
        errored). Callers must poll wes_get_run_status / wes_get_run_log
        after submission to confirm the run actually reached RUNNING or
        COMPLETE — do not report a run as "submitted successfully" based
        on this call alone.

        Args:
            workflow_url: Workflow reference. NGS360 workflows use
                "<workflow_id_no_dashes>:<version_or_alias>".
            workflow_type: "CWL" or "WDL" (case-insensitive).
            workflow_type_version: e.g. "v1.0", "v1.2". Not validated
                server-side.
            workflow_params: Input parameters for the workflow. File
                inputs can be S3 URIs, or "ngs360://<file_id>" — the
                server resolves ngs360:// references to their backing
                S3 URIs before dispatching to Omics.
            workflow_engine: Usually omit; inferred from the deployment.
            workflow_engine_version: Usually omit.
            workflow_engine_parameters: AWS Omics run options. No
                defaults are applied — callers decide explicitly.
                Unknown keys are silently dropped downstream — spell
                exactly:
                  * name (str): Run name. Falls back to tags.TaskName.
                  * workflowVersionName (str): Pin Omics workflow version.
                  * cacheId (str): Reuse outputs from an Omics run cache.
                  * storageType (str): "STATIC" or "DYNAMIC". If set to
                    STATIC and the workflow was registered as DYNAMIC,
                    also pass storageCapacity or Omics will reject.
                  * storageCapacity (int): GiB; only with storageType=STATIC.
                  * networkingMode (str): "VPC" for workflows that call
                    licensed servers (e.g. Sentieon); must be paired
                    with configurationName.
                  * configurationName (str): Named Omics run config;
                    paired with networkingMode.
                Note: outputUri is NOT accepted here — the WES service
                constructs it unconditionally from tags.ProjectId as
                s3://<configured_bucket>/Project/<ProjectId>/, and any
                caller-supplied value is silently discarded.
            tags: Tags for the run. **ProjectId is required** for audit
                and cost tracking, and for the outputUri the WES
                constructs. Other special keys: TaskName (fallback for
                `name`); ProjectId is renamed to `Project` on outgoing
                Omics tags for AWS cost tracking (DB storage keeps
                ProjectId).

        Raises:
            ValueError: If tags is missing or does not include a
                ProjectId. Fail-fast at the MCP layer so an LLM sees a
                clear error and can prompt the user, instead of a raw
                HTTP 500 from the WES service.
        """
        if not tags or not tags.get("ProjectId"):
            raise ValueError(
                "tags.ProjectId is required. Every WES run must be tagged "
                "with a project identifier for audit and cost tracking. "
                "Pass e.g. tags={'ProjectId': 'P-XXXXXXXX-XXXX', ...}."
            )

        form: dict[str, Any] = {
            "workflow_url": workflow_url,
            "workflow_type": workflow_type,
            "workflow_type_version": workflow_type_version,
            "workflow_engine": workflow_engine,
            "workflow_engine_version": workflow_engine_version,
        }
        if workflow_params is not None:
            form["workflow_params"] = json.dumps(workflow_params)
        if workflow_engine_parameters is not None:
            form["workflow_engine_parameters"] = json.dumps(workflow_engine_parameters)
        if tags is not None:
            form["tags"] = json.dumps(tags)
        return await wes_client.post_form("/runs", data=form)

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
