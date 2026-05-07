"""MCP tools for the Manifest API."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ngs360_mcp_server.client import NGS360Client


def register_manifest_tools(mcp: FastMCP, client: NGS360Client) -> None:
    """Register all manifest-related tools with the MCP server."""

    @mcp.tool()
    async def get_latest_manifest(s3_path: str) -> str:
        """Get the latest manifest file path from an S3 bucket.

        Searches recursively for CSV files containing 'manifest' in their name.

        Args:
            s3_path: S3 path to search (e.g., s3://bucket-name/path/to/manifests)
        """
        return await client.get("/manifest", params={"s3_path": s3_path})

    @mcp.tool()
    async def validate_manifest(
        manifest_uri: str,
        files_uri: str | None = None,
        manifest_version: str | None = None,
        post_to_api: bool = False,
    ) -> dict:
        """Validate a manifest CSV file from S3.

        Checks required fields, data format, value constraints,
        and file existence.

        Args:
            manifest_uri: S3/GS path to the manifest CSV file
            files_uri: S3/GS path where files in manifest are located
            manifest_version: Manifest version to validate against (e.g., 'DTS12.1')
            post_to_api: If true, post samples to API after successful validation
        """
        params: dict[str, Any] = {"manifest_uri": manifest_uri}
        if files_uri:
            params["files_uri"] = files_uri
        if manifest_version:
            params["manifest_version"] = manifest_version
        if post_to_api:
            params["post_to_api"] = post_to_api
        return await client.post("/manifest/validate", params=params)
