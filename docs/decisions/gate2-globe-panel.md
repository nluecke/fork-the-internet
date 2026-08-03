# Gate 2 — Globe Panel: Decision

**Date:** 2026-08-02
**Result:** ✅ passed. Option 1 (Business Charts / Apache ECharts + echarts-gl).

## Minimal test

Panel type `volkovlabs-echarts-panel` (Grafana Labs, formerly Volkov Labs — see note
below) installed and tested in Grafana Cloud (`svanfr.grafana.net`).
Dashboard: `nluecke > Fun > Gate 2 — Globe Minimal Test` (uid `am8fqq`).

Eight real submarine cables selected from `data/samples/telegeography-cable-geo.json`
(longest great-circle spans: Project Waterworth, MAREA, SEA-US, AAG, Seabras-1,
Southern Cross, WACS, SeaMeWe-4), start/end points rendered as a `lines3D` series on
`coordinateSystem: 'globe'`. Result: a globe with eight cable arcs, rendered via
`get_panel_image` and visually confirmed.

**Open cosmetic point:** the globe texture (`world.topo.bathy...jpg`, loaded externally
from `echarts.apache.org`) stayed white in server-side headless rendering — likely a
timing/CORS issue with the image renderer, not a fundamental problem. For the production
build: self-host the texture or embed it as a build artifact instead of loading it at
runtime from an external CDN — consistent with Principle 1 (no live third-party
dependency during voting week).

## Second criterion: does the globe react to variables without a full rebuild?

Tested with dashboard variable `cut_cable`: `context.grafana.replaceVariables('$cut_cable')`
read inside `getOption`, correctly highlights the matching cable in red
(`var-cut_cable=MAREA` → the real MAREA route Virginia Beach–Bilbao turns red).
Interaction works.

**Source code analysis** (`github.com/grafana/business-charts`,
`src/components/EchartsPanel/EchartsPanel.tsx`) instead of an interactive browser test,
since no browser tool was available in this session — this gives a more precise answer
than a click test would:

1. The ECharts instance is disposed/recreated **only** when `options.renderer`,
   `options.map`, or `options.themeEditor.*` change (lines 112–115). Data changes and
   variable changes do **not** trigger this — no WebGL context loss, no full rebuild in
   the strict sense.
2. On every data change, however, `chart.setOption(option, notMerge=true)` runs by
   default (lines 254, 288–294) — a **full replace**, not a merge. For
   `globe.viewControl` (echarts-gl) that means: a camera the user has dragged/rotated
   snaps back to the orientation given in the returned option object (or the default)
   on every scenario change — **this is the actual inertia risk point from the
   briefing**, more precisely stated: not a rebuild, but a camera reset.
3. **Mitigation available:** the panel code supports a v2 return format
   (`{ version: 2, option, notMerge: false }`, lines 259–277). With `notMerge: false`,
   ECharts merges instead of replacing — if `viewControl` is omitted from the returned
   option object, the current camera position is preserved.
   **Rule for the production build:** every `getOption` function in the real dashboard
   must use the v2 format with `notMerge: false`, otherwise every what-if action resets
   the globe's camera perspective.
4. The re-render effect is keyed on `data` (line 305) — it only runs when the panel's
   query result changes. This means: **a `var-*` URL variable only updates the globe if
   it is actually used in the data source query** (e.g. interpolated into the Infinity
   URL or the jq filter expression) — a plain `context.grafana.replaceVariables()` call
   inside `getOption` alone is not enough if Grafana doesn't trigger a query refresh.
   **Consequence for Stage 1–3:** every scenario variable must be referenced in its
   respective Infinity query, otherwise the panel stays visually frozen after a URL
   change until an unrelated refresh happens.

## Side finding: Volkov Labs

Volkov Labs was acquired by Enerview.AI; the old demo/docs site (`echarts.volkovlabs.io`,
`volkovlabs.io`) is dead ("Closed for Business"). The plugins themselves are not
orphaned, though: the repo and package now live and are actively maintained under the
`grafana` organization (`github.com/grafana/business-charts`,
`signatureOrg: "Grafana Labs"` in the plugin catalog). Not a blocker, but good to know in
case the docs links are mentioned in the submission.

## Side finding: service account role

Contrary to prior assumption, the MCP service account only had viewer rights
(`*:read` permissions only), not editor. The user upgraded it to editor during this
session. Plugin installation itself requires `plugins:install` (admin) regardless and was
done manually in the UI.

## Decision

Option 1 (Business Charts / echarts-gl) becomes the foundation for the globe panel.
Two rules to hold onto before continuing the build (Step 4 onward):

- `getOption` always returns `{ version: 2, option: {...}, notMerge: false }`;
  `viewControl` is only ever set once at initial construction, never on every update.
- Every scenario variable meant to affect the globe is referenced in the Infinity query
  itself (not just read inside `getOption`), so Grafana actually triggers a refresh.
