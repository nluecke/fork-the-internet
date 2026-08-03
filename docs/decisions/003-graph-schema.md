# 003 — Graph Schema for the Build Artifact

**Date:** 2026-08-09 (placeholder, adjust to actual date)
**Status:** Schema final — round 3 review incorporated, final schema round. Approved as
final out of round 2 and unchanged in round 3: matching algorithm (Point 3),
`baseline_pair_path_count` rename (Point 5), `nodes`/`adjacency`/`edge_index`
(Point 6), stable IDs (Point 7), Option A + `scope_note` (Point 8). Round 3: arc length
instead of straight-line distance for submarine cable edges (Point 4), chain formation
explicitly specified including a newly discovered fourth matching fallback (Point 3a),
`data/landmass_groups.json` fully replaces the curated bridges from round 2 — threshold
clustering becomes a build check instead of a decision-maker (Point 1), automatic
latency warnings instead of hardcoded Russia (Point 2), `unreachable_baseline_pairs`
computed for real for the first time: 1,094 (Point 5).
**Proceed directly to Phase B, no further schema approval needed.**
**Scope:** Covers Stage 1 (reachability), Stage 2 (latency), and the baseline for
Stage 3 (reroute pressure) of the physical cable/country graph. **Not** part of this
document: the AS/IXP graph (CAIDA, RIPEstat, PeeringDB) and the RIPE Atlas validation
layer — both are added only in later steps (6 onward) and need their own schema update,
not anticipated here.

All numbers below are computed from the real samples in `data/samples/` or — for
Point 1 and the snapping verification — from all 697 cable detail responses of the
TeleGeography API, queried live, not estimated. Details on the snapping verification:
`003a-snapping-trefferquote.md`.

---

## 1. Two Levels, One Graph: Landing Points + Country Hubs per Cluster (revised)

**Revised after review — the original one-hub-per-country approach was a blocker.**
A single centroid per country breaks down for countries with geographically scattered
territories: the arithmetic mean of Marseille and an island in the Pacific produces a
point that doesn't exist anywhere in reality, and worse — it would suggest a path in the
graph *through* this nonsensical point, where in reality none exists.

**Verified, not assumed:** Recalculated using the authoritative `country` field from all
697 cable detail responses (see `003a-snapping-trefferquote.md`). Important finding up
front: TeleGeography already lists French overseas territories (`French Guiana`,
`Réunion`, `New Caledonia`, `French Polynesia`, `Martinique`, `Guadeloupe`, `Mayotte`) as
**separate** `country` values, distinct from `France` (27 landing points, all mainland +
Corsica). Likewise `Bermuda`, `Cayman Islands`, `Bonaire, Sint Eustatius and Saba`, etc.
are separate country strings. The FR example named in the brief therefore doesn't occur
in the real data as stated — but that doesn't change the fact that the underlying
problem is real, see US, Canada, Australia, Netherlands, Kiribati below.

**Decision: one hub per geographic cluster within a country, not one per country.**

- **Clustering:** single-linkage over a country's landing points, threshold **2,000 km**
  (great-circle). Two landing points are in the same cluster if a chain of intermediate
  points exists that is never more than 2,000 km apart.
- **Threshold justification, corrected after review.** The first version justified
  2,000 km via the distribution of nearest-neighbor distances — methodologically wrong,
  as correctly noted in review: single-linkage merges at **merge heights**, not at
  nearest-neighbor distances of individual points. For single-linkage, a country's merge
  heights are exactly the edge weights of its minimum spanning tree (MST) — Kruskal's
  algorithm and single-linkage dendrograms are the same construct. Recalculated
  correctly: built an MST per country (all 186 countries, 1,736 edges total), pooled all
  edge weights.
  - Distribution: 95% of all merge heights are below 483 km, 99% below 1,165 km, 99.5%
    below 1,651 km.
  - **There is no longer a clean empty zone as claimed in the first version.** The
    bucket distribution between 1,500 and 4,000 km is thin but not empty: 8 merge
    heights between 1,500–2,000 km, 2 between 2,000–2,500 km, **0 between
    2,500–3,000 km**, 2 between 3,000–3,500 km, 1 between 3,500–4,000 km. Only a single
    500-km bucket is empty, no wide gap.
  - **The threshold is a chosen convention, not a law of nature — stated openly here.**
    The exact window that reproduces the five-country grouping shown below (USA/Canada/
    Australia/Netherlands/Kiribati multiple, all others single) unchanged is
    **[1,994 km, 2,041 km)** — bounded above by Australia's largest MST edge (2,041 km,
    must stay above the threshold so Australia remains split), bounded below by
    Argentina's largest MST edge (1,994 km, must stay below the threshold so Argentina
    is **not** unnecessarily split as well). That's **47 km of margin**, not several
    thousand. 2,000 km is a round number that happens to fall within this narrow
    window — not a choice "proven" by a wide gap.
  - **Consequence:** This fragility belongs in Phase B as a build sanity check — if a
    future dataset (a new landing point in Argentina or Australia) shifts or closes the
    window, the build must report it, not silently produce a different hub split. And
    the math-panel text must say "2,000 km is a set convention, not an empirically
    unambiguous break," not the original (incorrect) gap claim.
- **Result with the threshold, authoritative country data:** **192 hubs across 186
  countries.** Only 5 countries get more than one hub:

  | Country | Hubs | Clusters (size, rough location) |
  |---|---|---|
  | USA | 3 | Alaska/West Coast (98), East Coast (44), Hawaii (25) |
  | Canada | 2 | West Coast/BC (115), Atlantic provinces (40) |
  | Australia | 2 | Sydney/East Coast (20), Darwin/Perth/Northwest (7) |
  | Netherlands | 2 | Mainland (7), Bonaire (1) |
  | Kiribati | 2 | Tarawa (1), Tabwakea/Kiritimati (1) |

  All other 181 countries get exactly one hub. This table shows the **raw threshold
  result** — the actual hub count after the "landmass groups" point below is lower (189
  instead of 192), because three of these five-country cases are not a genuine land
  split but a data gap in the threshold.

