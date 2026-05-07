"""MCP tools for the QC Metrics API."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ngs360_mcp_server.client import NGS360Client


def register_qcmetrics_tools(mcp: FastMCP, client: NGS360Client) -> None:
    """Register all QC metrics-related tools with the MCP server."""

    @mcp.tool()
    async def create_qcrecord(
        project_id: str | None = None,
        sequencing_run_id: str | None = None,
        workflow_run_id: str | None = None,
        metadata: dict[str, str] | None = None,
        metrics: list[dict[str, Any]] | None = None,
        output_files: list[dict[str, Any]] | None = None,
    ) -> dict:
        """Create a new QC record with metrics and output files.

        Exactly one of project_id or sequencing_run_id must be provided.

        Args:
            project_id: Project-scoped record (e.g., P-1234)
            sequencing_run_id: Run-scoped record (run_id string)
            workflow_run_id: Optional workflow run UUID (provenance)
            metadata: Pipeline metadata {"pipeline": "RNA-Seq", "version": "2.0"}
            metrics: List of metric groups, each with:
                - name: Metric group name
                - samples: Optional [{"sample_name": "S1", "role": "tumor"}]
                - values: {"reads": 50000000, "alignment_rate": 95.5}
            output_files: Optional list of file records to create
        """
        body: dict[str, Any] = {}
        if project_id is not None:
            body["project_id"] = project_id
        if sequencing_run_id is not None:
            body["sequencing_run_id"] = sequencing_run_id
        if workflow_run_id is not None:
            body["workflow_run_id"] = workflow_run_id
        if metadata is not None:
            body["metadata"] = metadata
        if metrics is not None:
            body["metrics"] = metrics
        if output_files is not None:
            body["output_files"] = output_files
        return await client.post("/qcmetrics", json=body)

    @mcp.tool()
    async def get_qcrecord(qcrecord_id: str) -> dict:
        """Get a specific QC record by UUID.

        Args:
            qcrecord_id: The QC record UUID
        """
        return await client.get(f"/qcmetrics/{qcrecord_id}")

    @mcp.tool()
    async def search_qcrecords(
        project_id: str | None = None,
        sequencing_run_id: str | None = None,
        workflow_run_id: str | None = None,
        latest: bool = True,
        page: int = 1,
        per_page: int = 100,
    ) -> dict:
        """Search QC records with filters.

        Args:
            project_id: Filter by project ID
            sequencing_run_id: Filter by sequencing run_id string
            workflow_run_id: Filter by workflow run UUID
            latest: Return only newest record per scope (default True)
            page: Page number
            per_page: Results per page
        """
        params: dict[str, Any] = {
            "latest": latest,
            "page": page,
            "per_page": per_page,
        }
        if project_id:
            params["project_id"] = project_id
        if sequencing_run_id:
            params["sequencing_run_id"] = sequencing_run_id
        if workflow_run_id:
            params["workflow_run_id"] = workflow_run_id
        return await client.get("/qcmetrics/search", params=params)

    @mcp.tool()
    async def search_qcrecords_advanced(
        filter_on: dict | None = None,
        page: int = 1,
        per_page: int = 100,
        latest: bool = True,
    ) -> dict:
        """Search QC records with advanced filtering (POST).

        Args:
            filter_on: Filter dictionary, e.g.:
                {"project_id": "P-1234", "metadata": {"pipeline": "RNA-Seq"}}
            page: Page number
            per_page: Results per page
            latest: Return only newest record per scope
        """
        body: dict[str, Any] = {
            "page": page,
            "per_page": per_page,
            "latest": latest,
        }
        if filter_on:
            body["filter_on"] = filter_on
        return await client.post("/qcmetrics/search", json=body)

    @mcp.tool()
    async def delete_qcrecord(qcrecord_id: str) -> dict:
        """Delete a QC record and all associated data (irreversible).

        Args:
            qcrecord_id: The QC record UUID
        """
        return await client.delete(f"/qcmetrics/{qcrecord_id}")
