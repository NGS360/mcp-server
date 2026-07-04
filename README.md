# NGS360 MCP Server

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that exposes the NGS360 REST API as tools for AI assistants.

## Overview

This MCP server wraps the NGS360 bioinformatics platform API, providing tools for:

| Domain | Tools | Description |
|--------|-------|-------------|
| **Runs** | 14 tools | Sequencing run CRUD, sample sheets, metrics, demultiplexing |
| **Jobs** | 6 tools | AWS Batch job submission, monitoring, and logs |
| **Projects** | 11 tools | Project CRUD, samples, pipeline actions, vendor ingestion |
| **Files** | 7 tools | File record management, S3 browsing |
| **Search** | 1 tool | Cross-index search (projects, runs, samples) |
| **Workflows** | 11 tools | Workflow identity, versions, aliases, deployments |
| **Pipelines** | 5 tools | Pipeline CRUD, workflow associations |
| **QC Metrics** | 5 tools | QC record creation, search, retrieval |
| **Vendors** | 5 tools | Vendor CRUD |
| **Settings** | 3 tools | Application settings management |
| **Platforms** | 3 tools | Workflow execution platform registry |
| **Manifest** | 2 tools | Manifest retrieval and validation |
| **WES** | 8 tools | GA4GH Workflow Execution Service (run/monitor workflows) |

## Installation

```bash
cd mcp-server
pip install -e .
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
cd mcp-server
uv pip install -e .
```

## Configuration

The server uses environment variables for configuration:

| Variable | Default | Description |
|----------|---------|-------------|
| `NGS360_API_URL` | `http://localhost:8000` | Base URL of the NGS360 API |
| `NGS360_API_TOKEN` | *(empty)* | Bearer token for NGS360 authentication |

## Usage

### Running directly

```bash
ngs360-mcp-server
```

### With Claude Desktop

Add to your Claude Desktop configuration (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "ngs360": {
      "command": "ngs360-mcp-server",
      "env": {
        "NGS360_API_URL": "https://your-ngs360-api.example.com",
        "NGS360_API_TOKEN": "your-bearer-token",
      }
    }
  }
}
```

### With VS Code / Roo

Add to your MCP settings:

```json
{
  "mcpServers": {
    "ngs360": {
      "command": "ngs360-mcp-server",
      "env": {
        "NGS360_API_URL": "https://your-ngs360-api.example.com",
        "NGS360_API_TOKEN": "your-bearer-token",
      }
    }
  }
}
```

## Development

### Project Structure

```
mcp-server/
├── pyproject.toml
├── README.md
└── ngs360_mcp_server/
    ├── __init__.py
    ├── client.py          # HTTP client wrapper for the NGS360 API
    ├── server.py          # MCP server entry point
    └── tools/
        ├── __init__.py
        ├── runs.py        # Sequencing run tools
        ├── jobs.py        # Batch job tools
        ├── projects.py    # Project & sample tools
        ├── files.py       # File management tools
        ├── search.py      # Cross-index search tools
        ├── workflows.py   # Workflow management tools
        ├── pipelines.py   # Pipeline management tools
        ├── qcmetrics.py   # QC metrics tools
        ├── vendors.py     # Vendor management tools
        ├── settings.py    # Settings tools
        ├── platforms.py   # Platform registry tools
        ├── manifest.py    # Manifest tools
```

### Testing with MCP Inspector

```bash
npx @modelcontextprotocol/inspector ngs360-mcp-server
```

### Adding New Tools

1. Create or edit a file in `ngs360_mcp_server/tools/`
2. Define a `register_*_tools(mcp, client)` function
3. Register it in `ngs360_mcp_server/server.py`

Each tool is a decorated async function:

```python
@mcp.tool()
async def my_new_tool(param1: str, param2: int = 10) -> dict:
    """Tool description shown to the AI assistant.

    Args:
        param1: Description of param1
        param2: Description of param2
    """
    return await client.get("/my/endpoint", params={"p": param1})
```

## API Coverage

This MCP server covers the full NGS360 API surface at `/api/v1/*`:

- `POST/GET /runs` — Create and list sequencing runs
- `GET/PUT /runs/{run_id}` — Get/update a run
- `GET /runs/{run_id}/samplesheet` — Sample sheet
- `GET /runs/{run_id}/metrics` — Demux metrics
- `GET/POST /runs/demultiplex` — Demux workflows
- `POST/GET/DELETE /runs/{run_id}/samples` — Sample associations
- `POST/GET /jobs` — Submit and list batch jobs
- `GET/PUT /jobs/{job_id}` — Get/update job
- `GET /jobs/{job_id}/log` — Job logs
- `POST/GET /projects` — Create and list projects
- `GET/PUT/PATCH /projects/{project_id}` — Project CRUD
- `POST/GET /projects/{project_id}/samples` — Project samples
- `POST /projects/{project_id}/actions/submit` — Pipeline submission
- `POST/GET /files` — File record management
- `GET/PATCH/DELETE /files/{file_id}` — File operations
- `GET /files/list` — S3 browser
- `GET /search` — Global search
- `POST/GET /workflows` — Workflow identity
- `POST/GET /workflows/{id}/versions` — Versions
- `PUT/GET/DELETE /workflows/{id}/aliases` — Aliases
- `POST/GET/DELETE /workflows/.../deployments` — Deployments
- `POST/GET /pipelines` — Pipeline CRUD
- `POST/DELETE /pipelines/{id}/workflows` — Workflow membership
- `POST/GET/DELETE /qcmetrics` — QC records
- `GET/POST /qcmetrics/search` — QC search
- `POST/GET/PUT/DELETE /vendors` — Vendor management
- `GET/PUT /settings` — Application settings
- `POST/GET /platforms` — Platform registry
- `GET/POST /manifest` — Manifest operations

### GA4GH WES API (`/ga4gh/wes/v1/*`)

- `GET /service-info` — WES service capabilities
- `GET /runs` — List workflow runs
- `POST /runs` — Submit a workflow run
- `GET /runs/{run_id}` — Full run log
- `GET /runs/{run_id}/status` — Run state
- `POST /runs/{run_id}/cancel` — Cancel a run
- `GET /runs/{run_id}/tasks` — List tasks for a run
- `GET /runs/{run_id}/tasks/{task_id}` — Get task details
