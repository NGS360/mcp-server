"""MCP tools for the Settings API."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ngs360_mcp_server.client import NGS360Client


def register_settings_tools(mcp: FastMCP, client: NGS360Client) -> None:
    """Register all settings-related tools with the MCP server."""

    @mcp.tool()
    async def get_settings_by_tag(tag_key: str, tag_value: str) -> list:
        """Get settings filtered by a tag key-value pair.

        Args:
            tag_key: Tag key to filter by (e.g., 'category')
            tag_value: Tag value to filter by (e.g., 'storage')
        """
        params = {"tag_key": tag_key, "tag_value": tag_value}
        return await client.get("/settings", params=params)

    @mcp.tool()
    async def get_setting(key: str) -> dict:
        """Get a specific setting by key.

        Args:
            key: The setting key identifier
        """
        return await client.get(f"/settings/{key}")

    @mcp.tool()
    async def update_setting(
        key: str,
        value: str | None = None,
        name: str | None = None,
        description: str | None = None,
        tags: list[dict[str, str]] | None = None,
    ) -> dict:
        """Update a setting (value, name, description, tags).

        The key itself cannot be changed.

        Args:
            key: The setting key
            value: Optional new value
            name: Optional new display name
            description: Optional new description
            tags: Optional new tags list [{"key": "category", "value": "storage"}]
        """
        body: dict[str, Any] = {}
        if value is not None:
            body["value"] = value
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if tags is not None:
            body["tags"] = tags
        return await client.put(f"/settings/{key}", json=body)
