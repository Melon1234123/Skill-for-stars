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
STARSKILL_WEATHER_CACHE_DIR = "/absolute/path/to/starskill/cache/weather"
STARSKILL_LIGHT_POLLUTION_SNAPSHOT = "/absolute/path/to/starskill/data/black_marble_snapshot.json"
STARSKILL_NASA_CACHE_DIR = "/absolute/path/to/starskill/cache/nasa"
```

The server uses only standard input/output for MCP messages. Do not run it as
an HTTP service without adding authentication and request limits.

To enable NASA APOD, configure `STARSKILL_NASA_API_KEY` only in the local
server process environment. It is used solely to configure the NASA provider;
it is not returned by tools, written to run resources, or included in examples.
Without it, `get_nasa_feature` returns an unavailable result with provenance.

## Tools

| Tool | Purpose |
| --- | --- |
| `validate_observation_task` | Validate an observation-plan payload before external queries. |
| `resolve_astronomy_target` | Resolve a target through SIMBAD and reuse validated cache records. |
| `plan_observation` | Run the complete observation workflow and produce its audit bundle. |
| `calculate_moon_jupiter_relationship` | Calculate the apparent Moon-Jupiter angular relationship. |
| `fetch_m51_sdss_image` | Fetch the bounded SDSS DR18 M51 image and preserve provenance. |
| `get_observing_conditions` | Fetch Open-Meteo forecast evidence for a validated observer and time range. |
| `recommend_tonight` | Run geometry first, then combine it with weather and static light-pollution evidence. |
| `get_nasa_feature` | Fetch NASA APOD metadata and provenance for an optional ISO date. |
| `sync_stellarium` | Synchronize a validated target, time, and observer with local Stellarium RemoteControl. |

`plan_observation`, `calculate_moon_jupiter_relationship`, and
`fetch_m51_sdss_image`, and every outreach tool create a unique server-owned
run directory. Clients cannot supply output or artifact paths. Each successful
result includes resource URIs such as:

```text
starskill://runs/20260723T080000Z-observation-0123456789ab/manifest
starskill://runs/20260723T080000Z-observation-0123456789ab/report
```

The resource template exposes only a fixed allowlist of text artifacts:
`manifest`, `result`, `report`, `review-checklist`, `target`, `ephemeris`,
`visibility`, `relationship`, `relationship-table`, `image-metadata`,
`conditions`, `recommendation`, `nasa-feature`, and `stellarium-sync`.

## Scientific Boundaries

Observation windows are geometry-based candidates. They do not establish
weather, clouds, horizon obstruction, equipment suitability, or observation
safety. SIMBAD and SDSS outages are returned as structured failures; the
server does not invent coordinates, images, cache hits, or a successful run.

Weather is a forecast, not a safety decision. The Black Marble value is a
versioned static radiance snapshot, not a current local measurement or Bortle
classification. `recommend_tonight` retains required human review for weather,
local horizon, equipment, and safety. Stellarium synchronization uses only the
local loopback RemoteControl endpoint at `http://127.0.0.1:8090`; it does not
make the MCP server reachable over the network.
