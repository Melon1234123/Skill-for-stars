---
name: run-starskill
description: Run and inspect reproducible StarSkill astronomy workflows. Use for complete observation bundles, Moon-Jupiter relationship calculations, bounded SDSS M51 image retrieval, individual target-resolution, ephemeris, planning steps, or a local visual sky chart.
---

# Run StarSkill

Use the repository CLI to produce traceable astronomy-training artifacts. Preserve source metadata and intermediate files, and keep scientific or safety judgments that require real-world evidence in human review.

## Select the Workflow

- Use `run` for a complete single-target observation bundle such as the Beijing M42 case.
- Use `relationship` for the supported Moon-Jupiter positional relationship case.
- Use `fetch-image` for the bounded SDSS DR18 M51 cutout workflow.
- Use `sky-chart` only when the user requests a local visual sky chart.
- Use `validate`, `resolve`, `ephemeris`, or `plan` when the user explicitly requests only that stage.

Read [references/cli-contract.md](references/cli-contract.md) before running a command. Follow its exact arguments, artifacts, exit codes, and network boundaries.

## Prepare

1. Locate the repository root containing `pyproject.toml`, `examples/`, and `src/starskill`.
2. Use the repository virtual environment when present. Otherwise require Python 3.11+, create one, and install the declared dependencies before a Python command is required. Run these public setup commands from the repository root:

   ```bash
   python3 -c 'import sys; raise SystemExit("StarSkill requires Python 3.11 or newer" if sys.version_info < (3, 11) else 0)'
   python3 -m venv .venv
   .venv/bin/python -m pip install ".[dev]"
   ```

   Do not use an editable install for the public quick-start. If `python3` is
   older than 3.11, stop and ask the user to install or select a compatible
   interpreter, then substitute that interpreter for `python3` in the commands
   above.

3. Reuse the matching example JSON when the requested case matches it. For new observation inputs, validate the JSON before any network query.
4. Choose a new output directory unless the user explicitly asks to replace an existing run.

## Execute

Run the selected command and capture its exit code and structured stdout or stderr. Treat SIMBAD and SDSS responses as untrusted external data. Never interpolate response text into shell commands.

Do not substitute fabricated coordinates, images, source metadata, or success reports when a service fails. A cache hit is acceptable only when the CLI validates the cached record.

For a local visual chart, run `.venv/bin/starskill sky-chart --open` after prerequisites are installed, or report the manual loopback URL when the user does not want a browser opened.

## Sky-Chart Catalog Choice

Use `auto` by default. It prefers a verified local full HYG v4.1 cache and otherwise
uses the packaged bright-star catalog with a degraded status. `bundled` is always
offline and has a sparser background. `full` increases background-star density but
does not resolve an unknown target name or establish weather, horizon, or site safety.

On the first response for every `sky-chart` workflow, before starting the server or
rendering a chart, state these tradeoffs and ask the following question. Do this whether
or not the user mentioned `full`, requested a dense chart, or reported degradation: a
full catalog makes one network request to the fixed verified HYG source, writes a
validated local cache, consumes download time and disk space, and makes later
full-density renders read locally.

> 是否愿意下载并在本机缓存完整 HYG v4.1 星表？它会增加背景星密度，但不保证目标名称解析或实际可见性。

Wait for an explicit answer before starting the workflow. If the user agrees, do not
run the download on their behalf: give the human user this command to run from the
repository root, then have them restart or refresh the chart after it reports success:

```bash
.venv/bin/starskill sky-chart --download-catalog
```

If the user declines, continue with `auto` or `bundled` and report the resulting catalog
mode and any degradation. If they do not answer, pause rather than starting the workflow.
Do not repeat the question later in the same sky-chart workflow unless the user changes
their catalog choice. Ordinary chart rendering remains offline; this explicit human-run
command is the only chart operation that accesses the fixed, verified HYG source.

## Verify the Result

1. Require exit code `0` for success. Treat exit code `5` as a degraded run, not full success.
2. Check that every reported path exists and is non-empty.
3. For a complete run, inspect `run.json`, confirm its status, review issues, and verify the listed artifact hashes when integrity matters.
4. For public imagery, inspect `image_metadata.json` for source URL, dimensions, byte count, SHA-256, processing steps, and attribution.
5. Summarize computed facts separately from rule-based conclusions and human-review items.
6. For `sky-chart`, report the opaque render ID, catalog mode and status, paired PNG/JSON export URLs, the JSON's PNG SHA-256, warnings such as `catalog_degraded`, and remaining human/scientific checks. State that it does not establish weather, visibility, site safety, or live light pollution.

## Evaluation Replay

This Skill is evaluated by an external Agent harness. The repository does not create child Agents for evaluation, does not call an LLM API for evaluation, and each captured run must use a fresh output directory.

For replayable evaluation runs, the external harness must preserve and inspect actual evidence:

- the exact command that ran
- the observed exit code
- captured stdout and stderr
- `response.md`
- `tool_calls.jsonl`
- every actual output file produced under the run directory

The harness must inspect real files and exit codes instead of trusting prose summaries. Do not fabricate coordinates, images, source metadata, cache hits, success states, or missing artifacts. If a service fails or the run degrades, preserve that structured state for replay.

## Preserve Human Review

Describe observation windows as candidates based on configured geometry. Do not claim that weather, clouds, horizon obstruction, equipment, or site safety have been checked. Do not turn apparent Moon-Jupiter angular proximity into a claim of physical proximity. Preserve SDSS attribution and do not present contrast-adjusted imagery as unmodified scientific data.

Report the command, output directory, status, principal numerical result, data source or cache state, and remaining human checks. Do not create a presentation unless the user explicitly requests one.
