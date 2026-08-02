# Gate 2 — Globus-Panel: Entscheidung

**Datum:** 2026-08-02
**Ergebnis:** ✅ bestanden. Option 1 (Business Charts / Apache ECharts + echarts-gl).

## Minimaltest

Panel-Typ `volkovlabs-echarts-panel` (Grafana Labs, vormals Volkov Labs — siehe
Hinweis unten) in Grafana Cloud (`svanfr.grafana.net`) installiert und getestet.
Dashboard: `nluecke > Fun > Gate 2 — Globe Minimaltest` (uid `am8fqq`).

Acht echte Seekabel aus `data/samples/telegeography-cable-geo.json` ausgewählt
(längste Great-Circle-Strecken: Project Waterworth, MAREA, SEA-US, AAG, Seabras-1,
Southern Cross, WACS, SeaMeWe-4), Start-/Endpunkte als `lines3D`-Serie auf
`coordinateSystem: 'globe'` gerendert. Ergebnis: Kugel mit acht Kabelbögen, per
`get_panel_image` gerendert und visuell bestätigt.

**Offener Kosmetik-Punkt:** Die Globus-Textur (`world.topo.bathy...jpg`, extern von
`echarts.apache.org` geladen) blieb im Server-seitigen Headless-Rendering weiß — vermutlich
Timing/CORS beim Bild-Renderer, kein grundsätzliches Problem. Für den Produktivbau:
Textur selbst hosten oder als Build-Artefakt einbetten statt zur Laufzeit von einer
externen CDN zu laden — konsistent mit Prinzip 1 (keine Live-Fremdabhängigkeit in der
Voting-Woche).

## Zweites Kriterium: Reagiert der Globus auf Variablen ohne vollen Neuaufbau?

Mit Dashboard-Variable `cut_cable` getestet: `context.grafana.replaceVariables('$cut_cable')`
in `getOption` gelesen, passendes Kabel korrekt rot markiert (`var-cut_cable=MAREA` →
die reale MAREA-Route Virginia Beach–Bilbao wird rot). Interaktion funktioniert.

**Quellcode-Analyse** (`github.com/grafana/business-charts`,
`src/components/EchartsPanel/EchartsPanel.tsx`) statt Browser-Interaktionstest, da in
dieser Session kein Browser-Tool verfügbar war — liefert eine präzisere Antwort als ein
Klicktest:

1. Die ECharts-Instanz wird **nur** bei Änderung von `options.renderer`, `options.map`
   oder `options.themeEditor.*` disposed/neu erstellt (Zeile 112–115). Datenänderungen
   und Variablenänderungen lösen das **nicht** aus — kein WebGL-Kontextverlust, kein
   voller Neuaufbau im eigentlichen Sinn.
2. Bei jeder Datenänderung läuft aber standardmäßig
   `chart.setOption(option, notMerge=true)` (Zeile 254, 288–294) — **vollständiges
   Ersetzen**, nicht Mergen. Für `globe.viewControl` (echarts-gl) bedeutet das: eine vom
   Nutzer per Maus gedrehte Kamera springt bei jeder Szenario-Änderung auf die im
   zurückgegebenen Option-Objekt angegebene (oder default) Ausrichtung zurück — **das ist
   der eigentliche Trägheits-Risikopunkt aus dem Briefing**, präziser gefasst: nicht
   Neuaufbau, sondern Kamera-Reset.
3. **Mitigation vorhanden:** Der Panel-Code unterstützt ein v2-Rückgabeformat
   (`{ version: 2, option, notMerge: false }`, Zeile 259–277). Mit `notMerge: false`
   merged ECharts statt zu ersetzen — wenn `viewControl` dabei aus dem zurückgegebenen
   Option-Objekt weggelassen wird, bleibt die aktuelle Kamera-Position erhalten.
   **Regel für den Produktivbau:** jede `getOption`-Funktion im echten Dashboard muss
   das v2-Format mit `notMerge: false` verwenden, sonst resettet jede What-If-Aktion die
   Kameraperspektive.
4. Der Re-Render-Effect hängt an `data` (Zeile 305) — er läuft nur, wenn sich das
   Query-Ergebnis des Panels ändert. Das heißt: **eine `var-*`-URL-Variable aktualisiert
   den Globus nur, wenn sie tatsächlich in der Datenquellen-Query verwendet wird**
   (z. B. in der Infinity-URL oder im jq-Filterausdruck interpoliert) — ein reines
   `context.grafana.replaceVariables()` in `getOption` allein reicht nicht, wenn Grafana
   keinen Query-Refresh auslöst. **Konsequenz für Stufe 1–3:** jede Szenario-Variable
   muss in der jeweiligen Infinity-Query referenziert werden, sonst bleibt das Panel
   bei einer URL-Änderung optisch stehen, bis ein unabhängiger Refresh passiert.

## Nebenbefund: Volkov Labs

Volkov Labs wurde von Enerview.AI übernommen, die alte Demo-/Doku-Seite
(`echarts.volkovlabs.io`, `volkovlabs.io`) ist tot ("Closed for Business"). Die Plugins
selbst sind aber nicht verwaist: Repo und Paket laufen jetzt unter der Organisation
`grafana` (`github.com/grafana/business-charts`, `signatureOrg: "Grafana Labs"` im
Plugin-Katalog) weiter aktiv gepflegt. Kein Blocker, aber gut zu wissen, falls die
Doku-Links in der Einreichung erwähnt werden.

## Nebenbefund: Service-Account-Rolle

Der MCP-Service-Account war entgegen der bisherigen Annahme nur mit Viewer-Rechten
ausgestattet (nur `*:read`-Permissions), nicht Editor. Nutzer hat während dieser Session
auf Editor hochgestuft. Plugin-Installation selbst braucht ohnehin `plugins:install`
(Admin) und wurde manuell in der UI durchgeführt.

## Entscheidung

Option 1 (Business Charts / echarts-gl) wird die Grundlage für das Globus-Panel.
Vor dem Weiterbau (Schritt 4 ff.) zwei Regeln festhalten:

- `getOption` gibt immer `{ version: 2, option: {...}, notMerge: false }` zurück,
  `viewControl` wird nur einmalig beim ersten Aufbau gesetzt, nicht bei jedem Update.
- Jede Szenario-Variable, die den Globus beeinflussen soll, wird in der Infinity-Query
  selbst referenziert (nicht nur in `getOption` gelesen), damit Grafana den Refresh
  überhaupt auslöst.
