# StarSkill MCP Server

StarSkill provides a local `stdio` MCP server for its auditable astronomy
workflows. The server calls the existing Python domain functions directly; it
does not shell out to the CLI.

## Install

Use Python 3.11 or later and install the project from the repository root:

```bash
python -m pip install -e ".[dev]"
```

The `mcp==1.28.1` dependency and the `starskill-mcp` console entry point are
installed with the project.

## Codex Configuration

Add this server to the MCP client configuration. Substitute the absolute paths
for this checkout and its virtual environment:

```toml
[mcp_servers.starskill]
command = "/absolute/path/to/starskill/.venv/bin/python"
args = ["-m", "starskill.mcp_server"]
cwd = "/absolute/path/to/starskill"

[mcp_servers.starskill.env]
STARSKILL_RUNS_DIR = "/absolute/path/to/starskill/runs/mcp"
STARSKILL_TARGET_CACHE_DIR = "/absolute/path/to/starskill/cache/targets"
STARSKILL_IMAGE_CACHE_DIR = "/absolute/path/to/starskill/cache/sdss"
```

The server uses only standard input/output for MCP messages. Do not run it as
an HTTP service without adding authentication and request limits.

## Tools

| Tool | Purpose |
| --- | --- |
| `validate_observation_task` | Validate an observation-plan payload before external queries. |
| `resolve_astronomy_target` | Resolve a target through SIMBAD and reuse validated cache records. |
| `plan_observation` | Run the complete observation workflow and produce its audit bundle. |
| `calculate_moon_jupiter_relationship` | Calculate the apparent Moon-Jupiter angular relationship. |
| `fetch_m51_sdss_image` | Fetch the bounded SDSS DR18 M51 image and preserve provenance. |

`plan_observation`, `calculate_moon_jupiter_relationship`, and
`fetch_m51_sdss_image` create a unique server-owned run directory. Clients
cannot supply output or cache paths. Each successful result includes resource
URIs such as:

```text
starskill://runs/20260723T080000Z-observation-0123456789ab/manifest
starskill://runs/20260723T080000Z-observation-0123456789ab/report
```

The resource template exposes only a fixed allowlist of text artifacts:
`manifest`, `result`, `report`, `review-checklist`, `target`, `ephemeris`,
`visibility`, `relationship`, `relationship-table`, and `image-metadata`.

## Scientific Boundaries

Observation windows are geometry-based candidates. They do not establish
weather, clouds, horizon obstruction, equipment suitability, or observation
safety. SIMBAD and SDSS outages are returned as structured failures; the
server does not invent coordinates, images, cache hits, or a successful run.
