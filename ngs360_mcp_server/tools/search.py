"""MCP tools for the Search API."""

from mcp.server.fastmcp import FastMCP

from ngs360_mcp_server.client import NGS360Client


def register_search_tools(mcp: FastMCP, client: NGS360Client) -> None:
    """Register all search-related tools with the MCP server."""

    @mcp.tool()
    async def search(query: str, n_results: int = 5) -> dict:
        """Search across all indices (projects, runs, samples) using OpenSearch.

        Args:
            query: Search query string
            n_results: Number of results to return per index
        """
        params = {"query": query, "n_results": n_results}
        return await client.get("/search", params=params)
