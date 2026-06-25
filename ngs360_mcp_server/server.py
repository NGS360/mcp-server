"""NGS360 MCP Server - Main entry point."""

from mcp.server.fastmcp import FastMCP

from ngs360_mcp_server.client import NGS360Client
from ngs360_mcp_server.wes_client import WESClient
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
    mcp = FastMCP(
        "NGS360 API",
        instructions=(
            "MCP server for the NGS360 bioinformatics platform API. "
            "Provides tools for managing sequencing runs, projects, samples, "
            "files, batch jobs, workflows, pipelines, QC metrics, vendors, "
            "settings, and platforms. Also provides GA4GH Workflow Execution "
            "Service (WES) tools for submitting and monitoring workflow runs. "
            "NGS360 tools communicate with the NGS360 REST API backend. "
            "WES tools (prefixed with wes_) communicate with a separate "
            "GA4GH WES API service."
        ),
    )

    client = NGS360Client()
    wes_client = WESClient()

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
    """Run the MCP server."""
    mcp = create_server()
    mcp.run()


if __name__ == "__main__":
    main()
