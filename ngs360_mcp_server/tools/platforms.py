"""MCP tools for the Platforms API."""

from mcp.server.fastmcp import FastMCP

from ngs360_mcp_server.client import NGS360Client


def register_platforms_tools(mcp: FastMCP, client: NGS360Client) -> None:
    """Register all platform-related tools with the MCP server."""

    @mcp.tool()
    async def list_platforms() -> list:
        """List all registered workflow execution platforms."""
        return await client.get("/platforms")

    @mcp.tool()
    async def get_platform(name: str) -> dict:
        """Get a platform by name.

        Args:
            name: Platform name (e.g., Arvados, SevenBridges)
        """
        return await client.get(f"/platforms/{name}")

    @mcp.tool()
    async def create_platform(name: str) -> dict:
        """Create a new workflow execution platform.

        Args:
            name: Platform name (e.g., Arvados, SevenBridges)
        """
        return await client.post("/platforms", json={"name": name})
