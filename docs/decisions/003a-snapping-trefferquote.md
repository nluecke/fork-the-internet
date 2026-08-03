# 003a — Snapping Match Rate (Verification Before the Generator)

**Date:** 2026-08-09, updated in review round 2 (matching algorithm corrected).
**Belongs to:** `003-graph-schema.md`, Point 3 (cable → edges). Point 3 itself (which
landing point belongs to which segment/vertex — Tiers 1–3 below) was finally approved
in review round 3 and carried over unchanged. What changed in round 3 is one layer
above that: **how** the assignments determined here actually become edges
(ordering/chaining, plus a fourth fallback for landing points with no chain partner) —
that's in `003-graph-schema.md`, Point 3a, not here. The numbers in this document
(Tier 1/2/3 distribution) remain valid.
**Method:** all 697 unique cables individually queried via `GET
https://www.submarinecablemap.com/api/v3/cable/{id}.json` (697/697 successful,
0 errors), checked against `data/samples/telegeography-cable-geo.json` (geometry) and
`data/samples/telegeography-landing-point-geo.json` (coordinates). Script and raw data
are not in the repo (a verification run, not a build artifact) — the result is fully
documented here, reproducible with the same API.

**First correction against `003-graph-schema.md`:** the schema document counted
"718 cables". That is the number of GeoJSON *features* in `cable-geo.json` — 21 cables
are split across multiple features (the same `properties.id` appears more than once,
each with its own `MultiLineString`). The number of **unique cables** (and hence of
`cables` index entries in the artifact) is **697**, not 718. IDs in `cable-geo.json` and
in the cable detail endpoint match exactly (697 = 697, no difference either way).

---

## Review round 2: matching algorithm corrected

The numbers below replace the first version. The original counting algorithm
("independent nearest-match per landing point") implicitly assumed a bijection between
segment endpoints and landing points. But there are 3,860 segment endpoints against only
3,184 declared pairs — a landing point where a cable passes through is the endpoint of
**two** segments; that's not the exception but the normal case for pass-through
stations. Corrected to true many-to-one matching (see `003-graph-schema.md`, Point 3, for
the full algorithm): each endpoint gets exactly one landing point, a landing point may
receive multiple endpoints.

## Result: 99.8% → still 99.8% clean, but a different distribution

| Category | Count (corrected) | Share | Count (first, flawed count) |
|---|---|---|---|
| Tier 1: endpoint match (≤ 50 km) | 2,646 | 83.1% | 2,772 |
| Tier 2: vertex split (interior line point ≤ 50 km) | 531 | 16.7% | 405 |
| **clean (Tier 1 + 2)** | **3,177** | **99.8%** | 3,177 |
| Tier 3: inferred (edge to the nearest already-matched landing point) | 7 | 0.2% | 7 |
| no match possible | 0 | 0% | 0 |
| **Total (declared cable↔landing-point pairs)** | **3,184** | 100% | 3,184 |

The overall rate (99.8% clean) stays identical — but significantly more cases now
correctly land in the vertex tier instead of incorrectly passing as an endpoint match.
Reason: in the old algorithm, once a landing point was marked "taken," it could no
longer be assigned to any further endpoint — for pass-through stations (two endpoints at
the same location), that incorrectly assigned the second endpoint to a more distant,
wrong landing point that happened to still be "free," instead of correctly landing in
the vertex tier or at the same (now doubly-used) landing point. The 7 `inferred_edge`
cases stayed identical (same 3 cables, see below) — the correction changes nothing there,
since there was no contention case to begin with.

**Stress test, not originally requested:** `apcn-2` (Singapore–Japan trunk, 52 segments)
came out with 8 of 10 landing points completely unmatched under the first, flawed
algorithm. With the corrected vertex tier: all 8 match to within 0.0–1.4 km as interior
line points of two long trunk segments (Hong Kong, Shantou, Busan, Taipei etc. as
genuine intermediate stations). Without the vertex tier this would have been a highly
visible error on one of the largest cables in the dataset — the best evidence that Tier
2 is not a nice-to-have.

**The 7 `inferred_edge` cases, unchanged from the first count:**

| Cable | Landing point |
|---|---|
| `america-movil-submarine-cable-system-1-amx-1` | `cancn-mexico` |
| `eaufon-2` | `kangiqsujuaq-qc-canada` |
| `eaufon-2` | `puvirnituq-qc-canada` |
| `trans-global-cable-system-tgcs` | `balikpapan-indonesia` |
| `trans-global-cable-system-tgcs` | `makassar-indonesia` |
| `trans-global-cable-system-tgcs` | `manado-indonesia` |
| `trans-global-cable-system-tgcs` | `surabaya-indonesia` |

Only 3 cables affected, all with a plausible explanation: `eaufon-2` and
`trans-global-cable-system-tgcs` are multi-landing-point systems with simplified public
geometry; `cancn-mexico` likely sits on a spur that isn't drawn separately in the
geometry.

No cable is entirely unmatched, no missing geometry, no missing coordinate — across 697
of 697 cables, every declared landing point ends up with a place in the graph.

---

## Ambiguity check: structurally resolved by many-to-one matching

**Question:** do two declared landing points of the *same* cable ever lie within 50 km
of each other? If so, a single match attempt could assign an endpoint to the wrong one
of the two.

**Result: yes, for 210 of 697 cables (30.1%)** — more often than expected. Examples:
`5-villages-6-islands` (13 ambiguous pairs), `au-aleutian` (8), `aqualink` (6), `aurora`
(7), `2africa` (3), plus 205 more cables with mostly 1–2 pairs.

**Solved, not just scoped.** The fix proposed in round 1 — greedy matching, all
candidate pairs sorted by distance, assigned ascending — is now part of the corrected
algorithm itself (Tier 1) and was tested precisely against the examples named in the
review:

| Cable | Declared | Tier 1 | Tier 2 | Tier 3 | Unmatched |
|---|---|---|---|---|---|
| `2africa` | 50 | 49 | 1 | 0 | 0 |
| `5-villages-6-islands` | 9 | 8 | 1 | 0 | 0 |
| `au-aleutian` | 14 | 12 | 2 | 0 | 0 |
| `aqualink` | 11 | 10 | 1 | 0 | 0 |
| `aurora` | 12 | 12 | 0 | 0 | 0 |

For all five: complete, unambiguous assignment, no open cases. The earlier residual-risk
framing ("labeling risk, not an accuracy risk") was correctly judged — with the
corrected algorithm it is now resolved, not just bounded.

---

## Additional finding: the country field is consistent

Checked in passing, since it's derivable from the same data: the `country` field from
the cable details is **contradiction-free** for all 1,922 landing points that appear in
at least one cable — no two cables state different countries for the same
`landing_point.id`. This is the data foundation for the country-hub redefinition in
Point 1 of the main document; without this consistency check, per-country clustering
would not have been reliable.