**Landmass groups replace the curated bridges — revised after review 3.**
Round 2 solved the problem (USA east/west need a connection for the real North American
transit route in the Red Sea scenario) with three hand-maintained bridge edges. Problem
per review: the bridge list is a function of the 2,000-km threshold but is maintained
independently of it — if the threshold shifts or a new country drifts across the
boundary, a bridge silently goes missing.

**Decision:** Instead of forming clusters and then curating bridges after the fact,
directly curate **which landing-point groups of a country are the same landmass** — the
2,000-km clustering becomes a **build check**, no longer the decision-maker.

- **`data/landmass_groups.json`** (fully replaces `data/bridges.json`, which becomes
  obsolete): a short list of "forced merges," each entry giving two anchor landing
  points whose clusters are to be treated as one landmass:

  ```json
  {
    "force_same_landmass": [
      { "country": "United States", "anchor_points": ["anchorage-ak-united-states", "shirley-ny-united-states"], "note": "Mainland incl. Alaska/West Coast + East Coast; Hawaii remains separate" },
      { "country": "Canada", "anchor_points": ["cordova-bay-bc-canada", "cape-ray-nl-canada"], "note": "West Coast/BC + Atlantic provinces" },
      { "country": "Australia", "anchor_points": ["sydney-nsw-australia", "darwin-nt-australia"], "note": "East Coast + Northwest" }
    ]
  }
  ```

  Anything not listed in the file stays with the raw threshold result — for most
  countries that's a single cluster anyway; for Hawaii/Bonaire/Kiritimati the (correct)
  split remains.

- **Build check, verified and passed:** For each of the 186 countries, the 2,000-km
  clustering is computed, then the declared merges are applied (union-find over the
  clusters containing the anchor points). Two checks, both must pass green for **all**
  186 countries, not just the three known cases:
  1. Every country **not** listed in `landmass_groups.json` must consist of **exactly
     one** cluster after threshold clustering. Otherwise: build aborts — "Country X is
     fragmented and not declared in `landmass_groups.json`."
  2. Every declared merge must do real work — the two anchor points must be in
     **different** clusters **before** the merge. If they already land in the same
     cluster, the entry is likely stale (new cables have closed the gap): build aborts —
     "Entry for country X may be redundant, please check."
  Recomputed: **0 errors on both checks**, with exactly the three entries listed above.
  This is direct proof that the file is complete today — and the mechanism that will
  loudly report a future fragmenting Argentina instead of silently staying wrong.
- **Result: 189 hubs instead of 192.** USA (3→2: mainland unified, Hawaii remains),
  Canada (2→1: unified), Australia (2→1: unified). Netherlands and Kiribati remain at 2
  — those are the only two genuine multi-hub countries left.
- **Verified: the three old bridges now arise as perfectly ordinary MST edges, no
  special handling, no separate edge type needed anymore.** The minimum spanning tree
  over the **unified** point set of each country finds the cheapest connection itself —
  and in all three cases it is more precise than the old, curated hub-to-hub distance:

  | Country | New MST edge (real landing points) | Distance | Old curated bridge (hub centroid to hub centroid) |
  |---|---|---|---|
  | USA | San Diego, CA ↔ Freeport, TX | **2,120.7 km** | 5,281.2 km |
  | Canada | Kitimat, BC ↔ Ivujivik, QC | 3,021.2 km | 4,041.4 km (~same order of magnitude) |
  | Australia | Kingscote, SA ↔ Mandurah, WA | 2,041.0 km | 2,685.7 km |

  The USA case shows the difference most clearly: the old bridge measured centroid to
  centroid (5,281 km, a number with no real-world counterpart), the new MST edge
  measures real landing points (2,120.7 km) — more than twice as precise, because it
  finds the actually closest pair of points across the continent instead of two
  artificial midpoints. **Consequence:** `terrestrial_bridge` as an edge type is
  dropped, `data/bridges.json` is dropped. Every edge in the graph is either
  `submarine` or `terrestrial` — no third, curated category anymore.
- **Country reachability:** unchanged — a country counts as reachable if at least one
  of its (now 189 instead of 192) hubs is reachable from the rest of the graph.

**Hub coordinate: true spherical centroid, not arithmetic mean of lat/lon.**
The arithmetic mean breaks at the 180th meridian. Demonstrated with Kiribati (Tabwakea:
−157.43°, Tarawa: 172.98°): arithmetic mean yields 7.78° — that's in the Gulf of
Guinea, on the exact opposite side of the earth. Correct: convert coordinates to
Cartesian unit vectors, average, project back to lat/lon → −172.23°, the actual
midpoint. Formula:

```
x = cos(lat)·cos(lon), y = cos(lat)·sin(lon), z = sin(lat)   [per point, averaged]
lat = asin(z / |v|), lon = atan2(y, x)                        [projected back]
```

Since Kiribati falls into two single-point clusters anyway (each cluster is trivially
its own centroid), the example demonstrates the necessity of the formula rather than
fixing an actual bug in the current dataset — it kicks in whenever two nearby landing
points in the future land directly on opposite sides of the 180th meridian. Mandatory
in the implementation, regardless of whether the current dataset happens to test it.

**Hub coordinate: true spherical centroid, not arithmetic mean of lat/lon.**
The arithmetic mean breaks at the 180th meridian. Demonstrated with Kiribati (Tabwakea:
−157.43°, Tarawa: 172.98°): arithmetic mean yields 7.78° — that's in the Gulf of
Guinea, on the exact opposite side of the earth. Correct: convert coordinates to
Cartesian unit vectors, average, project back to lat/lon → −172.23°, the actual
midpoint. Formula:

