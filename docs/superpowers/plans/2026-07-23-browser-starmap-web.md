# StarSkill Browser Star Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a loopback browser workspace that embeds Stellarium Web Engine and presents StarSkill's auditable tonight recommendations after a normal clone-and-build workflow.

**Architecture:** Vendor a pinned Stellarium Web Engine revision under AGPL-3.0 and build its JavaScript/WebAssembly assets through its upstream Docker workflow. A React/Vite TypeScript application isolates the raw engine behind one canvas wrapper, calls only the same-origin loopback Web API from the data-and-MCP plan, and keeps evidence visible beside the interactive sky.

**Tech Stack:** Stellarium Web Engine commit `1fa2d3bbb19f66ebb0de6deed3090391497c8047`, Docker, Emscripten, React 19, TypeScript, Vite, Vitest, Playwright.

## Global Constraints

- Complete `2026-07-23-live-outreach-data-and-mcp.md` first; browser calls the `/v1` contracts from that plan.
- Add AGPL-3.0 text and third-party notices before distributing a bundle containing the engine assets.
- The Web app is desktop-first. Fixed controls must not resize when values, errors, or Chinese labels change.
- Browser JavaScript never contains NASA credentials, cache paths, or a desktop Stellarium URL.
- Render fresh, cached, stale, and unavailable provider states with source time. Never display a prior success as current.
- Browser calls only the Web API. It never starts MCP stdio or requests a local RemoteControl endpoint.
- Verify at `1440x960` and `390x844` with Playwright screenshots and nonblank canvas pixel checks.
- A new user can clone into an empty directory and follow README with only declared Python, Node, and Docker prerequisites; browser core must not require an API key, a local cache, private data, absolute paths, or desktop Stellarium.

---

### Task 1: Vendor and verify the Stellarium engine under AGPL-3.0

**Files:**
- Create: `.gitmodules`
- Create: `web/vendor/stellarium-web-engine` (git submodule)
- Create: `LICENSE`
- Create: `web/THIRD_PARTY_NOTICES.md`
- Create: `web/Makefile`
- Create: `web/scripts/verify_engine_assets.mjs`
- Modify: `README.md:1-20`

**Interfaces:**
- Produces `web/vendor/stellarium-web-engine/build/stellarium-web-engine.js` and `.wasm` for Task 3.
- Produces `make -C web engine` and `make -C web verify-engine`.

- [ ] **Step 1: Create a failing engine-asset verifier**

```js
import { access, stat } from 'node:fs/promises';

const files = [
  'vendor/stellarium-web-engine/build/stellarium-web-engine.js',
  'vendor/stellarium-web-engine/build/stellarium-web-engine.wasm',
];

for (const file of files) {
  await access(file);
  if ((await stat(file)).size === 0) throw new Error(`${file} is empty`);
}
console.log('Stellarium engine assets verified');
```

- [ ] **Step 2: Confirm it fails before assets are built**

Run: `node web/scripts/verify_engine_assets.mjs`

Expected: FAIL because the submodule and build artifacts are absent.

- [ ] **Step 3: Add pinned source, license, and build wrapper**

Run `git submodule add --force --name stellarium-web-engine https://github.com/Stellarium/stellarium-web-engine.git web/vendor/stellarium-web-engine`, then run `git -C web/vendor/stellarium-web-engine checkout 1fa2d3bbb19f66ebb0de6deed3090391497c8047`.

Copy `web/vendor/stellarium-web-engine/LICENSE-AGPL-3.0.txt` verbatim to root `LICENSE`. Create `web/THIRD_PARTY_NOTICES.md` with a link to the upstream repository, the exact revision, the AGPL-3.0 license name, and the statement that corresponding browser source is distributed in this repository.

Create this `web/Makefile`:

```make
engine:
	$(MAKE) -C vendor/stellarium-web-engine js-es6

verify-engine:
	node scripts/verify_engine_assets.mjs
```

Update README licensing content to link `LICENSE`, the notices file, and the pinned engine revision.

- [ ] **Step 4: Build and verify assets**

Run: `make -C web engine && make -C web verify-engine`

Expected: `Stellarium engine assets verified` after Docker/Emscripten completes.

- [ ] **Step 5: Commit**

Run `git add .gitmodules web/vendor/stellarium-web-engine LICENSE web/THIRD_PARTY_NOTICES.md web/scripts/verify_engine_assets.mjs web/Makefile README.md`, then create commit `feat: vendor Stellarium web engine under AGPL`.

### Task 2: Scaffold a typed Vite client and narrow Web API boundary

**Files:**
- Create: `web/package.json`
- Create: `web/package-lock.json`
- Create: `web/tsconfig.json`
- Create: `web/vite.config.ts`
- Create: `web/index.html`
- Create: `web/src/main.tsx`
- Create: `web/src/api.ts`
- Create: `web/src/api.test.ts`
- Create: `web/src/types.ts`

