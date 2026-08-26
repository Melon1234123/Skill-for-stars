# StarSkill Answer Templates

Every user-facing answer follows the same five-part structure, in this order:

1. **Conclusion** — one or two sentences naming the place, local time, target,
   and the principal result. No file paths and no implementation detail.
2. **Key numbers** — a short table or list of the numerical facts the user
   acts on. Keep computed facts separate from rule-based conclusions.
3. **Visual** — embed the verified raster artifact when the workflow produced
   one. Never invent a figure for a workflow that has none; give the compact
   table instead.
4. **Evidence** — command, output directory, envelope `status`, data source
   or cache state, and the artifact hash when integrity matters.
5. **Human review** — the envelope's `human_review` items that remain open,
   stated as unresolved checks, never as completed verifications.

Read the machine facts from the command's uniform envelope (`summary`,
`artifacts`, `sources`, `human_review`) rather than re-deriving them from
prose. A `degraded` envelope must be reported as degraded, naming the
unavailable evidence; never present a degraded run as full success.

## Per-Workflow Guidance

### `run` / `plan`

- Conclusion: whether a candidate window exists tonight and when.
- Key numbers: window start/end in local time, peak target altitude, limiting
  Sun or Moon condition.
- Visual: embed the visibility PNG; explain the altitude curve, thresholds,
  and shaded windows.
- Human review: weather, horizon obstruction, equipment, and site safety are
  unchecked geometry caveats.

### `relationship`

- Conclusion: the minimum apparent separation and when it occurs.
- Key numbers: minimum/maximum separation in degrees, sample count, both
  targets' motion kinds (dynamic versus fixed ICRS).
- Visual: none is produced; show a compact table of a few sample times.
- Always state that angular separation is an apparent sky angle, not physical
  distance.

### `resolve` / `resolve-target`

- Conclusion: the canonical name and where the answer came from
  (SIMBAD, cache, built-in ephemeris, or user coordinates).
- Key numbers: ICRS RA/Dec in degrees, object type when known.
- Visual: none; a one-row table is enough.

### `ephemeris`

- Conclusion: the target's altitude behavior over the requested range.
- Key numbers: sample count, highest altitude and its local time, Sun/Moon
  context at that moment.
- Visual: none is produced by this stage; point to `plan` for the curve.

### `fetch-image`

- Conclusion: which target and survey the image shows.
- Key numbers: pixel scale, dimensions, byte count.
- Visual: embed the generated display PNG; identify the source, the listed
  processing steps, and the attribution. Do not call it raw scientific data:
  the display image is contrast-adjusted.

### `sky-chart`

- Conclusion: what the sky looks like from the location at the time.
- Visual: embed the saved PNG; the center is the zenith, the outer circle is
  the horizon, and the cardinal labels set direction. Call out the most useful
  objects or constellations by direction and altitude when the data supports
  it.
- Evidence: opaque render ID, catalog mode and status, warnings such as
  `catalog_degraded`, and the PNG SHA-256 matched against the JSON export.

### `conditions`

- Conclusion: the forecast trend across the requested window.
- Key numbers: cloud cover range, precipitation, wind, visibility for the key
  hours.
- State availability (`fresh`, `cached`, `unavailable`) and that the forecast
  is planning evidence, not a go/no-go safety decision.

### `recommend`

- Conclusion: the graded windows for tonight and the dominant reason for each
  grade.
- Key numbers: each window's start/end, grade, and the weather or light
  pollution values behind the grade.
- Visual: embed the pipeline's visibility PNG from the same output directory.
- Human review: repeat the recommendation's `human_review` list; grades are
  conservative rule outputs, not observing decisions.

### `apod`

- Conclusion: the featured title and date.
- Evidence: availability and cache state; preserve NASA attribution and any
  copyright notice. Never display the media without its attribution.

### `stellarium-sync`

- Conclusion: whether the local Stellarium instance now shows the requested
  target, location, and time.
- Key numbers: the completed operations list.
- On failure, report the partial operations record and that the local
  RemoteControl endpoint was unreachable; do not retry against a non-local
  URL.

### `validate`

- Conclusion: whether the task is valid and its task type.
- On failure, list each validation detail with its input location so the user
  can fix the JSON directly.