```
x = cos(lat)·cos(lon), y = cos(lat)·sin(lon), z = sin(lat)   [per point, averaged]
lat = asin(z / |v|), lon = atan2(y, x)                        [projected back]
```

Since Kiribati falls into two single-point clusters anyway (each cluster is trivially
its own centroid), the example demonstrates the necessity of the formula rather than
fixing an actual bug in the current dataset — it kicks in whenever two nearby landing
points in the future land directly on opposite sides of the 180th meridian. Mandatory
in the implementation, regardless of whether the current dataset happens to test it.

That answers "route or aggregate landing points" not as an either/or: **we do both at
the same time**, because every hub is itself part of the routing graph.

---

## 2. Terrestrial Edges: Spanning Tree Instead of Star (revised)

**Problem:** Landing points in the same cluster (see Point 1) need a connection, or the
graph falls apart at every cluster boundary with more than one landing point.

**Revised after review — the star to the cluster centroid was optimized for the wrong
target.** Originally: every landing point gets a `terrestrial` edge to its cluster hub.
Problem: for elongated clusters, the star potentially doubles the route — a path from
one end to the other always runs via the hub in the middle and back, no matter how
close the two landing points actually are along the coast.

**Decision:** Minimum spanning tree (MST) over the real landing points of each cluster
(great-circle weights, the same fiber formula as for submarine cables, see Point 4)
instead of a star. The cluster hub remains as a country/cluster handle, but is now
connected with only **one** edge to its nearest real landing point — no longer to all
of them.

**Edge count and artifact size: unchanged.** A cluster with *n* landing points had *n*
edges in the star (one LP→hub each). The spanning tree has *n*−1 edges (MST) plus 1 hub
connection = also *n* edges. Recomputed across all 189 landmass groups (see Point 1,
after merging USA/Canada/Australia): **1,922 terrestrial edges, unchanged** — the
grouping changes which points are combined into a tree, not the total edge count.

**An honest finding, not just an improvement — now recomputed with the merged landmass
groups from Point 1.** The MST minimizes a group's **total edge length** (that's its
mathematical definition) — that is not the same as minimizing the **longest individual
path** (diameter), which is what the brief actually intended to address. Now that
USA/Canada/Australia are treated as **one** group instead of two (Point 1), the USA
group (142 points, mainland incl. Alaska, excl. Hawaii) is by far the largest in the
entire dataset:

| Group | Points | Modelled MST diameter | Modelled latency |
|---|---|---|---|
| **USA (mainland)** | 142 | **13,944.9 km** | **69.7 ms** |
| Russia | 28 | 12,591.9 km | 63.0 ms |
| Brazil | 75 | 8,410.0 km | 42.1 ms |
| Australia | 27 | 8,113.5 km | 40.6 ms |
| Canada | 155 | 7,497.6 km | 37.5 ms |
| Indonesia | 146 | 7,315.5 km | 36.6 ms |

For comparison, star diameter (old, before the merge, for context only): Russia
10,818 km, Norway (42 points) 3,304 km → MST 3,035 km (269 km better), Malaysia
(21 points) 2,322 km → MST 2,268 km (53 km better). For compact clusters, the spanning
tree improves the diameter as expected; for the now large-area, merged groups (USA,
Russia, Brazil, Australia, Canada, Indonesia), the tree's chain structure makes the
worst individual path **longer** than a hypothetical star through the centroid would —
Kaliningrad–Kamchatka for Russia, San Diego or Miami to Alaska for the USA. That's a
genuine trade-off, not an implementation flaw.

**New — automatic `warnings` entries for unrealistically high modelled intra-group
latency, not just hardcoded Russia.** Threshold: **30 ms**, based on a real reference
route (New York↔London, ~5,750 km great-circle ≈ 28.75 ms in our own formula — a real,
well-documented intercontinental link). Every landmass group whose modelled MST
diameter exceeds this latency value is automatically added to the `warnings` array
during the build (not a hand-maintained list):
`{"type": "high_intra_group_latency", "group": "...", "modelled_latency_ms": ..., "threshold_ms": 30}`.
With the current data, that applies to **6 groups**: USA, Russia, Brazil, Australia,
Canada, Indonesia (India at 26.1 ms would stay just under it — the threshold separates
visibly, not arbitrarily).

**Second mandatory sentence for the "show me the math" panel, in addition to the
trade-off text from round 2:**

*"The spanning tree connects every landmass group with zero redundancy — a tree by
definition has exactly one path between two points, no second way around. That's
acceptable as long as scenarios only cut submarine cables (this model has no cuttable
land connections anyway, see Point 8). If a future version were to also make land
routes cuttable, every landmass group would need its own redundancy edges — the
spanning tree is the wrong structure for that, deliberately chosen because it's
sufficient for the current scenario universe."*

**Hub connection distance** (centroid → nearest real landing point) sits at a median of
47.5 km, under 830 km for 99% of groups — the hub connection itself is cheap in the
vast majority of cases.

---

## 3. Cables → Edges: Snapping Segment Endpoints to Landing Points (matching corrected)

**Design flaw in the first matching fixed.** "Take assigned landing points from the
pool" assumed a bijection between segment endpoints and landing points. In reality:
3,860 endpoints for only 3,184 declared pairs — a landing point where a cable passes
through (an intermediate/branching station) is the endpoint of **two** segments. The
old "take from the pool" approach would have incorrectly locked out such pass-through
stations after their first endpoint.

**Corrected algorithm, three-tier, fully many-to-one:**

1. **Endpoint matching.** For each cable: collect all (segment endpoint, landing point)
   pairs within 50 km, sort ascending by distance, assign greedily. An **endpoint** gets
   exactly one landing point (not reassigned after matching). A **landing point** stays
   in the candidate pool and may take any number of endpoints — this correctly models
   pass-through stations.