**Interfaces:**
- Consumes `POST /v1/recommendations/tonight`, `POST /v1/conditions`, `GET /v1/nasa/apod`, and `POST /v1/stellarium/sync`.
- Produces `StarSkillApi`, `TonightRecommendationResult`, and `ApiError` for Tasks 3-5.

- [ ] **Step 1: Write a failing API-client test**

```ts
it('sends a recommendation request and preserves unavailable state', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ weather_forecast: { source: { availability: 'unavailable' } } }), { status: 200 }));
  const api = new StarSkillApi('http://127.0.0.1:8000', fetcher);
  const result = await api.recommendTonight({ task: validTask });
  expect(fetcher).toHaveBeenCalledWith('http://127.0.0.1:8000/v1/recommendations/tonight', expect.objectContaining({ method: 'POST' }));
  expect(result.weather_forecast.source.availability).toBe('unavailable');
});
```

- [ ] **Step 2: Confirm it fails before project setup**

Run: `npm --prefix web test -- api.test.ts`

Expected: FAIL because the Vite project and `StarSkillApi` are absent.

- [ ] **Step 3: Implement the project and API client**

Install `react@19`, `react-dom@19`, `typescript@5`, `vite@6`, `vitest@3`, `@vitejs/plugin-react@4`, `@playwright/test@1`, and type packages. Add `dev`, `build`, `test`, and `test:e2e` scripts. `src/types.ts` defines only fields rendered in the client, matching public Web API results.

Implement this boundary in `src/api.ts`:

```ts
export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
  }
}

export class StarSkillApi {
  constructor(private readonly baseUrl: string, private readonly fetcher: typeof fetch = fetch) {}

  async recommendTonight(payload: TonightRecommendationRequest): Promise<TonightRecommendationResult> {
    const response = await this.fetcher(`${this.baseUrl}/v1/recommendations/tonight`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new ApiError(response.status, `Request failed with ${response.status}`);
    return response.json() as Promise<TonightRecommendationResult>;
  }
}
```

The production app is served by `starskill-web` from the same loopback origin as `/v1`, so no token environment variable, Authorization header, CORS configuration, or reverse proxy is added.

- [ ] **Step 4: Run unit test and production build**

Run: `npm --prefix web test -- api.test.ts && npm --prefix web run build`

Expected: PASS and `web/dist` exists.

- [ ] **Step 5: Commit**

Run `git add web/package.json web/package-lock.json web/tsconfig.json web/vite.config.ts web/index.html web/src`, then create commit `feat: scaffold typed outreach web client`.

### Task 3: Wrap Stellarium Web Engine in one React canvas component

**Files:**
- Create: `web/src/stellarium/engine.ts`
- Create: `web/src/stellarium/engine.test.ts`
- Create: `web/src/stellarium/StellariumCanvas.tsx`
- Modify: `web/vite.config.ts`
- Modify: `web/Makefile`

**Interfaces:**
- Consumes JS/WASM assets from Task 1 and observer/time/target state from Task 4.
- Produces `<StellariumCanvas observer={...} timestamp={...} target={...} />`.

- [ ] **Step 1: Write a failing engine-facade test**

```ts
it('synchronizes observer, time, and target through the engine facade', () => {
  const setSelection = vi.fn();
  const core = { observer: { longitude: 0, latitude: 0 }, date: new Date(0) };
  const engine = createEngineFacade({ core, setSelection });
  engine.sync({ longitude: 116.4074, latitude: 39.9042, timestamp: '2026-01-10T20:00:00+08:00', target: 'M 42' });
  expect(core.observer.longitude).toBe(116.4074);
  expect(core.observer.latitude).toBe(39.9042);
  expect(setSelection).toHaveBeenCalledWith('M 42');
});
```

- [ ] **Step 2: Confirm it fails before the wrapper exists**

Run: `npm --prefix web test -- engine.test.ts`

Expected: FAIL because `createEngineFacade` is absent.

- [ ] **Step 3: Implement initialization and lifecycle**

During `make -C web engine`, copy built `stellarium-web-engine.js` and `.wasm` to `web/src/vendor/`; configure Vite to include `*.wasm`. Keep raw engine types inside `engine.ts`. Initialize once per canvas with the upstream contract:

```ts
StelWebEngine({
  wasmFile,
  canvas,
  translateFn: (_domain: string, text: string) => text,
  onReady: (stel: RawStellarium) => resolve(createEngineFacade(stel)),
});
```

`createEngineFacade().sync()` updates latitude, longitude, simulation time, and selection using engine APIs. `StellariumCanvas` has a stable canvas size, shows a visible text fallback on WebGL initialization failure, owns cleanup on unmount, and has `data-testid="stellarium-canvas"`. It does not call StarSkill HTTP endpoints or RemoteControl.

- [ ] **Step 4: Run wrapper test and build**

