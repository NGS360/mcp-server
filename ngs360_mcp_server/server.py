"""NGS360 MCP Server - Main entry point."""

import os

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from ngs360_mcp_server.client import NGS360Client

from ngs360_mcp_server.tools.runs import register_runs_tools
from ngs360_mcp_server.tools.jobs import register_jobs_tools
from ngs360_mcp_server.tools.projects import register_projects_tools
from ngs360_mcp_server.tools.files import register_files_tools
from ngs360_mcp_server.tools.search import register_search_tools
from ngs360_mcp_server.tools.workflows import register_workflows_tools
from ngs360_mcp_server.tools.pipelines import register_pipelines_tools
from ngs360_mcp_server.tools.qcmetrics import register_qcmetrics_tools
from ngs360_mcp_server.tools.vendors import register_vendors_tools
from ngs360_mcp_server.tools.settings import register_settings_tools
from ngs360_mcp_server.tools.platforms import register_platforms_tools
from ngs360_mcp_server.tools.manifest import register_manifest_tools
from ngs360_mcp_server.tools.wes import register_wes_tools


def create_server() -> FastMCP:
    """Create and configure the MCP server with all NGS360 tools."""
    # HTTP bind config for the streamable-http transport.
    # Read explicitly from env because pydantic's FASTMCP_* auto-read is not
    # honored in the installed mcp version. Defaults are container-correct:
    # bind all interfaces on 8000 so the load balancer can reach the task, and
    # run stateless (required behind a multi-replica load balancer).
    def _env_bool(name: str, default: bool) -> bool:
        val = os.environ.get(name)
        return default if val is None else val.strip().lower() in ("1", "true", "yes")

    mcp = FastMCP(
        "NGS360 API",
        instructions=(
            "MCP server for the NGS360 bioinformatics platform API. "
            "Provides tools for managing sequencing runs, projects, samples, "
            "files, batch jobs, workflows, pipelines, QC metrics, vendors, "
            "settings, and platforms. Also provides GA4GH Workflow Execution "
            "Service (WES) tools for submitting and monitoring workflow runs. "
            "WES tools are prefixed with wes_."
        ),
        host=os.environ.get("FASTMCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("FASTMCP_PORT", "8000")),
        stateless_http=_env_bool("FASTMCP_STATELESS_HTTP", True),
    )

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> JSONResponse:
        """Liveness probe for the AI Hub load balancer."""
        return JSONResponse({"status": "ok"})

    client = NGS360Client()
    wes_client = NGS360Client(path_prefix="/ga4gh/wes/v1")

    # Register all tool groups
    register_runs_tools(mcp, client)
    register_jobs_tools(mcp, client)
    register_projects_tools(mcp, client)
    register_files_tools(mcp, client)
    register_search_tools(mcp, client)
    register_workflows_tools(mcp, client)
    register_pipelines_tools(mcp, client)
    register_qcmetrics_tools(mcp, client)
    register_vendors_tools(mcp, client)
    register_settings_tools(mcp, client)
    register_platforms_tools(mcp, client)
    register_manifest_tools(mcp, client)
    register_wes_tools(mcp, wes_client)

    return mcp


def main() -> None:
    """Run the MCP server.

    Transport is selected via the MCP_TRANSPORT env var, defaulting to "stdio"
    for local use (e.g. MCP Inspector, Claude Desktop). For container
    deployment set MCP_TRANSPORT=streamable-http; the server then serves /mcp and
    /health on FASTMCP_HOST:FASTMCP_PORT (0.0.0.0:8000 in the container, with
    FASTMCP_STATELESS_HTTP=true).
    """
    mcp = create_server()
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
