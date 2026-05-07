"""MCP tools for the Jobs API."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ngs360_mcp_server.client import NGS360Client


def register_jobs_tools(mcp: FastMCP, client: NGS360Client) -> None:
    """Register all jobs-related tools with the MCP server."""

    @mcp.tool()
    async def list_jobs(
        skip: int = 0,
        limit: int = 100,
        user: str | None = None,
        status_filter: str | None = None,
        sort_by: str = "submitted_on",
        sort_order: str = "desc",
    ) -> dict:
        """List batch jobs with optional filtering and sorting.

        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            user: Optional filter by username
            status_filter: Optional filter by status (SUBMITTED, PENDING, RUNNABLE, STARTING, RUNNING, SUCCEEDED, FAILED)
            sort_by: Field to sort by (defaults to submitted_on)
            sort_order: Sort order (asc or desc)
        """
        params: dict[str, Any] = {
            "skip": skip,
            "limit": limit,
            "sort_by": sort_by,
            "sort_order": sort_order,
        }
        if user:
            params["user"] = user
        if status_filter:
            params["status_filter"] = status_filter
        return await client.get("/jobs", params=params)

    @mcp.tool()
    async def get_job(job_id: str) -> dict:
        """Get details of a specific batch job.

        Args:
            job_id: The job UUID
        """
        return await client.get(f"/jobs/{job_id}")

    @mcp.tool()
    async def submit_job(
        job_name: str,
        job_definition: str,
        job_queue: str,
        command: str,
        user: str,
        environment: list[dict[str, str]] | None = None,
    ) -> dict:
        """Submit a new batch job to AWS Batch.

        Args:
            job_name: Name for the batch job
            job_definition: AWS Batch job definition ARN
            job_queue: AWS Batch job queue name
            command: Command string to execute
            user: Username submitting the job
            environment: Optional list of environment variables [{"name": "KEY", "value": "VAL"}]
        """
        body: dict[str, Any] = {
            "job_name": job_name,
            "job_definition": job_definition,
            "job_queue": job_queue,
            "command": command,
            "user": user,
        }
        if environment:
            body["environment"] = environment
        return await client.post("/jobs", json=body)

    @mcp.tool()
    async def update_job(
        job_id: str,
        log_stream_name: str | None = None,
        status: str | None = None,
        viewed: bool | None = None,
    ) -> dict:
        """Update a batch job's status or metadata.

        Args:
            job_id: The job UUID
            log_stream_name: Optional CloudWatch log stream name
            status: Optional new status (SUBMITTED, PENDING, RUNNABLE, STARTING, RUNNING, SUCCEEDED, FAILED)
            viewed: Optional viewed flag
        """
        body: dict[str, Any] = {}
        if log_stream_name is not None:
            body["log_stream_name"] = log_stream_name
        if status is not None:
            body["status"] = status
        if viewed is not None:
            body["viewed"] = viewed
        return await client.put(f"/jobs/{job_id}", json=body)

    @mcp.tool()
    async def get_job_log(job_id: str) -> list:
        """Get the full log output for a batch job.

        Args:
            job_id: The job UUID
        """
        return await client.get(f"/jobs/{job_id}/log")

    @mcp.tool()
    async def get_job_log_paginated(
        job_id: str,
        limit: int = 1000,
        next_token: str | None = None,
        start_from_head: bool = True,
    ) -> dict:
        """Get paginated log output for a batch job.

        Args:
            job_id: The job UUID
            limit: Number of log lines to return (1-10000)
            next_token: Pagination token from previous response
            start_from_head: Start from beginning (true) or end (false)
        """
        params: dict[str, Any] = {
            "limit": limit,
            "start_from_head": start_from_head,
        }
        if next_token:
            params["next_token"] = next_token
        return await client.get(f"/jobs/{job_id}/log/paginated", params=params)
