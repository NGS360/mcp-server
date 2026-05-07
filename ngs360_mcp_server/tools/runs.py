"""MCP tools for the Runs API."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ngs360_mcp_server.client import NGS360Client


def register_runs_tools(mcp: FastMCP, client: NGS360Client) -> None:
    """Register all runs-related tools with the MCP server."""

    @mcp.tool()
    async def list_runs(
        page: int = 1,
        per_page: int = 20,
        sort_by: str = "run_id",
        sort_order: str = "asc",
    ) -> dict:
        """List sequencing runs with pagination and sorting.

        Args:
            page: Page number (1-indexed)
            per_page: Number of items per page
            sort_by: Field to sort by
            sort_order: Sort order (asc or desc)
        """
        params = {
            "page": page,
            "per_page": per_page,
            "sort_by": sort_by,
            "sort_order": sort_order,
        }
        return await client.get("/runs", params=params)

    @mcp.tool()
    async def get_run(run_id: str) -> dict:
        """Get details of a specific sequencing run.

        Args:
            run_id: The run identifier (e.g., '240101_A00000_0001_FLOWCELLID')
        """
        return await client.get(f"/runs/{run_id}")

    @mcp.tool()
    async def create_run(
        run_id: str,
        run_date: str,
        machine_id: str,
        run_number: str,
        flowcell_id: str,
        experiment_name: str | None = None,
        run_folder_uri: str | None = None,
        status: str | None = None,
        run_time: str | None = None,
    ) -> dict:
        """Create a new sequencing run.

        Args:
            run_id: Unique run identifier
            run_date: Run date in YYYY-MM-DD format
            machine_id: Instrument machine ID
            run_number: Run number (string)
            flowcell_id: Flowcell identifier
            experiment_name: Optional experiment name
            run_folder_uri: Optional URI to the run folder
            status: Optional status (In Progress, Uploading, Ready, Resync)
            run_time: Optional run time in HHMM format (4 digits)
        """
        body: dict[str, Any] = {
            "run_id": run_id,
            "run_date": run_date,
            "machine_id": machine_id,
            "run_number": run_number,
            "flowcell_id": flowcell_id,
        }
        if experiment_name is not None:
            body["experiment_name"] = experiment_name
        if run_folder_uri is not None:
            body["run_folder_uri"] = run_folder_uri
        if status is not None:
            body["status"] = status
        if run_time is not None:
            body["run_time"] = run_time
        return await client.post("/runs", json=body)

    @mcp.tool()
    async def update_run_status(run_id: str, run_status: str) -> dict:
        """Update the status of a sequencing run.

        Args:
            run_id: The run identifier
            run_status: New status (In Progress, Uploading, Ready, Resync)
        """
        return await client.put(f"/runs/{run_id}", json={"run_status": run_status})

    @mcp.tool()
    async def search_runs(
        query: str,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = "run_id",
        sort_order: str = "asc",
    ) -> dict:
        """Search sequencing runs using OpenSearch.

        Args:
            query: Search query string
            page: Page number (1-indexed)
            per_page: Number of items per page
            sort_by: Field to sort by (run_id or experiment_name)
            sort_order: Sort order (asc or desc)
        """
        params = {
            "query": query,
            "page": page,
            "per_page": per_page,
            "sort_by": sort_by,
            "sort_order": sort_order,
        }
        return await client.get("/runs/search", params=params)

    @mcp.tool()
    async def get_run_samplesheet(run_id: str) -> dict:
        """Get the sample sheet for a sequencing run.

        Args:
            run_id: The run identifier
        """
        return await client.get(f"/runs/{run_id}/samplesheet")

    @mcp.tool()
    async def get_run_metrics(run_id: str) -> dict:
        """Get demultiplexing metrics for a sequencing run.

        Args:
            run_id: The run identifier
        """
        return await client.get(f"/runs/{run_id}/metrics")

    @mcp.tool()
    async def list_demux_workflows() -> list:
        """List available demultiplex workflows."""
        return await client.get("/runs/demultiplex")

    @mcp.tool()
    async def get_demux_workflow_config(
        workflow_id: str, run_id: str | None = None
    ) -> dict:
        """Get configuration for a specific demultiplex workflow.

        Args:
            workflow_id: The workflow identifier
            run_id: Optional run ID to prepopulate s3_run_folder_path
        """
        params = {}
        if run_id:
            params["run_id"] = run_id
        return await client.get(f"/runs/demultiplex/{workflow_id}", params=params)

    @mcp.tool()
    async def submit_demux_job(
        workflow_id: str, run_id: str, inputs: dict[str, Any]
    ) -> dict:
        """Submit a demultiplex workflow job.

        Args:
            workflow_id: The workflow identifier
            run_id: The run to demultiplex
            inputs: Workflow input parameters
        """
        body = {
            "workflow_id": workflow_id,
            "run_id": run_id,
            "inputs": inputs,
        }
        return await client.post("/runs/demultiplex", json=body)

    @mcp.tool()
    async def associate_sample_with_run(
        run_id: str, sample_id: str
    ) -> dict:
        """Associate a sample with a sequencing run.

        Args:
            run_id: The run identifier
            sample_id: UUID of the sample to associate
        """
        return await client.post(
            f"/runs/{run_id}/samples", json={"sample_id": sample_id}
        )

    @mcp.tool()
    async def get_samples_for_run(run_id: str) -> list:
        """List sample associations for a sequencing run.

        Args:
            run_id: The run identifier
        """
        return await client.get(f"/runs/{run_id}/samples")

    @mcp.tool()
    async def clear_samples_for_run(run_id: str) -> dict:
        """Remove all sample associations and cleanup for a run (re-demux scenario).

        Args:
            run_id: The run identifier
        """
        return await client.delete(f"/runs/{run_id}/samples")

    @mcp.tool()
    async def remove_sample_from_run(run_id: str, sample_id: str) -> None:
        """Remove a single sample association from a run.

        Args:
            run_id: The run identifier
            sample_id: The sample identifier to remove
        """
        await client.delete(f"/runs/{run_id}/samples/{sample_id}")
