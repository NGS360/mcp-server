"""MCP tools for the Auth API."""

from mcp.server.fastmcp import FastMCP

from ngs360_mcp_server.client import NGS360Client


def register_auth_tools(mcp: FastMCP, client: NGS360Client) -> None:
    """Register all auth-related tools with the MCP server."""

    @mcp.tool()
    async def get_current_user() -> dict:
        """Get the profile of the authenticated user (whoami).

        Returns the user the current credential resolves to, including
        username, email, full name, and flags such as is_active,
        is_verified, and is_superuser. Useful for verifying that a token
        is valid and to see who a call will be attributed to.
        """
        return await client.get("/auth/me")