2. **Vertex split** for landing points still without an endpoint after step 1: match
   against all interior line points (not just endpoints) across all segments of the
   same cable, again greedily by distance, one position (segment, vertex index) per
   landing point. A match **splits** the affected segment at that point into two edges
   — the landing point becomes a real intermediate node in the path, not a straight
   line to a distant neighbor.
3. **Inferred edge** only for landing points that come up empty after step 1 **and** 2:
   a direct edge to the nearest already-matched landing point of the same cable, marked
   `"inferred": true`.

**Tested on 6 cables, including both named in the review:**

| Cable | Declared | Tier 1 (endpoint) | Tier 2 (vertex split) | Tier 3 (inferred) | Unmatched |
|---|---|---|---|---|---|
| `2africa` | 50 | 49 | 1 | 0 | 0 |
| `5-villages-6-islands` | 9 | 8 | 1 | 0 | 0 |
| `au-aleutian` | 14 | 12 | 2 | 0 | 0 |
| `aqualink` | 11 | 10 | 1 | 0 | 0 |
| `aurora` | 12 | 12 | 0 | 0 | 0 |
| `apcn-2` (stress test, not requested) | 10 | 2 | 8 | 0 | 0 |

`apcn-2` was additionally tested because it stood out in the first (flawed) matching
with 8 of 10 completely unmatched — a large trunk cable (Singapore–Japan) with two
50-vertex long-haul stretches on which 8 intermediate stations (Hong Kong, Shantou,
Busan, Taipei, etc.) sit exactly as interior vertices (0.0–1.4 km deviation), not as
segment endpoints. Without Tier 2 (vertex split), that would have been eight unmatched
landing points on a single, very real cable — the best evidence that the vertex
fallback tier is not a nice-to-have but a necessity.

**Full run across all 697 cables, with the corrected algorithm:**

| Category | Count | Share |
|---|---|---|
| Tier 1 (endpoint) | 2,646 | 83.1% |
| Tier 2 (vertex split) | 531 | 16.7% |
| Tier 3 (inferred) | 7 | 0.2% |
| Unmatched | 0 | 0% |
| **Total** | **3,184** | 100% |

Noticeably more vertex splits than in the first (flawed) count (405 there, 531 now) —
exactly the expected effect of the many-to-one correction: pass-through stations that
previously passed incorrectly as an "endpoint match" because their neighboring endpoint
was already taken now correctly land in the vertex tier or are genuinely recognized as
an endpoint. Updated full evaluation, including the 210-of-697 ambiguity check (remains
unchanged in relevance, the many-to-one matching resolves it structurally, see
`003a-snapping-trefferquote.md`).

**Decision (unchanged in the basic idea, now correctly implemented):**
- Every `MultiLineString` sub-segment of a cable becomes a `submarine` edge between two
  landing points (or more, after vertex splits). Tolerance remains 50 km.
- Every edge gets a stable `id` (`<cable_id>__<segment_index>`, with a suffix for
  splits) and a `cable_id` field. Plus a `cables` index (`cable_id → {edge_indices,
  ...}`) for O(1) access to **all** edges of a cable. **697 unique cables, not 718** —
  718 is the number of GeoJSON features in `cable-geo.json`, 21 cables are spread
  across multiple features.

**This makes both required operations cheap:**
- *Cut a whole cable:* `cables[$cable_id].edge_indices` → mark all associated edges.
  O(1) lookup, no scan.
- *Cut a single segment:* the edge has its own stable `id`, directly referenceable via
  `edge_index[$edge_id]` (see Point 6). No special case needed — the data structure
  distinguishes "whole cable" from "one segment" only by the set of affected edge IDs.

---

## 3a. Chain Formation — new, Round 3 (closes the gap in `unreachable_baseline_pairs`)

Point 3 says **which** landing point belongs to which segment/vertex, but not in what
**order** multiple landing points on the same segment become edges — that exact gap
made `unreachable_baseline_pairs` uncomputable in round 2.

