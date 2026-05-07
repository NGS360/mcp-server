"""MCP tools for the Workflows API."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ngs360_mcp_server.client import NGS360Client


def register_workflows_tools(mcp: FastMCP, client: NGS360Client) -> None:
    """Register all workflow-related tools with the MCP server."""

    @mcp.tool()
    async def list_workflows(
        page: int = 1,
        per_page: int = 20,
        sort_by: str = "name",
        sort_order: str = "asc",
    ) -> list:
        """List workflows with pagination and sorting.

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
        return await client.get("/workflows", params=params)

    @mcp.tool()
    async def get_workflow(workflow_id: str) -> dict:
        """Get details of a specific workflow.

        Args:
            workflow_id: The workflow UUID
        """
        return await client.get(f"/workflows/{workflow_id}")

    @mcp.tool()
    async def create_workflow(
        name: str,
        attributes: list[dict[str, str]] | None = None,
    ) -> dict:
        """Create a new workflow identity.

        Args:
            name: Workflow name
            attributes: Optional key-value attributes
                        [{"key": "category", "value": "alignment"}]
        """
        body: dict[str, Any] = {"name": name}
        if attributes:
            body["attributes"] = attributes
        return await client.post("/workflows", json=body)

    @mcp.tool()
    async def create_workflow_version(
        workflow_id: str, definition_uri: str
    ) -> dict:
        """Create a new version for a workflow.

        Version number is auto-incremented.

        Args:
            workflow_id: The workflow UUID
            definition_uri: URI to the workflow definition file
        """
        return await client.post(
            f"/workflows/{workflow_id}/versions",
            json={"definition_uri": definition_uri},
        )

    @mcp.tool()
    async def list_workflow_versions(workflow_id: str) -> list:
        """List all versions of a workflow.

        Args:
            workflow_id: The workflow UUID
        """
        return await client.get(f"/workflows/{workflow_id}/versions")

    @mcp.tool()
    async def get_workflow_version(
        workflow_id: str, version_id: str
    ) -> dict:
        """Get a specific workflow version.

        Args:
            workflow_id: The workflow UUID
            version_id: The version UUID
        """
        return await client.get(
            f"/workflows/{workflow_id}/versions/{version_id}"
        )

    @mcp.tool()
    async def set_workflow_alias(
        workflow_id: str,
        alias: str,
        workflow_version_id: str,
    ) -> dict:
        """Set or update a workflow version alias (e.g., 'production').

        Args:
            workflow_id: The workflow UUID
            alias: Alias name (e.g., production, development)
            workflow_version_id: UUID of the version to point to
        """
        return await client.put(
            f"/workflows/{workflow_id}/aliases/{alias}",
            json={"workflow_version_id": workflow_version_id},
        )

    @mcp.tool()
    async def list_workflow_aliases(
        workflow_id: str, alias: str | None = None
    ) -> list:
        """List aliases for a workflow.

        Args:
            workflow_id: The workflow UUID
            alias: Optional filter to a specific alias name
        """
        params = {}
        if alias:
            params["alias"] = alias
        return await client.get(
            f"/workflows/{workflow_id}/aliases", params=params
        )

    @mcp.tool()
    async def delete_workflow_alias(workflow_id: str, alias: str) -> None:
        """Remove an alias from a workflow.

        Args:
            workflow_id: The workflow UUID
            alias: Alias name to remove
        """
        await client.delete(f"/workflows/{workflow_id}/aliases/{alias}")

    @mcp.tool()
    async def create_workflow_deployment(
        workflow_id: str,
        version_id: str,
        engine: str,
        external_id: str,
    ) -> dict:
        """Deploy a workflow version on a specific platform.

        Args:
            workflow_id: The workflow UUID
            version_id: The version UUID
            engine: Platform name (e.g., Arvados, SevenBridges)
            external_id: Workflow identifier on the external platform
        """
        return await client.post(
            f"/workflows/{workflow_id}/versions/{version_id}/deployments",
            json={"engine": engine, "external_id": external_id},
        )

    @mcp.tool()
    async def list_workflow_deployments(
        workflow_id: str,
        version_id: str | None = None,
        alias: str | None = None,
        engine: str | None = None,
    ) -> list:
        """List deployments for a workflow.

        Can list across all versions or for a specific version.

        Args:
            workflow_id: The workflow UUID
            version_id: Optional version UUID (if omitted, lists across all versions)
            alias: Optional alias filter (resolves to version)
            engine: Optional engine/platform filter
        """
        params: dict[str, Any] = {}
        if alias:
            params["alias"] = alias
        if engine:
            params["engine"] = engine

        if version_id:
            return await client.get(
                f"/workflows/{workflow_id}/versions/{version_id}/deployments",
                params=params,
            )
        return await client.get(
            f"/workflows/{workflow_id}/deployments", params=params
        )

    @mcp.tool()
    async def delete_workflow_deployment(
        workflow_id: str, version_id: str, deployment_id: str
    ) -> None:
        """Remove a platform deployment.

        Args:
            workflow_id: The workflow UUID
            version_id: The version UUID
            deployment_id: The deployment UUID
        """
        await client.delete(
            f"/workflows/{workflow_id}/versions/{version_id}"
            f"/deployments/{deployment_id}"
        )
