# assets/

Static third-party assets committed directly (not build-generated, not weekly-refreshed).

## world.topo.bathy.200401.jpg

Globe base/height texture for the echarts-gl globe panel (`Globe: cable network`,
dashboard `al9xz4`). Self-hosted here instead of loaded at runtime from
`echarts.apache.org` for two reasons:

1. **Principle 1 (no live third-party dependency during voting week).** The dashboard
   should not depend on an external CDN staying up during the public voting window.
2. **Fixes a real rendering bug.** Gate 2 testing found the texture stayed white/grey
   in server-side headless rendering when loaded externally (`docs/decisions/gate2-globe-panel.md`)
   — likely a timing/CORS issue specific to cross-origin image loads in the image
   renderer. Serving the same bytes from `raw.githubusercontent.com` (same-origin
   pattern already used for `data/graph.json`) resolves it.

Source: NASA Visible Earth / Blue Marble: Next Generation with Topography and Bathymetry
(January 2004 composite), via the Apache ECharts example gallery asset of the same name
(`echarts.apache.org/examples/data-gl/asset/world.topo.bathy.200401.jpg`, identical bytes).
NASA imagery is public domain (17 U.S.C. § 105); courtesy credit: *Image courtesy NASA
Visible Earth / NASA Earth Observatory.*