**Decision, verbatim:** For each segment, all landing points assigned to it (Tier-1
endpoints **and** Tier-2 vertex splits) are sorted by their **arc-length position**
along the polyline (cumulative distance from the segment's first vertex). Consecutive
pairs in this ordering each become one edge, weight = the arc-length difference between
them (see Point 4 for the exact formula). Across segment boundaries, landing points
chain together automatically when the same landing-point ID appears on multiple
segments (pass-through station, see Point 3) — no extra logic needed, the edges of both
segments share the node.

**Fourth fallback discovered during testing, not originally planned: branch fallback.**
Landing points that end up as the **only** placement on their segment (no chain
partner) produce **no** edge under pure arc-length chaining — they remain isolated in
the graph despite being successfully matched. This is not an edge case: **704 out of
roughly 3,184 placements (≈22%) are affected, across 195 cables.** Cause: short stub
segments to a branching unit whose other end has no landing point of its own in the
public geometry — the branching unit itself is not a declared node in the data.

Found concretely in the example `accra-ghana` on the `2africa` cable: it sits alone on
a 3-vertex stub segment whose other end doesn't match anywhere else. Without a fix,
Ghana would remain completely disconnected in the graph — even though 2Africa is one of
the best-connected cables in the world. This was initially indistinguishable from a
genuine connectivity problem (see the earlier, incorrect 40-country report in round 2).

**Fix:** Landing points without a chain partner on their own segment get an edge to the
nearest **already-chained** landing point on the **same cable** (cable-wide, not
segment-wide) — great-circle distance, since no shared polyline exists between the two.
Marked with its own `length_source` value (see Point 4), so these edges remain
distinguishable from genuine arc-length edges.

**Result after the fix:** 0 unmatched, 1,581 genuine arc-length edges (Tier 1+2,
chained), 638 chord edges (7 Tier-3 `inferred` unchanged from round 2 + 631 branch
fallback). That's a substantial share (638 of 2,219 cable edges, ≈29%) of edges without
a real geometric basis — worth stating honestly, not hiding: the public TeleGeography
geometry doesn't draw branching units as their own points, our model has to compensate.

---

## 4. Edge Weights: Arc Length for Submarine Cables, Great-Circle for Land (corrected)

**Bug fixed:** `distance_km` was defined for all edges as the great-circle distance
between endpoints. For submarine cables that's systematically too short — cables don't
run straight, and `apcn-2` alone has 50 vertices on one segment. Latency is the
project's headline number, it has to be right.

**Decision, by edge origin:**
- **`submarine`, Tier 1/2 (real polyline present):** `distance_km` = arc length along
  the polyline between the two landing points (sum of vertex-to-vertex great-circle
  distances in the respective section, see Point 3a).
- **`submarine`, Tier 3 (`inferred`) and Tier 4 (branch fallback):** great-circle
  chord — there is no polyline between the two points, so the straight-line distance is
  all that's left absent an alternative. Remains conceptually part of the submarine
  cable family, but without a genuine geometric basis.
- **`terrestrial`:** great-circle remains, as decided in round 2 — no geometry
  available.
- **Origin explicit in the `length_source` field** (`"polyline_arc"` | `"great_circle_chord"`),
  independent of the `type` field — exactly the required distinguishability.

**Ratio of arc length to straight-line distance, recomputed across all 1,579 Tier-1/2
edges with chord > 0:**

| Percentile | Ratio |
|---|---|
| Median (p50) | 1.06 |
| p90 | 1.39 |
| p95 | **1.62** |
| p99 | 2.59 |
| Maximum | 4.77 |

**The 5 cables with the largest ratio (arc length/straight-line, aggregated per cable):**

| Cable | Ratio | Arc length | Straight-line |
|---|---|---|---|
| `tautira-teahupoo` | 3.62 | 41.6 km | 11.5 km |
| `i-am-cable` | 3.28 | 205.9 km | 62.8 km |
| `ruppione-isolella` | 2.67 | 54.1 km | 20.3 km |
| `kumul-domestic-submarine-cable-system` | 2.09 | 1,957.3 km | 935.7 km |
| `subcan-link-2` | 2.06 | 207.0 km | 100.7 km |

Notably, all five are short, coastal/local systems (Tahiti, PNG domestic cable,
Corsican coast), not the large trunk cables — plausible, because deep-sea routes run
closer to a great circle, while coastal cables have to avoid reefs, bays, and shallow
water. Reinforces that the method makes geometric sense rather than just producing
numbers.

The constant sits once in the artifact header (`constants`), not duplicated per edge:

```json
"constants": {
  "speed_of_light_km_s": 299792.458,
  "fiber_index_factor": 0.667,
  "fiber_speed_km_s": 199861.63
}
```

**Mandatory caveat for the "show me the math" panel:**

*"Even the arc length from the TeleGeography geometry is a cartographic
simplification, not a survey — real cables lie with additional slack for tension and
laying tolerance. The arc length is a notably better lower bound than the
straight-line distance (6% longer at the median, up to 4.8x for individual cables), but
remains a lower bound, not an exact cable length."*

`distance_km` is mandatory because the "show me the math" panel needs to show the raw
physics, not just the derived result — exactly the point where the jury might ask, and
the answer must be right there in the artifact without a detour.

---

## 5. Baseline for Stage 3: Edge Usage, Not All-Pairs Paths

**Size risk, concretely:** ~186 countries yield up to ~17,200 undirected country pairs.
If the full path (list of edge IDs) were stored per pair in the artifact, at ~8–12
edges per path that would quickly add up to several hundred thousand edge references —
exactly the blow-up risk the brief warns against.

**Decision:** We store **no** paths, only their aggregate. During the build (not in jq,
but in the generator script with a real graph library), the weighted shortest path (hub
to hub, `latency_ms`) is computed for each of the ~17,200 country pairs; for every edge
on that path, a counter `baseline_pair_path_count` is incremented. This is essentially
edge betweenness centrality (Brandes' algorithm), just computed on the build server,
not live. Result: **one integer per edge**, no path record. Costs practically nothing
in artifact size (~3,850 edges × one additional field).

**What this does NOT solve:** The live computation of actual reroute pressure after a
cut (which country pairs were affected, where do they reroute now) is not yet
specified by this — that's model logic for step 8 (Stage 3), not schema for this step.
What this decision does ensure: the artifact provides the **reference size**
(`baseline_pair_path_count`) against which a later-built live query can put an edge's
post-cut usage into proportion — exactly what the phrase *"3.2 times its normal share
of paths"* from the project brief needs. **Open question for step 8, deliberately not
decided here:** whether the live recomputation runs on the full graph or is limited to
a local radius around the cut edge to keep jq performance in check.

**Renamed after review:** The field was originally called `baseline_usage_count` — the
name suggested traffic volume, but it was never that. It counts **country pairs,
unweighted**, not bytes or bandwidth. Renamed to **`baseline_pair_path_count`** to make
that unambiguous. Side effect of the country hub revision from Point 1: the count
technically runs over hub nodes (192, not 186 countries directly) — the country-pair
distance is defined as the minimum over all hub combinations of the two countries, so
a country with multiple hubs doesn't count multiple times but takes its cheapest
access.

**Mandatory text for the "show me the math" panel, to be adopted verbatim or in
substance:**

> This number counts how many country pairs have their shortest path in the model run
> over this edge — not how much actual data traffic flows over it. A country pair with
> negligible traffic counts the same as one with enormous volume. This is a measure of
> structural importance in the model, not a traffic or capacity value — we don't have
> real traffic data per cable (see Stage 3 in the project brief).

**New — unreachable country pairs in the baseline state, added to the artifact.** The
betweenness computation above assumes a path exists between two countries at all.
That's not guaranteed in the raw dataset — some countries hang off only a single, small
regional system. **Decision:** The build counts, during the betweenness run, how many
of the ~17,200 country pairs have **no** path (union-find/BFS over the finished graph —
a byproduct of the betweenness computation anyway, no extra expensive pass), and puts
the number as `unreachable_baseline_pairs` in the artifact header. A country that is
itself isolated is skipped in the betweenness count instead of being silently counted
along.

**Actually computed, round 3 — with the chain formation from Point 3a and the landmass
groups from Point 1 (697 cables, 1,581 arc-length + 638 chord edges, 1,922 terrestrial
edges, 189 hubs):**

| Metric | Value |
|---|---|
| Reachable country pairs | 16,111 |
| **`unreachable_baseline_pairs`** | **1,094 of 17,205 (6.4%)** |
| Fully isolated countries (no hub in the largest component) | **6** |

**The 6 isolated countries, all plausible, no longer obviously wrong as in round 2:**

| Country | Landing point(s) | Assessment |
|---|---|---|
| Azerbaijan | `sumgait-azerbaijan` | Caspian Sea — an inland sea with no connection to the world ocean. A submarine cable model can't show this any other way structurally, this is not a model gap but the reality of this body of water |
| Kazakhstan | `aktau-kazakhstan` | Same Caspian Sea situation |
| Tuvalu | `funafuti-tuvalu` | A single landing point, small Pacific system |
| Wallis and Futuna | 2 landing points | Small, isolated Pacific regional system |
| Tokelau | 3 landing points | Small, isolated Pacific regional system |
| Saint Helena, Ascension and Tristan da Cunha | 1 landing point | Remote South Atlantic island group |

**Below the set stop threshold of 10 — no stop needed.** Azerbaijan/Kazakhstan are
actually positive evidence for Principle 4 ("the model is inspectable") and the
tightened `scope_note` from Point 8: a pure submarine cable model correctly shows the
Caspian Sea as not connected to the global submarine cable network, because in reality
it isn't — those countries effectively get internet via land connections (Russia,
Iran), which this model deliberately does not represent.

**How the earlier false finding (40 isolated countries, including Ghana/Senegal) came
about and was fixed:** see Point 3a — missing chaining across segment boundaries, plus
the newly introduced branch fallback (Tier 4) for landing points without a chain
partner on their own segment. With both fixed, the number of falsely isolated
countries dropped from 40 to the now-plausible 6.

**Phase B addendum (real build run, three more bugfixes, 2026-08-03) — numbers above
are superseded:**

- **`unreachable_baseline_pairs`: 551 of 17,205 (3.2%), no longer 1,094.** Cause: 36
  cables (including real large-scale systems like Equiano, Bifrost, Echo, Faster, Juno,
  Jupiter) had **zero edges and not a single warning** in the previous implementation —
  the branch fallback (Tier 4) needed an already-chained landing point as an anchor,
  but never had one when *every* declared landing point of a cable sat alone on its own
  segment (pure branching topology, no segment shared by two). Fix: deterministic
  bootstrap anchor (lexicographically smallest landing-point ID), see
  `scripts/build_graph.py`.
- **Isolated countries: 3, not 6.** Saint Helena (now correctly connected to
  Nigeria/South Africa/Togo via Equiano), Tokelau, and Wallis and Futuna drop off the
  list — they were only isolated due to the Tier-4 bug. Remaining: **Azerbaijan,
  Kazakhstan** (Caspian Sea, still genuinely isolated) and **Tuvalu** (still a single,
  small Pacific landing point with no global connectivity). Additionally, the
  `isolated_countries` definition itself was implemented too narrowly ("unreachable
  from *every* other country" instead of "no hub in the largest connected component")
  — that would otherwise have missed Azerbaijan/Kazakhstan as a connected but, from the
  rest of the world, separated country pair. Now determined via genuine connected
  components (union-find over the entire node graph).
- Two further, smaller bugs found in the same run: a Tier-1/Tier-2 vertex collision
  (two different landing points several km apart could snap to the same polyline
  vertex and thereby collapse into a 0-km edge) and duplicate consecutive vertices in
  TeleGeography's own raw geometry (`australia-japan-cable-ajc`, segment 2) with the
  same effect. Both fixed, see code comments in `scripts/build_graph.py`.
- These corrections are a genuine improvement in model accuracy, not compromises to
  the schema structure (Points 1–8 remain unchanged) — pure generator bugfixes, as
  foreseen in the project brief for Phase B ("if the build run shows a new error
  again, just keep debugging").

---

## 6. jq Suitability: No Linear Scans

- **`nodes`**: object, keyed by node ID (`landing_point` and `country_hub` nodes mixed,
  distinguished via `"type"`). O(1) lookup for "give me the country/coordinates of node
  X."
- **`edges`**: array (not keyed) — edges are almost never looked up individually by ID,
  but reached via adjacency or the cable index. An array saves the double overhead of
  an object key **and** an `"id"` field.
- **`adjacency`**: object, keyed by node ID → array of **numeric indices** into `edges`
  (not edge-ID strings — saves bytes, stays O(1)).
- **`edge_index`**: object, keyed by edge-ID string → numeric index into `edges`.
  Solves the case "a scenario variable names an edge ID, I need the edge" without a
  scan.
- **`cables`**: object, keyed by cable ID → `{name, edge_indices: [...],
  landing_point_ids: [...]}`. Solves the case "a scenario variable names a cable"
  without a scan.

This makes every operation a scenario variable can trigger (cutting a cable, cutting a
segment, looking up node info, finding a node's neighbors) an O(1) or O(degree) access,
never a scan over all 3,850 edges.

---

## 7. Reproducibility

```json
{
  "schema_version": "1.0.0",
  "generated_at": "2026-08-09T03:00:00Z",
  "sources": [
    {
      "name": "TeleGeography Submarine Cable Map",
      "license": "CC BY-SA 4.0",
      "fetched_at": "2026-08-09T02:47:11Z",
      "raw_feature_count": 718,
      "unique_cable_count": 697,
      "landing_point_count": 1922
    }
  ],
  "constants": { "...": "see Point 4" },
  "scope_note": "see Point 8 — pure submarine cable model, no land borders except the merges declared in landmass_groups.json",
  "unreachable_baseline_pairs": 1094,
  "landmass_groups_file": "data/landmass_groups.json",
  "warnings": [
    {
      "type": "inferred_edge",
      "landing_point_id": "cancn-mexico",
      "cable_id": "america-movil-submarine-cable-system-1-amx-1",
      "detail": "no segment endpoint and no vertex within 50 km; attached via an inferred edge to the nearest matched landing point of the same cable (one of 7 verified cases, see 003a-snapping-trefferquote.md)"
    },
    {
      "type": "high_intra_group_latency",
      "group": "United States (mainland)",
      "modelled_latency_ms": 69.7,
      "threshold_ms": 30,
      "detail": "one of 6 automatically detected groups above the threshold, see Point 2"
    }
  ],
  "nodes": { "...": "see Point 6" },
  "edges": [ "...": "see Point 6" ],
  "adjacency": { "...": "see Point 6" },
  "edge_index": { "...": "see Point 6" },
  "cables": { "...": "see Point 6" }
}
```

**The most important, easiest-to-miss point here:** For a scenario link from today to
still show the same thing in five years, **IDs must stay stable**, even though the
artifact is rebuilt weekly. Hence: **all IDs are slugs derived from TeleGeography's own
stable identifiers** (`cable.id`, `landing_point.id`) — never array indices or
order-dependent numbers. A new build can add nodes and edges (new cables go into
service), but existing IDs don't shift. `var-cut_cable=marea` remains valid even if the
build has changed between two calls — just potentially against slightly different
baseline numbers (`baseline_pair_path_count`, etc.), which is honestly appropriate:
today's reality is not the reality of five years from now.

`warnings` is simultaneously the technical safeguard *and* ammunition for Principle 4
("the model is inspectable") — the build reports its own uncertainties instead of
silently hiding them.

**Open question, deliberately not decided here:** whether, in addition to the
normalized graph, the raw upstream payloads are also versioned per build run (e.g., as
a build artifact attachment or a separate weekly snapshot commit), so that the
**derivation** of a historical graph state can also be traced, not just its result.
That's a build-process question for Phase B, not a schema question — but it does affect
whether `sources` should later be extended with a content hash/commit reference.

---

## 8. Landlocked Countries — Option A Confirmed, `scope_note` Tightened

**Option A adopted.** But the original wording was too narrow: it described the
problem as "landlocked countries are missing," when in fact **any** purely terrestrial
land connection between two countries is missing — even between two coastal countries
that each have their own landing points. Germany↔France has no edge in this graph,
even though both have coastal access; the only land connections that exist at all are
the three curated bridges from Point 1 (and those are explicitly marked as an
exception, not intended as general border modeling). This is not a side effect of the
~44 landlocked states, but the fundamental statement of the whole schema: **this is a
submarine cable model.** Any land connection that doesn't run via a submarine cable
doesn't exist — landlocked countries are just the most visible, not the only, case of
this.

**`scope_note` reworded accordingly, prominent rather than a footnote:**

> This model represents submarine cable connectivity only. Any purely land-based
> connection between two countries is missing — even between neighboring countries
> with their own landing points (e.g., Germany↔France). The only exception are the
> merges declared in `data/landmass_groups.json` (see Point 1, currently USA, Canada,
> Australia) to preserve intra-country connectivity for a few large countries — not
> general border modeling, and not a separate edge type: these connections arise as
> perfectly ordinary spanning-tree edges. The ~44 landlocked states with no coastal
> access at all are the extreme case of this boundary, not the only one: they simply
> have no node in the graph at all.

**Problem, concretely:** Roughly 44 landlocked states worldwide (the commonly cited
number — Switzerland, Austria, Bolivia, Kazakhstan, Rwanda, Chad, Mongolia, etc.) have
no coastline and thus no TeleGeography landing point. Without an additional measure,
they simply don't exist in the graph — no node, no edge, no scenario can reach them or
originate from them.

**Option B — terrestrial neighbor edges.** Every landlocked-state hub gets a
`terrestrial` edge to the hub of every country it shares a land border with, weighted
the same way as in Point 2 (great-circle between hub centers × fiber formula). Possible
auth-free source for border adjacency: **CIA World Factbook**, "Land boundaries" field
per country (public-domain US government work) or **Natural Earth** vector data
(`ne_110m_admin_0_countries`, public domain) — both provide plain border pairs (~300
worldwide), could be curated once as a small static reference file and committed, no
new live API call, no operational risk.

**Cost of Option B:** a second layer of unmeasured, synthetic edges (land-hub to
land-hub across the border) in addition to the already synthetic landing-point-to-hub
layer from Point 2. Multi-transit countries (a landlocked state bordering several
coastal countries) need an additional rule for which border(s) count.

**Proposal (not a unilateral decision):** Option A for this schema, Option B deferred
as a named, source-backed extension until the AS/IXP layer (step 6 onward), where
transit relationships would be represented from real data (RIPEstat/CAIDA) rather than
geographically estimated anyway — the actually interesting question for a landlocked
country ("what does Switzerland depend on if a cable is cut?") is a question of AS
transit relationships anyway, not physical cable topology. Adding a second layer of
invented edges now would stack two unmeasured assumptions on top of each other before
the first one (cluster-hub star topology from Point 1/2) has even been checked live.
**But:** please explicitly confirm or prefer Option B — this is a decision that affects
the narratability of the finished dashboard, not just the technical side.

---

## Size Budget (recalculated, round 3)

**Correction to the expectation from the brief:** "531 vertex splits produce 531
additional edges" was a plausible but too-simple back-of-envelope calculation — the
chain formation from Point 3a doesn't add edges 1:1 per split (multiple splits on the
same segment share edges in the chain; the new branch fallback from Point 3a in turn
adds some that didn't appear in either calculation). The actual number comes from the
real chain-formation run across all 697 cables, not from the upfront estimate:

| Part | Count | ≈ bytes/entry | ≈ total |
|---|---|---|---|
| `nodes` (landing_point) | 1,922 | 110 | 211 KB |
| `nodes` (country_hub) | 189 (landmass groups, see Point 1) | 90 | 17 KB |
| `edges` (submarine, `polyline_arc`) | 1,581 | 190 | 300 KB |
| `edges` (submarine, `great_circle_chord` — Tier 3+4, see Point 3a) | 638 | 180 | 115 KB |
| `edges` (terrestrial) | 1,922 | 170 | 327 KB |
| `adjacency` | 2,111 nodes, avg. 3.92 edges | ~5/ref | 41 KB |
| `edge_index` | 4,141 | 35 | 145 KB |
| `cables` | 697 (unique cables, see Point 3) | 107 | 75 KB |
| **Total (uncompressed)** | | | **≈ 1.23 MB** |

Matches the expectation from the brief (~1.25 MB) almost exactly — confirmed by real
chain formation, not by the original addition assumption. **Still clearly under the
1.5 MB budget.**

**Phase B addendum (real build run, after the three bugfixes of 2026-08-03):** The
actual artifact size is **1,713.7 KB uncompressed** — above the 1.5 MB line below,
because the upfront estimate had under-budgeted `id` strings and
`baseline_pair_path_count` per edge (real average ≈ 253 bytes/edge at 4,229 edges, not
the 170–190 above). **No need to sharpen the data structure:** gzip yields 287 KB,
brotli 176 KB — both clearly within the target corridor of 250–400 KB set below, and it
is precisely the compressed number that is the actual operating criterion (CDN
transfer, not the raw byte count in the repo). The 1.5 MB budget below remains as an
uncompressed rule-of-thumb size with margin, but is no longer a hard gate — the build
script check still emits a `WARNING` on overshoot, not a `SystemExit`.

**Budget: ≤ 1.5 MB uncompressed (rule-of-thumb size, see addendum above).** The current
calculation (~1.23 MB) still leaves room for new cables until the next redesign. Over
`raw.githubusercontent.com` with gzip/brotli (standard for JSON responses), the actual
transferred size still lands roughly at 250–400 KB — the artifact is loaded once per
dashboard session, not per query, so no volume problem even under parallel voting-week
load (static file via GitHub CDN, no rate-limit vector like live APIs).

**Levers, should the budget get tight after all:** round coordinates to 4 decimal
places (≈11 m precision, more than enough), `distance_km` to 1, `latency_ms` to 2
decimal places — both already factored into the estimate above.

---

## Summary of Decisions

| # | Decision |
|---|---|
| 1 | **`data/landmass_groups.json`** (3 entries: USA, Canada, Australia) fully replaces `data/bridges.json` — 2,000-km clustering becomes a build check instead of a decision-maker, reports deviating fragmentation as a build error instead of silently missing it. Result: **189 hubs** (no longer 192); the three old bridges arise as normal, more precise MST edges (e.g., USA: 2,120.7 km instead of 5,281.2 km curated), no separate edge type needed anymore. The 2,000-km threshold remains a **convention within a 47-km window**, to be stated openly in the math panel |
| 2 | Terrestrial edges as a spanning tree (MST) instead of a star, edge count unchanged (1,922). With the merged landmass groups, the USA group (142 points) is now the extreme case (13,944.9 km / 69.7 ms modelled intra-group latency), ahead of Russia. Automatic `warnings` entries from 30 ms up (6 groups affected), plus mandatory sentence on the spanning tree's lack of redundancy |
| 3 | Matching algorithm (endpoint → vertex split → inferred) **approved as final, unchanged** |
| 3a | **New:** chain formation explicitly specified (sort by arc-length position, chain consecutively) — reveals a fourth fallback (branch fallback, 631 cases across 195 cables for landing points without a chain partner on their segment), without which `unreachable_baseline_pairs` could not have been computed |
| 4 | `distance_km` = arc length along the cable geometry for `submarine` edges with a real polyline (median ratio to straight-line distance 1.06, p95 1.62), great-circle chord for `terrestrial` and for edges without a geometric basis (Tier 3/4); origin explicit in the `length_source` field |
| 5 | Stage 3 baseline as `baseline_pair_path_count` per edge — **approved as final, unchanged**. `unreachable_baseline_pairs` now actually computed: **1,094 of 17,205 country pairs (6.4%)**, 6 isolated countries, all plausible (Caspian Sea, small Pacific/South Atlantic systems) — below the stop threshold of 10 |
| 6 | `nodes`/`adjacency`/`edge_index`/`cables` as keyed objects, `edges` as an array — **approved as final, unchanged** |
| 7 | IDs are stable TeleGeography slugs, never indices — **approved as final, unchanged** |
| 8 | Option A confirmed, `scope_note` tightened — **approved as final, unchanged** |
| Budget | ≤ 1.5 MB uncompressed, recalculated to **~1.23 MB** (previously ~1.15 MB, due to real chain formation instead of segment counting — confirms the ~1.25 MB expectation from the brief), ~260–420 KB estimated over the wire |

This summary table fully replaces the one from round 2 — Points 1, 2, 3a, 4, and 5 have
changed in content or numbers, 3, 6, 7, 8 carry over unchanged from round 2 into this
round.