Run: `npm --prefix web test -- engine.test.ts && npm --prefix web run build`

Expected: PASS.

- [ ] **Step 5: Commit**

Run `git add web/src/stellarium web/src/vendor web/vite.config.ts web/Makefile`, then create commit `feat: embed Stellarium star map canvas`.

### Task 4: Build the desktop observation workspace and evidence states

**Files:**
- Create: `web/src/App.tsx`
- Create: `web/src/App.test.tsx`
- Create: `web/src/components/ObservationControls.tsx`
- Create: `web/src/components/RecommendationPanel.tsx`
- Create: `web/src/components/SourceStatus.tsx`
- Create: `web/src/styles.css`
- Modify: `web/src/main.tsx`

**Interfaces:**
- Consumes `StarSkillApi`, `StellariumCanvas`, and public API types.
- Produces the Web workspace exercised by Task 5.

- [ ] **Step 1: Write a failing UI state test**

```tsx
it('renders provider times and leaves unavailable weather visible', async () => {
  render(<App api={fakeApiWithUnavailableWeather} initialTask={validTask} />);
  await userEvent.click(screen.getByRole('button', { name: '更新今晚建议' }));
  expect(await screen.findByText('天气预报不可用')).toBeVisible();
  expect(screen.getByText('仅基于几何条件')).toBeVisible();
  expect(screen.getByText('人工复核')).toBeVisible();
});
```

- [ ] **Step 2: Confirm it fails before the workspace exists**

Run: `npm --prefix web test -- App.test.tsx`

Expected: FAIL because `App` is absent.

- [ ] **Step 3: Implement the workspace**

Create a desktop grid with `grid-template-columns: minmax(0, 1fr) 360px`: full-height star map left, fixed-width controls and evidence right. `ObservationControls` uses labeled inputs for location name, longitude, latitude, IANA timezone, ISO date/time, and target; validate coordinate bounds locally before request. `RecommendationPanel` displays grade, window, reasons, and server `human_review`. `SourceStatus` displays provider, availability, and accessed time.

Use 40 px minimum button height and 8 px maximum control radius. No text may overlay the canvas or neighboring panel. Under the mobile fallback, stack panel below a star-map canvas with `min-height: 420px`. A successful recommendation feeds resolved target, observer, and selected time to the canvas facade.

- [ ] **Step 4: Run UI test and build**

Run: `npm --prefix web test -- App.test.tsx && npm --prefix web run build`

Expected: PASS.

- [ ] **Step 5: Commit**

Run `git add web/src/App.tsx web/src/components web/src/styles.css web/src/main.tsx web/src/App.test.tsx`, then create commit `feat: add tonight observation workspace`.

### Task 5: Add deterministic browser integration tests and operator documentation

**Files:**
- Create: `web/playwright.config.ts`
- Create: `web/tests/fixtures/api-server.mjs`
- Create: `web/tests/observation-workspace.spec.ts`
- Modify: `README.md:376-381`
- Modify: `docs/mcp-server.md:1-120`

**Interfaces:**
- Consumes complete server and browser contracts.
- Produces repeatable visual acceptance evidence.

- [ ] **Step 1: Write a failing Playwright interaction test**

```ts
test('star map and evidence render without overlap', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '更新今晚建议' }).click();
  await expect(page.locator('canvas[data-testid="stellarium-canvas"]')).toBeVisible();
  await expect(page.getByText('人工复核')).toBeVisible();
  await expect(page.getByText('数据来源')).toBeVisible();
  const bytes = await page.locator('canvas[data-testid="stellarium-canvas"]').screenshot();
  expect(bytes.length).toBeGreaterThan(1000);
});
```

- [ ] **Step 2: Confirm it fails before fixture wiring**

Run: `npm --prefix web run test:e2e -- observation-workspace.spec.ts`

Expected: FAIL because the fixture API and UI server are absent.

- [ ] **Step 3: Implement fixtures and visual assertions**

The local fixture API returns one fresh weather source, one unavailable light-pollution source, one recommendation window, and all human-review strings for each `/v1` route. Configure Playwright to run Vite on `127.0.0.1`, take screenshots at `1440x960` and `390x844`, and use `locator.evaluate()` to read a 10x10 center canvas pixel area. Fail if all pixels are transparent or all RGB channels are zero. At desktop width assert separate canvas and right-panel boxes; at mobile width assert the panel begins below the canvas. Add README setup commands and cross-link the clean-clone acceptance procedure from server Task 8.

- [ ] **Step 4: Run complete Web and Python acceptance commands**

Run: `npm --prefix web test && npm --prefix web run build && npm --prefix web run test:e2e && pytest -q`

Expected: PASS. Public-network smoke results remain outside this command.

- [ ] **Step 5: Commit**

Run `git add web/playwright.config.ts web/tests README.md docs/mcp-server.md`, then create commit `test: verify browser outreach workflow`.
