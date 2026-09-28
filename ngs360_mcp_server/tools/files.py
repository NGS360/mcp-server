"""MCP tools for the Files API."""

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from ngs360_mcp_server.client import NGS360Client


def register_files_tools(mcp: FastMCP, client: NGS360Client) -> None:
    """Register all file-related tools with the MCP server."""

    @mcp.tool()
    async def create_file_record(
        uri: str,
        project_id: str | None = None,
        sequencing_run_id: str | None = None,
        qcrecord_id: str | None = None,
        pipeline_id: str | None = None,
        original_filename: str | None = None,
        size: int | None = None,
        source: str | None = None,
        created_by: str | None = None,
        storage_backend: str | None = None,
        samples: list[dict[str, str]] | None = None,
        hashes: dict[str, str] | None = None,
        tags: dict[str, str] | None = None,
    ) -> dict:
        """Create a new file record (external reference).

        At least one entity association is required.

        Args:
            uri: File location (s3://, file://, etc.)
            project_id: Project business key (string)
            sequencing_run_id: SequencingRun UUID
            qcrecord_id: QCRecord UUID
            pipeline_id: Pipeline UUID
            original_filename: Original filename before renaming
            size: File size in bytes
            source: Origin of file record
            created_by: User identifier
            storage_backend: Storage type (LOCAL, S3, AZURE, GCS)
            samples: Sample associations [{"sample_name": "S1", "role": "tumor"}]
            hashes: Hash values {"md5": "abc...", "sha256": "def..."}
            tags: Key-value metadata {"type": "alignment", "format": "bam"}
        """
        body: dict[str, Any] = {"uri": uri}
        if project_id is not None:
            body["project_id"] = project_id
        if sequencing_run_id is not None:
            body["sequencing_run_id"] = sequencing_run_id
        if qcrecord_id is not None:
            body["qcrecord_id"] = qcrecord_id
        if pipeline_id is not None:
            body["pipeline_id"] = pipeline_id
        if original_filename is not None:
            body["original_filename"] = original_filename
        if size is not None:
            body["size"] = size
        if source is not None:
            body["source"] = source
        if created_by is not None:
            body["created_by"] = created_by
        if storage_backend is not None:
            body["storage_backend"] = storage_backend
        if samples is not None:
            body["samples"] = samples
        if hashes is not None:
            body["hashes"] = hashes
        if tags is not None:
            body["tags"] = tags
        return await client.post("/files", json=body)

    @mcp.tool()
    async def get_file(file_id: str) -> dict:
        """Get file metadata by UUID.

        Args:
            file_id: The file UUID
        """
        return await client.get(f"/files/{file_id}")

    @mcp.tool()
    async def list_files(
        uri: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        include_archived: bool = False,
        page: int = 1,
        per_page: int = 100,
    ) -> dict:
        """List or search files.

        Args:
            uri: Filter by URI (returns latest version)
            entity_type: Filter by entity type (PROJECT, SEQUENCING_RUN, SAMPLE, QCRECORD, PIPELINE)
            entity_id: Filter by entity ID (requires entity_type)
            include_archived: Include archived files
            page: Page number
            per_page: Items per page
        """
        params: dict[str, Any] = {
            "include_archived": include_archived,
            "page": page,
            "per_page": per_page,
        }
        if uri:
            params["uri"] = uri
        if entity_type:
            params["entity_type"] = entity_type
        if entity_id:
            params["entity_id"] = entity_id
        return await client.get("/files", params=params)

    @mcp.tool()
    async def get_file_versions(file_id: str) -> dict:
        """Get all versions of a file.

        Args:
            file_id: The file UUID (any version)
        """
        return await client.get(f"/files/{file_id}/versions")

    @mcp.tool()
    async def update_file(
        file_id: str,
        uri: str | None = None,
        original_filename: str | None = None,
        size: int | None = None,
        source: str | None = None,
        created_by: str | None = None,
        storage_backend: str | None = None,
    ) -> dict:
        """Update a file record (superuser only).

        Only provided fields are updated.

        Args:
            file_id: The file UUID
            uri: New URI
            original_filename: New original filename
            size: New file size
            source: New source
            created_by: New creator
            storage_backend: New storage backend
        """
        body: dict[str, Any] = {}
        if uri is not None:
            body["uri"] = uri
        if original_filename is not None:
            body["original_filename"] = original_filename
        if size is not None:
            body["size"] = size
        if source is not None:
            body["source"] = source
        if created_by is not None:
            body["created_by"] = created_by
        if storage_backend is not None:
            body["storage_backend"] = storage_backend
        return await client.patch(f"/files/{file_id}", json=body)

    @mcp.tool()
    async def delete_file(file_id: str) -> None:
        """Delete a file record and all associated data (superuser only, irreversible).

        Args:
            file_id: The file UUID
        """
        await client.delete(f"/files/{file_id}")

    @mcp.tool()
    async def browse_s3(uri: str) -> dict:
        """Browse files and folders at an S3 URI.

        Args:
            uri: S3 URI to list (e.g., s3://bucket/folder/)
        """
        return await client.get("/files/list", params={"uri": uri})

    @mcp.tool()
    async def upload_file(
        local_path: str,
        project_id: str,
        relative_path: str,
        filename: str | None = None,
    ) -> dict:
        """Upload a local file to NGS360 and create its file record.

        POSTs multipart/form-data to /files/upload. The API server writes
        the bytes to its configured storage backend, then creates a
        File row and returns it (including the new file id).

        Path is on the MCP server's local filesystem — under stdio
        transport that's the user's own machine, so a path like
        "/tmp/wgs.packed.cwl" refers to the caller's local file.

        Under remote MCP transport (streamable-http) this tool cannot
        be used — ``local_path`` resolves on the deployed server host,
        not the caller's machine. Instead, guide the user to run the
        equivalent curl themselves and use the returned file id:

            export NGS360_API_ENDPOINT=<NGS360 API base URL, ending in /api/v1>
            export NGS360_AUTH_TOKEN=<their bearer token>

            curl -s -X POST "$NGS360_API_ENDPOINT/files/upload" \\
              -H "Authorization: Bearer $NGS360_AUTH_TOKEN" \\
              -F "filename=<name>" \\
              -F "relative_path=<path prefix within the project>" \\
              -F "project_id=<project id>" \\
              -F "content=@<local-path-to-file>"

        The response JSON has an ``id`` field — that's the file id to
        hand to whatever tool consumes it next.

        Callers that want the timestamped filename convention used by
        register_ngs360_workflow.sh (avoiding accidental overwrites on
        re-run) should pass the timestamp themselves via ``filename``;
        this tool does not modify the name so a caller uploading a
        specific artifact name gets exactly what they asked for.

        Args:
            local_path: Path to the file on the MCP server's filesystem.
            project_id: Project business key (e.g. "P-XXXXXXXX-XXXX")
                that scopes the upload.
            relative_path: Path prefix within the project. Workflow
                registration uses "workflow_definition_file".
            filename: Name to record on the server side. Defaults to
                ``basename(local_path)``.
        """
        if not os.path.isfile(local_path):
            raise ValueError(f"local file not found: {local_path}")
        upload_name = filename or os.path.basename(local_path)
        with open(local_path, "rb") as fh:
            content = fh.read()
        return await client.post_form(
            "/files/upload",
            data={
                "filename": upload_name,
                "relative_path": relative_path,
                "project_id": project_id,
            },
            files={"content": (upload_name, content)},
        )

    @mcp.tool()
    async def get_file_download_url(path: str) -> dict:
        """Get a temporary presigned URL to download a file from S3.

        Returns a time-limited URL that the caller can use to download the file
        directly from S3 (the API does not stream file bytes). The URL is a
        bearer credential — treat it as secret and use it before it expires.

        Args:
            path: S3 URI of the file (e.g., s3://bucket/path/file.bam)
        """
        return await client.get("/files/download-url", params={"path": path})
