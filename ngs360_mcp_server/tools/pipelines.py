"""MCP tools for the Pipelines API."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ngs360_mcp_server.client import NGS360Client


def register_pipelines_tools(mcp: FastMCP, client: NGS360Client) -> None:
    """Register all pipeline-related tools with the MCP server."""

    @mcp.tool()
    async def list_pipelines(
        page: int = 1,
        per_page: int = 20,
        sort_by: str = "name",
        sort_order: str = "asc",
    ) -> dict:
        """List pipelines with pagination and sorting.

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
        return await client.get("/pipelines", params=params)

    @mcp.tool()
    async def get_pipeline(pipeline_id: str) -> dict:
        """Get details of a specific pipeline.

        Args:
            pipeline_id: The pipeline UUID
        """
        return await client.get(f"/pipelines/{pipeline_id}")

    @mcp.tool()
    async def create_pipeline(
        name: str,
        version: str | None = None,
        attributes: list[dict[str, str]] | None = None,
        workflow_ids: list[str] | None = None,
    ) -> dict:
        """Create a new pipeline (named collection of workflows).

        Args:
            name: Pipeline name
            version: Optional version string
            attributes: Optional key-value attributes
            workflow_ids: Optional list of workflow UUIDs to include
        """
        body: dict[str, Any] = {"name": name}
        if version is not None:
            body["version"] = version
        if attributes:
            body["attributes"] = attributes
        if workflow_ids:
            body["workflow_ids"] = workflow_ids
        return await client.post("/pipelines", json=body)

    @mcp.tool()
    async def add_workflow_to_pipeline(
        pipeline_id: str, workflow_id: str
    ) -> dict:
        """Add a workflow to a pipeline.

        Args:
            pipeline_id: The pipeline UUID
            workflow_id: UUID of the workflow to associate
        """
        return await client.post(
            f"/pipelines/{pipeline_id}/workflows",
            params={"workflow_id": workflow_id},
        )

    @mcp.tool()
    async def remove_workflow_from_pipeline(
        pipeline_id: str, workflow_id: str
    ) -> None:
        """Remove a workflow from a pipeline.

        Args:
            pipeline_id: The pipeline UUID
            workflow_id: The workflow UUID to remove
        """
        await client.delete(
            f"/pipelines/{pipeline_id}/workflows/{workflow_id}"
        )
