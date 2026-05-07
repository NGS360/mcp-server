"""MCP tools for the Vendors API."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ngs360_mcp_server.client import NGS360Client


def register_vendors_tools(mcp: FastMCP, client: NGS360Client) -> None:
    """Register all vendor-related tools with the MCP server."""

    @mcp.tool()
    async def list_vendors(
        skip: int = 0,
        limit: int = 100,
        sort_by: str = "vendor_id",
        sort_order: str = "asc",
    ) -> dict:
        """List vendors with pagination and sorting.

        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            sort_by: Field to sort by
            sort_order: Sort order (asc or desc)
        """
        params = {
            "skip": skip,
            "limit": limit,
            "sort_by": sort_by,
            "sort_order": sort_order,
        }
        return await client.get("/vendors", params=params)

    @mcp.tool()
    async def get_vendor(vendor_id: str) -> dict:
        """Get details of a specific vendor.

        Args:
            vendor_id: The vendor identifier
        """
        return await client.get(f"/vendors/{vendor_id}")

    @mcp.tool()
    async def create_vendor(
        vendor_id: str,
        name: str,
        description: str,
        bucket: str | None = None,
    ) -> dict:
        """Create a new vendor.

        Args:
            vendor_id: Unique vendor identifier
            name: Vendor display name
            description: Vendor description
            bucket: Optional S3 bucket associated with vendor
        """
        body: dict[str, Any] = {
            "vendor_id": vendor_id,
            "name": name,
            "description": description,
        }
        if bucket is not None:
            body["bucket"] = bucket
        return await client.post("/vendors", json=body)

    @mcp.tool()
    async def update_vendor(
        vendor_id: str,
        name: str | None = None,
        description: str | None = None,
        bucket: str | None = None,
    ) -> dict:
        """Update a vendor's information.

        Args:
            vendor_id: The vendor identifier
            name: Optional new name
            description: Optional new description
            bucket: Optional new bucket
        """
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if bucket is not None:
            body["bucket"] = bucket
        return await client.put(f"/vendors/{vendor_id}", json=body)

    @mcp.tool()
    async def delete_vendor(vendor_id: str) -> None:
        """Delete a vendor.

        Args:
            vendor_id: The vendor identifier
        """
        await client.delete(f"/vendors/{vendor_id}")
