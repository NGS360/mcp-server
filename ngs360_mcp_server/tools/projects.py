"""MCP tools for the Projects API."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ngs360_mcp_server.client import NGS360Client


def register_projects_tools(mcp: FastMCP, client: NGS360Client) -> None:
    """Register all project-related tools with the MCP server."""

    @mcp.tool()
    async def list_projects(
        page: int = 1,
        per_page: int = 20,
        sort_by: str = "project_id",
        sort_order: str = "asc",
    ) -> dict:
        """List projects with pagination and sorting.

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
        return await client.get("/projects", params=params)

    @mcp.tool()
    async def get_project(project_id: str) -> dict:
        """Get details of a specific project.

        Args:
            project_id: The project identifier (e.g., 'P-1234')
        """
        return await client.get(f"/projects/{project_id}")

    @mcp.tool()
    async def create_project(
        name: str,
        attributes: list[dict[str, str]] | None = None,
    ) -> dict:
        """Create a new project.

        Args:
            name: Project name
            attributes: Optional list of key-value attributes
                        [{"key": "type", "value": "RNA-Seq"}]
        """
        body: dict[str, Any] = {"name": name}
        if attributes:
            body["attributes"] = attributes
        return await client.post("/projects", json=body)

    @mcp.tool()
    async def update_project(
        project_id: str,
        name: str | None = None,
        attributes: list[dict[str, str]] | None = None,
    ) -> dict:
        """Full replacement update of a project (PUT semantics).

        Attributes provided here replace all existing attributes.

        Args:
            project_id: The project identifier
            name: Optional new name
            attributes: Optional list of attributes (replaces all existing)
        """
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if attributes is not None:
            body["attributes"] = attributes
        return await client.put(f"/projects/{project_id}", json=body)

    @mcp.tool()
    async def patch_project(
        project_id: str,
        name: str | None = None,
        attributes: list[dict[str, str]] | None = None,
    ) -> dict:
        """Partially update a project (merge/upsert semantics).

        Unlike update_project, this does NOT remove attributes absent
        from the request.

        Args:
            project_id: The project identifier
            name: Optional new name
            attributes: Optional attributes to upsert
        """
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if attributes is not None:
            body["attributes"] = attributes
        return await client.patch(f"/projects/{project_id}", json=body)

    @mcp.tool()
    async def search_projects(
        query: str,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = "name",
        sort_order: str = "asc",
    ) -> dict:
        """Search projects by project_id or name.

        Args:
            query: Search query string
            page: Page number (1-indexed)
            per_page: Number of items per page
            sort_by: Field to sort by (project_id or name)
            sort_order: Sort order (asc or desc)
        """
        params = {
            "query": query,
            "page": page,
            "per_page": per_page,
            "sort_by": sort_by,
            "sort_order": sort_order,
        }
        return await client.get("/projects/search", params=params)

    @mcp.tool()
    async def add_sample_to_project(
        project_id: str,
        sample_id: str,
        attributes: list[dict[str, str]] | None = None,
        run_id: str | None = None,
    ) -> dict:
        """Add a sample to a project.

        Args:
            project_id: The project identifier
            sample_id: Sample identifier string
            attributes: Optional sample attributes
            run_id: Optional run_id to associate the sample with
        """
        body: dict[str, Any] = {"sample_id": sample_id}
        if attributes:
            body["attributes"] = attributes
        if run_id:
            body["run_id"] = run_id
        return await client.post(f"/projects/{project_id}/samples", json=body)

    @mcp.tool()
    async def get_project_samples(
        project_id: str,
        skip: int = 0,
        limit: int = 100,
        sort_by: str = "sample_id",
        sort_order: str = "asc",
        include_files: bool = False,
    ) -> dict:
        """Get samples for a project with pagination.

        Args:
            project_id: The project identifier
            skip: Number of records to skip
            limit: Maximum number of records to return
            sort_by: Field to sort by
            sort_order: Sort order (asc or desc)
            include_files: Whether to include file data for each sample
        """
        params: dict[str, Any] = {
            "skip": skip,
            "limit": limit,
            "sort_by": sort_by,
            "sort_order": sort_order,
        }
        if include_files:
            params["include"] = "files"
        return await client.get(f"/projects/{project_id}/samples", params=params)

    @mcp.tool()
    async def delete_sample_from_project(
        project_id: str, sample_id: str
    ) -> None:
        """Delete a sample from a project (superuser only, irreversible).

        Args:
            project_id: The project identifier
            sample_id: The sample identifier to delete
        """
        await client.delete(f"/projects/{project_id}/samples/{sample_id}")

    @mcp.tool()
    async def submit_pipeline_job(
        project_id: str,
        action: str,
        platform: str,
        project_type: str,
        reference: str | None = None,
        auto_release: bool | None = None,
    ) -> dict:
        """Submit a pipeline job to AWS Batch for a project.

        Args:
            project_id: The project identifier
            action: Pipeline action (create-project or export-project-results)
            platform: Platform name (Arvados or SevenBridges)
            project_type: Pipeline workflow type (e.g., RNA-Seq, WGS)
            reference: Export reference (required for export action)
            auto_release: Auto-release flag for export action
        """
        body: dict[str, Any] = {
            "action": action,
            "platform": platform,
            "project_type": project_type,
        }
        if reference is not None:
            body["reference"] = reference
        if auto_release is not None:
            body["auto_release"] = auto_release
        return await client.post(
            f"/projects/{project_id}/actions/submit", json=body
        )

    @mcp.tool()
    async def ingest_vendor_data(
        project_id: str,
        files_uri: str,
        manifest_uri: str,
    ) -> dict:
        """Ingest vendor data for a project.

        Args:
            project_id: The project identifier
            files_uri: Source S3 bucket/prefix of data to ingest
            manifest_uri: S3 path to the vendor manifest
        """
        params = {
            "files_uri": files_uri,
            "manifest_uri": manifest_uri,
        }
        return await client.post(
            f"/projects/{project_id}/ingest", params=params
        )
