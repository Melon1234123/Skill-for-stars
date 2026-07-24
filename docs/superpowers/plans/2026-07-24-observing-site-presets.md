# Observing-Site Presets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a sky-chart observing site internally consistent by letting a local preset fill its label, coordinates, and timezone while preserving manual overrides.

**Architecture:** Keep the preset catalog in the packaged single-page application because it is a small, offline UI concern. The form continues to submit the existing `SkyChartRequest.observer` shape; no API or astronomy calculation changes are required.

**Tech Stack:** FastAPI packaged HTML, browser JavaScript, pytest.

## Global Constraints

- Use only bundled site data; do not add a geocoding service, network request, permission prompt, or dependency.
- A preset updates location name, longitude, latitude, and IANA timezone together.
- An edit to any observer field changes the select state to manual without overwriting the edit.
- Keep the current form IDs and request JSON contract.

---

### Task 1: Specify and Test Site Binding

**Files:**
- Modify: `tests/test_web_api.py`
- Modify: `src/starskill/static/sky_chart.html`

**Interfaces:**
- Consumes: the packaged root page returned by `create_web_app`.
- Produces: a `site-preset` select, local preset data, and manual-state behavior in the page script.

- [x] **Step 1: Write the failing test**

```python
def test_page_declares_local_observing_site_presets(
    tmp_path: Path, rendered_chart: RenderedSkyChart
) -> None:
    page = make_client(tmp_path, rendered_chart).get("/").text
    assert 'id="site-preset"' in page
    assert 'value="beijing"' in page
    assert 'value="manual"' in page
    assert "OBSERVING_SITE_PRESETS" in page
    assert "locationNameInput, longitudeInput, latitudeInput, timezoneInput" in page
```

- [x] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest -q tests/test_web_api.py -k observing_site_presets`

Expected: FAIL because the page has no site-preset control or observer-binding script.

- [x] **Step 3: Write minimal implementation**

```javascript
const OBSERVING_SITE_PRESETS = Object.freeze({
  beijing: Object.freeze({ locationName: "北京", longitude: "116.4074", latitude: "39.9042", timezone: "Asia/Shanghai" }),
  shanghai: Object.freeze({ locationName: "上海", longitude: "121.4737", latitude: "31.2304", timezone: "Asia/Shanghai" }),
  guangzhou: Object.freeze({ locationName: "广州", longitude: "113.2644", latitude: "23.1291", timezone: "Asia/Shanghai" })
});

function applySitePreset(key) {
  const preset = OBSERVING_SITE_PRESETS[key];
  if (!preset) return;
  locationNameInput.value = preset.locationName;
  longitudeInput.value = preset.longitude;
  latitudeInput.value = preset.latitude;
  timezoneInput.value = preset.timezone;
  resetTimeWindow();
}
function markManualSite() { sitePreset.value = "manual"; }
```

- [x] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest -q tests/test_web_api.py -k observing_site_presets`

Expected: PASS.

- [x] **Step 5: Verify the page behavior**

Run the loopback server, select Shanghai, verify all observer values change together, then edit longitude and verify the select shows manual before rendering a chart.

- [ ] **Step 6: Commit and push only this task's files**

```bash
git add src/starskill/static/sky_chart.html tests/test_web_api.py docs/superpowers/plans/2026-07-24-observing-site-presets.md
git commit -m "feat: bind sky chart observing site presets"
git push -u origin codex/starskill-mcp-service
```
