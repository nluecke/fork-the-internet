#!/usr/bin/env python3
"""Build the normalized topology artifact for "Fork the Internet".

Pulls live submarine-cable topology from TeleGeography, builds the
physical/country graph described in docs/decisions/003-graph-schema.md
(final after review round 3), and writes data/graph.json.

Run: python3 scripts/build_graph.py
"""

import json
import math
import re
import sys
import time
import heapq
import collections
import datetime
import pathlib
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

CABLE_GEO_URL = "https://www.submarinecablemap.com/api/v3/cable/cable-geo.json"
LANDING_POINT_GEO_URL = "https://www.submarinecablemap.com/api/v3/landing-point/landing-point-geo.json"
CABLE_DETAIL_URL_TMPL = "https://www.submarinecablemap.com/api/v3/cable/{id}.json"

TOLERANCE_KM = 50
CLUSTER_THRESHOLD_KM = 2000
SPEED_OF_LIGHT_KM_S = 299792.458
FIBER_INDEX_FACTOR = 0.667
FIBER_SPEED_KM_S = SPEED_OF_LIGHT_KM_S * FIBER_INDEX_FACTOR
HIGH_LATENCY_WARNING_MS = 30.0
ARTIFACT_BUDGET_KB = 1536  # 1.5 MB, docs/decisions/003-graph-schema.md
SANITY_MAX_ISOLATED_COUNTRIES = 10

# RIPE Atlas validation layer (Stage 2): a curated set of real anchor-mesh ping
# results, compared against the modelled physics-only latency_baseline. Curated,
# not exhaustive -- see build_atlas_validation() docstring for why.
RIPE_ATLAS_API = "https://atlas.ripe.net/api/v2"
ATLAS_COUNTRY_ISO = {
    "United States": "US", "Japan": "JP", "Germany": "DE", "Brazil": "BR",
    "Australia": "AU", "South Africa": "ZA", "India": "IN", "Singapore": "SG",
    "United Kingdom": "GB", "France": "FR", "Chile": "CL", "Spain": "ES",
    "New Zealand": "NZ", "Kenya": "KE", "Nigeria": "NG", "Sweden": "SE",
}
# The "first active anchor found per country" heuristic below picks a US anchor in
# Guam by default (technically US-coded, geographically nowhere near representative
# of "United States" -- inflated every US pair by 100+ ms in a live check). Override
# to a mainland hub instead. No other country in the curated set needed this.
ATLAS_ANCHOR_OVERRIDE = {"US": 1838}  # Ashburn, VA
ATLAS_PAIRS = [
    ("United States", "Japan"), ("United States", "Germany"), ("United States", "Brazil"),
    ("United States", "United Kingdom"), ("Japan", "Australia"), ("Japan", "Singapore"),
    ("Germany", "France"), ("Germany", "South Africa"), ("Germany", "India"),
    ("Brazil", "Chile"), ("Brazil", "Spain"), ("Australia", "New Zealand"),
    ("Australia", "Singapore"), ("South Africa", "Kenya"), ("South Africa", "Nigeria"),
    ("India", "Singapore"), ("India", "Sweden"),
]

# Historical event validation (Stage 4): real cable-cut incidents, modelled against
# TODAY's topology to see whether the reachability model would have predicted the
# real-world impact. Cable IDs, dates, and real_impact text are curated from
# contemporaneous reporting (source URL per event) -- not fabricated, not fetched
# live (these are settled historical facts, re-fetching them weekly would add
# network I/O for data that never changes). See build_historical_events() for the
# model-prediction side.
HISTORICAL_EVENTS = [
    {
        "id": "red-sea-2024",
        "name": "Red Sea cable cuts",
        "date": "2024-02-24",
        "cables": ["seacomtata-tgn-eurasia", "europe-india-gateway-eig", "asia-africa-europe-1-aae-1"],
        "cause": (
            "Widely attributed to the drifting, anchor-dragging MV Rubymar, a UK-owned "
            "cargo ship disabled by a Houthi missile strike on 2024-02-18 that later "
            "sank -- the leading theory, not confirmed fact."
        ),
        "real_impact": (
            "Disrupted an estimated 25-70% of Europe-Asia traffic on some routes; "
            "measurable degradation reported in East Africa (Tanzania, Kenya, Uganda, "
            "Mozambique), the Middle East (UAE, Djibouti), and Southeast Asia (Vietnam) "
            "-- a rerouting and congestion story, not a reported full blackout anywhere."
        ),
        "source": "https://www.kentik.com/blog/what-caused-the-red-sea-submarine-cable-cuts/",
    },
    {
        "id": "west-africa-2024",
        "name": "West Africa cable cuts",
        "date": "2024-03-14",
        "cables": ["west-africa-cable-system-wacs", "africa-coast-to-europe-ace", "sat-3wasc", "mainone"],
        "cause": (
            "Suspected undersea landslide in the canyon off Abidjan, Cote d'Ivoire; "
            "MainOne's initial assessment pointed to seismic activity. Equiano landed "
            "nearby but was not affected, and served as an alternate route."
        ),
        "real_impact": (
            "13 West African countries affected per the Internet Society's outage "
            "report. Cote d'Ivoire measured at roughly 4% of expected connectivity "
            "(NetBlocks) despite Equiano remaining intact -- degraded, not fully cut "
            "off, for Cote d'Ivoire specifically. Liberia, Benin, Ghana, and Burkina "
            "Faso were also described as badly affected."
        ),
        "source": "https://www.internetsociety.org/resources/doc/2024/2024-west-africa-submarine-cable-outage-report/",
    },
    {
        "id": "tonga-2022",
        "name": "Tonga volcanic eruption",
        "date": "2022-01-15",
        "cables": ["tonga-cable", "tonga-domestic-cable-extension-tdce"],
        "cause": (
            "The Hunga Tonga-Hunga Ha'apai volcanic eruption severed both the "
            "international cable to Fiji and the inter-island domestic extension in "
            "the same event."
        ),
        "real_impact": (
            "Near-total national internet blackout for 38 days -- the international "
            "link was restored 2022-02-22. The domestic inter-island cable took far "
            "longer: 18 months, restored 2023-07-12."
        ),
        "source": "https://blog.cloudflare.com/tonga-internet-outage",
        "note": (
            "Tonga's second international route -- the Hawaiki cable's Tu'i Vava'u "
            "branch to Vava'u -- landed 2026-03-18 and went live 2026-05-26, well "
            "after the 2022 eruption. This model reflects today's topology, so it may "
            "show Tonga as still reachable through that new branch -- a resilience "
            "gap the real 2022 blackout fell into that no longer exists today, not a "
            "modelling error."
        ),
    },
]

SCHEMA_VERSION = "1.0.0"
TELEGEOGRAPHY_LICENSE = "CC BY-SA 4.0"


# --------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------

def gc_dist(a, b):
    """Great-circle distance in km between (lon, lat) pairs."""
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def latency_ms(distance_km):
    return distance_km / FIBER_SPEED_KM_S * 1000.0


def to_cartesian(lon, lat):
    lam, phi = math.radians(lon), math.radians(lat)
    return (math.cos(phi) * math.cos(lam), math.cos(phi) * math.sin(lam), math.sin(phi))


def to_lonlat(x, y, z):
    n = math.sqrt(x * x + y * y + z * z)
    x, y, z = x / n, y / n, z / n
    return math.degrees(math.atan2(y, x)), math.degrees(math.asin(z))


def spherical_centroid(points):
    """points: list of (id, lon, lat). Antimeridian-safe centroid (003, Point 1)."""
    xs = ys = zs = 0.0
    for _, lon, lat in points:
        x, y, z = to_cartesian(lon, lat)
        xs += x
        ys += y
        zs += z
    return to_lonlat(xs, ys, zs)


def cumulative_arc_lengths(line):
    cum = [0.0]
    for i in range(1, len(line)):
        cum.append(cum[-1] + gc_dist(tuple(line[i - 1]), tuple(line[i])))
    return cum


def single_linkage_clusters(points, threshold_km):
    """points: list of (id, lon, lat). Union-find pairwise merge <= threshold."""
    n = len(points)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if gc_dist((points[i][1], points[i][2]), (points[j][1], points[j][2])) <= threshold_km:
                union(i, j)

    groups = collections.defaultdict(list)
    for i in range(n):
        groups[find(i)].append(points[i])
    return list(groups.values())


def mst_edges(points):
    """points: list of (id, lon, lat). Prim's algorithm. Returns (weight, i, j)."""
    n = len(points)
    if n <= 1:
        return []
    in_tree = [False] * n
    min_dist = [float("inf")] * n
    min_from = [-1] * n
    min_dist[0] = 0
    edges = []
    for _ in range(n):
        u = min(range(n), key=lambda x: (in_tree[x], min_dist[x]))
        in_tree[u] = True
        if min_from[u] != -1:
            edges.append((min_dist[u], min_from[u], u))
        for v in range(n):
            if not in_tree[v]:
                d = gc_dist((points[u][1], points[u][2]), (points[v][1], points[v][2]))
                if d < min_dist[v]:
                    min_dist[v] = d
                    min_from[v] = u
    return edges


def tree_diameter_km(n, edges):
    """edges: list of (weight, i, j) local indices. Double-sweep on the tree."""
    if n <= 1:
        return 0.0
    adj = collections.defaultdict(list)
    for w, i, j in edges:
        adj[i].append((j, w))
        adj[j].append((i, w))

    def farthest(src):
        dist = {src: 0.0}
        stack = [src]
        while stack:
            u = stack.pop()
            for v, w in adj[u]:
                if v not in dist:
                    dist[v] = dist[u] + w
                    stack.append(v)
        far_node = max(dist, key=dist.get)
        return far_node, dist[far_node]

    a, _ = farthest(0)
    _, d = farthest(a)
    return d


# --------------------------------------------------------------------------
# Fetch
# --------------------------------------------------------------------------

def fetch_json(url, timeout=15, retries=2):
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "golden-grot-2027-build/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last_err}")


def fetch_cable_geo():
    return fetch_json(CABLE_GEO_URL, timeout=30)


def fetch_landing_points():
    return fetch_json(LANDING_POINT_GEO_URL, timeout=30)


def fetch_all_cable_details(cable_ids, log=print):
    results = {}
    failures = []
    total = len(cable_ids)
    for i, cid in enumerate(sorted(cable_ids)):
        try:
            results[cid] = fetch_json(CABLE_DETAIL_URL_TMPL.format(id=cid), timeout=10)
        except Exception as e:
            failures.append((cid, str(e)))
        if (i + 1) % 100 == 0:
            log(f"  cable details: {i + 1}/{total}")
        time.sleep(0.12)
    if failures:
        raise RuntimeError(f"{len(failures)} cable-detail fetches failed: {failures[:10]}")
    return results


# --------------------------------------------------------------------------
# Matching + chaining (003, Point 3 + 3a)
# --------------------------------------------------------------------------

def dedupe_consecutive_vertices(line):
    """Collapse consecutive duplicate vertices in a polyline.

    TeleGeography's raw geometry occasionally repeats a vertex 2-3 times in a row
    (observed on australia-japan-cable-ajc, segment 2, at the Guam landing --
    presumably marking a branching unit). Left as-is, two distinct landing points
    near that spot can vertex-split onto separate copies of the same point and
    chain into a spurious zero-length edge despite being several km apart in
    reality. Dropping the duplicates doesn't change any real arc length (a
    zero-distance hop contributes nothing to the cumulative sum).
    """
    if not line:
        return line
    out = [line[0]]
    for pt in line[1:]:
        if tuple(pt) != tuple(out[-1]):
            out.append(pt)
    return out


def match_and_chain_cable(cid, cable_detail, lines_by_cable, lp_coords):
    """Returns (submarine_edges, warnings) for one cable.

    submarine_edges: list of dicts with from/to/distance_km/length_source/cable_id/segment_index
    Tier 1 (endpoint) + Tier 2 (vertex-split) use polyline arc length.
    Tier 3 (inferred, no match at all) + Tier 4 (branch fallback, lone placement) use
    great-circle chord, since no shared polyline exists for those pairs.
    """
    declared = cable_detail.get("landing_points", [])
    lines = [dedupe_consecutive_vertices(line) for line in lines_by_cable.get(cid, [])]
    lp_ids = [lp["id"] for lp in declared if lp["id"] in lp_coords]
    warnings = []
    if not lines or not lp_ids:
        return [], warnings

    seg_cum = [cumulative_arc_lengths(line) for line in lines]

    endpoints = []  # (seg_idx, vidx, coord)
    for seg_idx, line in enumerate(lines):
        endpoints.append((seg_idx, 0, tuple(line[0])))
        endpoints.append((seg_idx, len(line) - 1, tuple(line[-1])))

    # Tier 1: endpoints, many-to-one (an endpoint gets exactly one LP; an LP may serve
    # multiple endpoints -- pass-through stations).
    candidates = []
    for ei, (seg_idx, vidx, ecoord) in enumerate(endpoints):
        for lpid in lp_ids:
            d = gc_dist(ecoord, lp_coords[lpid])
            if d <= TOLERANCE_KM:
                candidates.append((d, ei, lpid))
    candidates.sort()
    endpoint_assignment = {}
    covered = set()
    for d, ei, lpid in candidates:
        if ei in endpoint_assignment:
            continue
        endpoint_assignment[ei] = lpid
        covered.add(lpid)

    seg_placements = collections.defaultdict(list)  # seg_idx -> [(vidx, lpid)]
    for ei, (seg_idx, vidx, _) in enumerate(endpoints):
        if ei in endpoint_assignment:
            seg_placements[seg_idx].append((vidx, endpoint_assignment[ei]))

    uncovered = [x for x in lp_ids if x not in covered]

    # Tier 2: interior vertices (vertex-split), many-to-one.
    all_vertex_positions = []
    for seg_idx, line in enumerate(lines):
        for vidx, pt in enumerate(line):
            all_vertex_positions.append((seg_idx, vidx, tuple(pt)))
    pos_lookup = {(seg_idx, vidx): pos_i for pos_i, (seg_idx, vidx, _) in enumerate(all_vertex_positions)}
    vcandidates = []
    for lpid in uncovered:
        lpc = lp_coords[lpid]
        for pos_i, (seg_idx, vidx, vc) in enumerate(all_vertex_positions):
            d = gc_dist(lpc, vc)
            if d <= TOLERANCE_KM:
                vcandidates.append((d, lpid, pos_i))
    vcandidates.sort()
    # A Tier-1 endpoint match already occupies its vertex position -- without this,
    # a second, genuinely distinct landing point (several km away) can vertex-split
    # onto that same position, and the two collapse into a zero-length chained edge
    # once sorted by arc-length position (found live: Guam tanguisson-point/tumon-bay,
    # 3.6 km apart, both landing on one segment endpoint).
    claimed_positions = {pos_lookup[(endpoints[ei][0], endpoints[ei][1])] for ei in endpoint_assignment}
    for d, lpid, pos_i in vcandidates:
        if lpid in covered or pos_i in claimed_positions:
            continue
        seg_idx, vidx, _ = all_vertex_positions[pos_i]
        seg_placements[seg_idx].append((vidx, lpid))
        claimed_positions.add(pos_i)
        covered.add(lpid)

    still_uncovered = [x for x in lp_ids if x not in covered]

    # Emit submarine edges: per segment, sort placements by vertex index (= arc-length
    # position), consecutive pairs become edges, weight = polyline arc length (003a,
    # Point 3a).
    submarine_edges = []
    connected = set()
    for seg_idx, placements in seg_placements.items():
        placements = sorted(set(placements))
        cum = seg_cum[seg_idx]
        for k in range(len(placements) - 1):
            v1, lp1 = placements[k]
            v2, lp2 = placements[k + 1]
            if lp1 == lp2:
                continue
            w = cum[v2] - cum[v1]
            submarine_edges.append({
                "from": lp1, "to": lp2, "distance_km": round(w, 1),
                "length_source": "polyline_arc", "cable_id": cid, "segment_index": seg_idx,
            })
            connected.add(lp1)
            connected.add(lp2)

    # Tier 3: inferred -- no vertex/endpoint match at all. Chord to nearest covered LP.
    for lpid in still_uncovered:
        if not covered:
            continue
        lpc = lp_coords[lpid]
        best = min(covered, key=lambda o: gc_dist(lpc, lp_coords[o]))
        w = gc_dist(lpc, lp_coords[best])
        submarine_edges.append({
            "from": lpid, "to": best, "distance_km": round(w, 1),
            "length_source": "great_circle_chord", "cable_id": cid, "segment_index": None,
            "inferred": True,
        })
        warnings.append({
            "type": "inferred_edge", "landing_point_id": lpid, "cable_id": cid,
            "detail": "no segment endpoint and no vertex within 50 km; edge to the nearest matched landing point of the same cable",
        })
        covered.add(lpid)
        connected.add(lpid)
        connected.add(best)

    # Tier 4: branch fallback -- matched (tier1/tier2) LPs with no pairing partner on
    # their own segment (e.g. a short spur off an undeclared branching unit). Chord to
    # nearest already-connected LP on the same cable (003, Point 3a).
    orphans = [lpid for lpid in covered if lpid not in connected]
    if orphans and not connected:
        # Every declared landing point on this cable sits alone on its own segment --
        # a pure multi-branch topology with no segment ever shared by two of them.
        # There is then no "already chained" neighbor for the loop below to attach
        # to, so it would otherwise spin through all orphans without ever connecting
        # one (found live: equiano, bifrost, echo and 33 other cables end up with
        # zero edges, no warning, fully silent). Bootstrap with the lexicographically
        # first orphan as a deterministic seed (Principle 3).
        seed = min(orphans)
        connected.add(seed)
        orphans = [x for x in orphans if x != seed]
    remaining = list(orphans)
    guard = 0
    while remaining and guard < 10000:
        guard += 1
        lpid = remaining.pop(0)
        targets = [o for o in connected if o != lpid]
        if not targets:
            if not remaining:
                break
            remaining.append(lpid)
            continue
        lpc = lp_coords[lpid]
        best = min(targets, key=lambda o: gc_dist(lpc, lp_coords[o]))
        w = gc_dist(lpc, lp_coords[best])
        submarine_edges.append({
            "from": lpid, "to": best, "distance_km": round(w, 1),
            "length_source": "great_circle_chord", "cable_id": cid, "segment_index": None,
            "branch_fallback": True,
        })
        connected.add(lpid)

    unmatched = [x for x in lp_ids if x not in covered]
    for lpid in unmatched:
        warnings.append({
            "type": "unmatched_landing_point", "landing_point_id": lpid, "cable_id": cid,
            "detail": "no match found in Tier 1-4; landing point is dropped",
        })

    return submarine_edges, warnings


# --------------------------------------------------------------------------
# Landmass groups (003, Point 1)
# --------------------------------------------------------------------------

def load_landmass_groups():
    path = REPO_ROOT / "data" / "landmass_groups.json"
    with open(path) as f:
        data = json.load(f)
    return data.get("force_same_landmass", []), data.get("accepted_separate", [])


def find_cluster_containing(clusters, point_id):
    for i, c in enumerate(clusters):
        if any(p[0] == point_id for p in c):
            return i
    return None


def build_landmass_groups(by_country, force_same_landmass, accepted_separate):
    """Returns final_groups: country -> list of point-lists (each a landmass group / hub).

    Every country whose threshold clustering yields more than one group after applying
    force_same_landmass must be declared in accepted_separate -- otherwise the build
    fails loudly instead of silently shipping an undeclared split (003, Point 1: "if
    Argentina splits apart in the future, a fourth bridge silently goes missing").
    """
    final_groups = {}
    errors = []
    accepted_countries = {e["country"] for e in accepted_separate}

    for country, pts in by_country.items():
        raw_clusters = single_linkage_clusters(pts, CLUSTER_THRESHOLD_KM)
        parent = list(range(len(raw_clusters)))

        def find(x, parent=parent):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for entry in force_same_landmass:
            if entry["country"] != country:
                continue
            a, b = entry["anchor_points"]
            ia = find_cluster_containing(raw_clusters, a)
            ib = find_cluster_containing(raw_clusters, b)
            if ia is None or ib is None:
                errors.append(f"{country}: anchor point not found ({a!r}, {b!r}) -- data may have changed, update landmass_groups.json")
                continue
            ra, rb = find(ia), find(ib)
            if ra == rb:
                errors.append(f"{country}: anchors {a!r}/{b!r} already in the same cluster -- override may be stale, consider removing")
                continue
            parent[ra] = rb

        groups = collections.defaultdict(list)
        for i, c in enumerate(raw_clusters):
            groups[find(i)].extend(c)
        final_groups[country] = list(groups.values())

        if len(final_groups[country]) > 1 and country not in accepted_countries:
            errors.append(
                f"{country}: {len(final_groups[country])} landmass groups after merging, "
                f"but not declared in landmass_groups.json's accepted_separate list -- "
                f"either add a force_same_landmass entry (if this should be one landmass) "
                f"or an accepted_separate entry (if the split is real)"
            )

    if errors:
        raise RuntimeError("landmass_groups build check failed:\n  " + "\n  ".join(errors))

    return final_groups


# --------------------------------------------------------------------------
# Terrestrial edges (003, Point 2)
# --------------------------------------------------------------------------

def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def build_terrestrial_edges(final_groups):
    """Returns (edges, hubs, warnings).

    edges: list of dicts (MST within each group + one hub-attach edge).
    hubs: list of dicts {id, country, lon, lat, member_count}.
    warnings: high_intra_group_latency entries (003, Point 2).

    Hub IDs are `hub__<country-slug>` for the common single-hub case, or
    `hub__<country-slug>__<n>` for the handful of countries with more than one
    landmass group (n assigned by sorting groups on their lexicographically
    smallest member landing-point ID -- itself a stable, content-derived string,
    never insertion/iteration order). A plain incrementing counter here would
    violate 003, Point 7's own stability rule the moment `final_groups`' iteration
    order shifts between builds (e.g. from upstream landing-point ordering changes)
    -- and country/from/to scenario variables built on top of hub IDs (Stage 2)
    make that concretely URL-breaking, not just cosmetic.
    """
    edges = []
    hubs = []
    warnings = []

    for country, groups in final_groups.items():
        country_slug = slugify(country)
        ordered_groups = sorted(groups, key=lambda g: min(p[0] for p in g))
        multi = len(ordered_groups) > 1
        for group_idx, group in enumerate(ordered_groups):
            hub_id = f"hub__{country_slug}__{group_idx}" if multi else f"hub__{country_slug}"
            n = len(group)
            clon, clat = spherical_centroid(group)
            hubs.append({"id": hub_id, "country": country, "lon": round(clon, 4), "lat": round(clat, 4), "member_count": n})

            if n >= 2:
                mst = mst_edges(group)
                for w, i, j in mst:
                    edges.append({
                        "from": group[i][0], "to": group[j][0], "distance_km": round(w, 1),
                        "length_source": "great_circle_chord",
                    })
                diam = tree_diameter_km(n, mst)
                lat = latency_ms(diam)
                if lat > HIGH_LATENCY_WARNING_MS:
                    warnings.append({
                        "type": "high_intra_group_latency", "group": f"{country} (hub {hub_id})",
                        "modelled_latency_ms": round(lat, 1), "threshold_ms": HIGH_LATENCY_WARNING_MS,
                        "detail": "modelled MST diameter of this landmass group exceeds a real intercontinental reference distance (NY-London ~28.75ms)",
                    })

            nearest = min(group, key=lambda p: gc_dist((p[1], p[2]), (clon, clat)))
            attach_w = gc_dist((nearest[1], nearest[2]), (clon, clat))
            edges.append({
                "from": hub_id, "to": nearest[0], "distance_km": round(attach_w, 1),
                "length_source": "great_circle_chord",
            })

    return edges, hubs, warnings


# --------------------------------------------------------------------------
# Baseline betweenness + unreachable pairs (003, Point 5)
# --------------------------------------------------------------------------

def dijkstra(adj, src, excluded_edges=None):
    dist = {src: 0.0}
    prev = {}
    pq = [(0.0, src)]
    visited = set()
    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        for v, w, edge_key in adj[u]:
            if excluded_edges and edge_key in excluded_edges:
                continue
            nd = d + w
            if v not in dist or nd < dist[v]:
                dist[v] = nd
                prev[v] = (u, edge_key)
                heapq.heappush(pq, (nd, v))
    return dist, prev


def connected_components(nodes_adj):
    """Union-find over the full node graph (landing points + hubs). Returns a dict
    node -> representative id of its component.
    """
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for u, neighbors in nodes_adj.items():
        parent.setdefault(u, u)
        for v, _w, _edge_key in neighbors:
            parent.setdefault(v, v)
            union(u, v)

    return {n: find(n) for n in parent}


def compute_baseline_and_unreachable(nodes_adj, hubs_by_country, edges):
    """Runs one Dijkstra per hub, derives country-pair reachability (min over hub
    combinations) and increments baseline_pair_path_count per edge on each country
    pair's shortest path. Also counts unreachable country pairs and countries
    isolated from the largest connected component (003, Point 5).

    Also returns `pair_records`: one entry per reachable country pair with its
    selected hub pair, full edge path and the set of cables that path touches --
    the exact same pair set baseline_pair_path_count is built from. Stage 3 reroute
    pressure (compute_reroute_pressure) needs this to stay consistent with the
    edge load figures it reports deltas against; recomputing "affected pairs" from
    a different pair set (e.g. the finer all-hub-pairs set behind latency_baseline)
    would report deltas against a baseline that isn't the one being displayed.
    """
    countries = sorted(hubs_by_country.keys())
    all_hubs = [h for hids in hubs_by_country.values() for h in hids]

    dist_from = {}
    prev_from = {}
    for h in all_hubs:
        dist_from[h], prev_from[h] = dijkstra(nodes_adj, h)

    baseline_count = collections.Counter()
    unreachable = 0
    total_pairs = 0
    pair_records = []

    for i in range(len(countries)):
        for j in range(i + 1, len(countries)):
            total_pairs += 1
            ca, cb = countries[i], countries[j]
            best = None
            for ha in hubs_by_country[ca]:
                for hb in hubs_by_country[cb]:
                    d = dist_from[ha].get(hb)
                    if d is not None and (best is None or d < best[0]):
                        best = (d, ha, hb)
            if best is None:
                unreachable += 1
                continue
            _, ha, hb = best
            # walk back the path from hb to ha using prev_from[ha]
            node = hb
            prev = prev_from[ha]
            edge_path = []
            cables = set()
            while node in prev:
                parent, edge_key = prev[node]
                baseline_count[edge_key] += 1
                edge_path.append(edge_key)
                cid = edges[edge_key].get("cable_id")
                if cid is not None:
                    cables.add(cid)
                node = parent
            pair_records.append({"ha": ha, "hb": hb, "edge_path": edge_path, "cables": cables})

    # "Isolated" means no hub of that country sits in the graph's largest connected
    # component -- not merely "unreachable from every other country". A country pair
    # can be its own two-country island (e.g. Azerbaijan/Kazakhstan across the
    # Caspian Sea: connected to each other, disconnected from the rest of the world)
    # without either country being unreachable from *all* others, so a
    # per-country-pair tally alone misses it. Comparing against the true largest
    # component catches that case correctly.
    comp_of = connected_components(nodes_adj)
    comp_sizes = collections.Counter(comp_of.values())
    largest_component = comp_sizes.most_common(1)[0][0] if comp_sizes else None
    isolated_countries = [
        c for c in countries
        if not any(comp_of.get(h) == largest_component for h in hubs_by_country[c])
    ]

    return baseline_count, unreachable, total_pairs, isolated_countries, pair_records


# --------------------------------------------------------------------------
# Stage 3 reroute pressure (unitless, relative -- no fabricated capacity numbers)
# --------------------------------------------------------------------------

REROUTE_PRESSURE_TOP_K = 8


def compute_reroute_pressure(nodes_adj, cables, baseline_count, pair_records, log=print):
    """For every cable, among the country pairs whose baseline shortest path used
    it (pair_records, the exact pair set baseline_pair_path_count is built from --
    see compute_baseline_and_unreachable's docstring), reroutes those pairs around
    the cable and tallies which surviving edges pick up extra load relative to
    their normal baseline_pair_path_count share.

    Deliberately unitless (Principle: no fabricated congestion percentages --
    info_traffic in PeeringDB is a network's volume, not a cable's capacity).
    Reported as "this edge now carries N.NNx its normal path share" -- physically
    grounded in the same betweenness count already shown elsewhere on the
    dashboard, not a capacity claim.

    Only edges whose load increases are kept (unaffected/decreased edges aren't
    "pressure"), capped to the top REROUTE_PRESSURE_TOP_K per cable by ratio to
    bound artifact size. A cable with zero affected pairs (never on any baseline
    shortest path -- redundant by construction) is omitted from the result
    entirely; the dashboard treats a missing key as "no reroute pressure from
    this cut", which is the correct reading.
    """
    affected_by_cable = collections.defaultdict(list)
    for rec in pair_records:
        for cid in rec["cables"]:
            affected_by_cable[cid].append(rec)

    result = {}
    for cable_id, recs in affected_by_cable.items():
        cut_edges = set(cables[cable_id]["edge_indices"])

        before_counter = collections.Counter()
        for rec in recs:
            for edge_key in rec["edge_path"]:
                before_counter[edge_key] += 1

        pairs_by_src = collections.defaultdict(set)
        for rec in recs:
            pairs_by_src[rec["ha"]].add(rec["hb"])

        after_counter = collections.Counter()
        for src, dsts in pairs_by_src.items():
            dist2, prev2 = dijkstra(nodes_adj, src, excluded_edges=cut_edges)
            for dst in dsts:
                if dst not in dist2:
                    continue  # now unreachable -- Stage 1 territory, contributes no load elsewhere
                node = dst
                while node in prev2:
                    parent, edge_key = prev2[node]
                    after_counter[edge_key] += 1
                    node = parent

        entries = []
        for edge_key in set(before_counter) | set(after_counter):
            if edge_key in cut_edges:
                continue
            baseline_load = baseline_count.get(edge_key, 0)
            unaffected_load = baseline_load - before_counter.get(edge_key, 0)
            new_load = unaffected_load + after_counter.get(edge_key, 0)
            if new_load <= baseline_load:
                continue
            ratio = round(new_load / baseline_load, 2) if baseline_load > 0 else None
            entries.append({
                "edge": edge_key, "baseline_load": baseline_load,
                "new_load": new_load, "ratio": ratio,
            })

        if not entries:
            continue
        entries.sort(key=lambda e: (e["ratio"] is None, -(e["ratio"] or 0), -e["new_load"]))
        result[cable_id] = entries[:REROUTE_PRESSURE_TOP_K]

    log(f"  reroute pressure computed for {len(result)}/{len(cables)} cables with affected baseline pairs")
    return result


# --------------------------------------------------------------------------
# Stage 2 latency baseline (precomputed shortest-path latency per hub pair)
# --------------------------------------------------------------------------

def compute_latency_baseline(nodes_adj, edges, hubs, cable_ids_sorted):
    """Shortest-path latency between every country-hub pair, plus the set of cables
    that path traverses -- precomputed here, not live in the browser.

    A live Dijkstra in jq (no priority queue, label-correcting relaxation instead)
    was measured at 60-110 rounds and 4-5s wall time for a single hub pair on this
    graph, because global cable topology has a short hop diameter but the lack of a
    proper priority queue means most of the ~2,100 nodes still get touched before the
    target settles. Precomputing here (189 Dijkstra runs, ~1s total) and shipping a
    keyed lookup lets the dashboard resolve "baseline latency for this pair" and
    "does this cut touch that pair's shortest path" in O(1), no live computation for
    the ~99% of (pair, cut) combinations where the answer is "unchanged".

    Cable references are stored as indices into `cable_ids_sorted` (returned
    alongside as `latency_cable_index`), not cable-id strings, since the same ~7
    cables repeat across thousands of pairs -- cuts the artifact's gzip size roughly
    in half versus inlining the id strings.
    """
    cable_index = {cid: i for i, cid in enumerate(cable_ids_sorted)}
    hub_ids = sorted(h["id"] for h in hubs)
    baseline = {}
    for src in hub_ids:
        dist, prev = dijkstra(nodes_adj, src)
        for dst in hub_ids:
            if dst <= src:
                continue
            d = dist.get(dst)
            if d is None:
                continue
            cables_used = []
            seen = set()
            node = dst
            while node in prev:
                parent, edge_key = prev[node]
                cid = edges[edge_key].get("cable_id")
                if cid is not None and cid not in seen:
                    seen.add(cid)
                    cables_used.append(cable_index[cid])
                node = parent
            baseline[f"{src}|{dst}"] = [round(d, 2), cables_used]
    return baseline


# --------------------------------------------------------------------------
# RIPE Atlas validation layer (Stage 2)
# --------------------------------------------------------------------------

def fetch_atlas_active_anchors(iso_codes, log=print):
    """Returns {iso: anchor_record} for the first active (non-disabled, not
    decommissioned) anchor found per requested country, then applies
    ATLAS_ANCHOR_OVERRIDE. Scans the full anchor list once (~1769 entries,
    paginated) rather than filtering server-side per country -- cheaper than
    16 separate requests and the set of countries we need is fixed and small.
    """
    wanted = set(iso_codes)
    found = {}
    url = f"{RIPE_ATLAS_API}/anchors/?page_size=500"
    while url and wanted - found.keys():
        d = fetch_json(url, timeout=25)
        for a in d["results"]:
            if a["is_disabled"] or a["date_decommissioned"]:
                continue
            cc = a["country"]
            if cc in wanted and cc not in found:
                found[cc] = a
        url = d.get("next")
    for iso, anchor_id in ATLAS_ANCHOR_OVERRIDE.items():
        if iso in wanted:
            found[iso] = fetch_json(f"{RIPE_ATLAS_API}/anchors/{anchor_id}/", timeout=15)
    missing = wanted - found.keys()
    if missing:
        log(f"  warning: no active RIPE Atlas anchor found for: {sorted(missing)}")
    return found


def fetch_atlas_mesh_measurement_ids(anchor_ids, log=print):
    """Returns {anchor_id: mesh_ping_measurement_id} for the given anchor IDs.

    The anchor-measurements list endpoint's query-string filters (target=,
    target_id=, type=, is_mesh=) are silently ignored by the API -- every
    combination tried returns the same unfiltered 12,743-row list starting at
    anchor 937. Confirmed live, not assumed. Works around it by paginating the
    full unfiltered list once (page_size=500, ~26 pages) and filtering
    client-side; stops early once every requested anchor has been found.
    """
    remaining = set(anchor_ids)
    result = {}
    url = f"{RIPE_ATLAS_API}/anchor-measurements/?page_size=500"
    while url and remaining:
        d = fetch_json(url, timeout=25)
        for r in d["results"]:
            if r["type"] != "ping" or not r["is_mesh"]:
                continue
            aid = int(r["target"].rstrip("/").split("/")[-1])
            if aid in remaining:
                result[aid] = r["measurement"].rstrip("/").split("/")[-1]
                remaining.discard(aid)
        url = d.get("next")
    if remaining:
        log(f"  warning: no mesh ping measurement found for anchor ids: {sorted(remaining)}")
    return result


def build_atlas_validation(latency_baseline, nodes, log=print):
    """Real measured RTT (RIPE Atlas anchor mesh, live) vs. modelled
    latency_baseline for a curated set of country pairs (ATLAS_PAIRS).

    Curated, not all 17,206 baseline pairs, for the same reason latency itself
    is precomputed rather than live: this is real network I/O (anchor list,
    mesh-measurement-id scan, one `latest` fetch per target anchor -- roughly
    10 MB total for 16 countries), not something to run per visitor or scale to
    thousands of pairs in a weekly build without a real justification. 16
    countries with an active RIPE Atlas anchor, chosen for geographic spread;
    17 pairs between them. Where a pair's forward mesh has no result (anchor
    meshes cover ~30-40% of all other anchors, not all of them), the reverse
    direction is tried before giving up on that pair -- RTT is symmetric enough
    for this purpose.
    """
    country_to_hub = {}
    for hid, node in nodes.items():
        if node.get("type") == "country_hub":
            country_to_hub.setdefault(node["country"], hid)

    countries = {c for pair in ATLAS_PAIRS for c in pair}
    isos = {ATLAS_COUNTRY_ISO[c] for c in countries}
    log(f"  fetching active RIPE Atlas anchors for {len(isos)} countries...")
    anchors = fetch_atlas_active_anchors(isos, log=log)

    anchor_ids = {a["id"] for a in anchors.values()}
    log(f"  scanning anchor-measurements for {len(anchor_ids)} mesh ping ids...")
    target_to_msm = fetch_atlas_mesh_measurement_ids(anchor_ids, log=log)

    mesh_cache = {}

    def mesh_results(anchor_id):
        if anchor_id not in mesh_cache:
            msm_id = target_to_msm.get(anchor_id)
            if msm_id is None:
                mesh_cache[anchor_id] = {}
            else:
                latest = fetch_json(f"{RIPE_ATLAS_API}/measurements/{msm_id}/latest/", timeout=25)
                mesh_cache[anchor_id] = {
                    r["prb_id"]: r for r in latest if isinstance(r, dict) and "prb_id" in r
                }
            time.sleep(0.3)
        return mesh_cache[anchor_id]

    validation = []
    for a, b in ATLAS_PAIRS:
        a_iso, b_iso = ATLAS_COUNTRY_ISO[a], ATLAS_COUNTRY_ISO[b]
        a_anchor, b_anchor = anchors.get(a_iso), anchors.get(b_iso)
        if not a_anchor or not b_anchor:
            continue

        measured = None
        msm_used = None
        # try b as target (a's probe pinging into b's mesh), then the reverse
        for target_anchor, source_anchor in ((b_anchor, a_anchor), (a_anchor, b_anchor)):
            by_probe = mesh_results(target_anchor["id"])
            r = by_probe.get(source_anchor["probe"])
            if r and r.get("avg", 0) > 0:
                measured = round(r["avg"], 2)
                msm_used = target_to_msm.get(target_anchor["id"])
                break
        if measured is None:
            log(f"  no RIPE Atlas result for {a} <-> {b}, skipping")
            continue

        ha, hb = country_to_hub.get(a), country_to_hub.get(b)
        key = "|".join(sorted([ha, hb])) if ha and hb else None
        entry = latency_baseline.get(key) if key else None
        if entry is None:
            log(f"  no modelled baseline for {a} <-> {b}, skipping")
            continue

        validation.append({
            "country_a": a, "country_b": b,
            "measured_rtt_ms": measured,
            "modelled_latency_ms": entry[0],
            "ratio": round(measured / entry[0], 2) if entry[0] else None,
            "atlas_measurement_id": int(msm_used) if msm_used else None,
        })

    return validation


# --------------------------------------------------------------------------
# Historical event validation (Stage 4)
# --------------------------------------------------------------------------

def build_historical_events(edges, cables, hubs_by_country, baseline_isolated_countries, log=print):
    """For each entry in HISTORICAL_EVENTS, removes that event's real cable set from
    today's topology and runs the same reachability BFS as Stage 1 to see which
    countries the model would predict as fully isolated. Returned alongside the
    curated real_impact text so the dashboard can show model vs. reality side by
    side -- including the honest misses (see the Tonga note in HISTORICAL_EVENTS).
    """
    all_hubs = [(h, country) for country, hids in hubs_by_country.items() for h in hids]
    baseline_isolated = set(baseline_isolated_countries)

    results = []
    for event in HISTORICAL_EVENTS:
        cut_idx = set()
        missing_cables = []
        for cid in event["cables"]:
            if cid not in cables:
                missing_cables.append(cid)
                continue
            cut_idx.update(cables[cid]["edge_indices"])
        if missing_cables:
            log(f"  warning: event {event['id']} references unknown cable ids: {missing_cables}")

        adj = collections.defaultdict(list)
        for idx, e in enumerate(edges):
            if idx in cut_idx:
                continue
            adj[e["from"]].append(e["to"])
            adj[e["to"]].append(e["from"])

        seed = next(h for h, c in all_hubs if c not in baseline_isolated)
        reached = {seed}
        frontier = [seed]
        while frontier:
            nxt = []
            for u in frontier:
                for v in adj[u]:
                    if v not in reached:
                        reached.add(v)
                        nxt.append(v)
            frontier = nxt

        newly_isolated = sorted({
            c for h, c in all_hubs
            if c not in baseline_isolated and h not in reached
        })

        entry = {k: v for k, v in event.items()}
        entry["model_predicted_isolated_countries"] = newly_isolated
        entry["model_cut_edge_count"] = len(cut_idx)
        results.append(entry)

    return results


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

def build_artifact(log=print):
    log("fetching cable geometry + landing points...")
    cable_geo = fetch_cable_geo()
    lp_geo = fetch_landing_points()

    lines_by_cable = collections.defaultdict(list)
    for f in cable_geo["features"]:
        lines_by_cable[f["properties"]["id"]].extend(f["geometry"]["coordinates"])

    lp_coords = {f["properties"]["id"]: tuple(f["geometry"]["coordinates"]) for f in lp_geo["features"]}

    cable_ids = sorted(lines_by_cable.keys())
    log(f"fetching {len(cable_ids)} cable details (this takes a few minutes)...")
    details = fetch_all_cable_details(cable_ids, log=log)

    lp_country = {}
    country_conflicts = []
    for cid, cable in details.items():
        for lp in cable.get("landing_points", []):
            lpid, country = lp["id"], lp["country"]
            if lpid in lp_country and lp_country[lpid] != country:
                country_conflicts.append((lpid, lp_country[lpid], country))
            lp_country[lpid] = country
    if country_conflicts:
        raise RuntimeError(f"inconsistent country field for landing points: {country_conflicts[:5]}")

    by_country = collections.defaultdict(list)
    for lpid, country in lp_country.items():
        coord = lp_coords.get(lpid)
        if coord is None:
            continue
        by_country[country].append((lpid, coord[0], coord[1]))

    log("building submarine edges (matching + chaining, 003 Point 3 + 3a)...")
    all_submarine_edges = []
    all_warnings = []
    for cid, cable in details.items():
        edges, warns = match_and_chain_cable(cid, cable, lines_by_cable, lp_coords)
        all_submarine_edges.extend(edges)
        all_warnings.extend(warns)

    log("building landmass groups + build check (003 Point 1)...")
    force_same_landmass, accepted_separate = load_landmass_groups()
    final_groups = build_landmass_groups(by_country, force_same_landmass, accepted_separate)

    log("building terrestrial edges (MST + hub attach, 003 Point 2)...")
    terrestrial_edges, hubs, latency_warnings = build_terrestrial_edges(final_groups)
    all_warnings.extend(latency_warnings)

    # assemble nodes
    nodes = {}
    for lpid, country in lp_country.items():
        coord = lp_coords.get(lpid)
        if coord is None:
            continue
        nodes[lpid] = {"type": "landing_point", "country": country, "lon": round(coord[0], 4), "lat": round(coord[1], 4)}
    for h in hubs:
        nodes[h["id"]] = {"type": "country_hub", "country": h["country"], "lon": h["lon"], "lat": h["lat"], "member_count": h["member_count"]}

    # assemble edges array + adjacency + edge_index + cables index
    # Edge ids are derived from stable content (cable_id/segment_index/endpoints or
    # from/to node ids), never from insertion order -- 003, Point 7: a var-cut_edge=X
    # link must keep resolving to the same edge across weekly rebuilds even if the
    # array position it lands on shifts.
    edges = []
    seen_ids = set()

    def unique_id(base):
        eid = base
        n = 2
        while eid in seen_ids:
            eid = f"{base}__{n}"
            n += 1
        seen_ids.add(eid)
        return eid

    for e in all_submarine_edges:
        if e.get("segment_index") is not None:
            base = f"{e['cable_id']}__{e['segment_index']}"
        else:
            base = f"{e['cable_id']}__{e['from']}__{e['to']}"
        edges.append({
            "id": unique_id(base),
            "type": "submarine",
            "from": e["from"], "to": e["to"],
            "distance_km": e["distance_km"], "latency_ms": round(latency_ms(e["distance_km"]), 2),
            "length_source": e["length_source"], "cable_id": e["cable_id"],
        })
    for e in terrestrial_edges:
        edges.append({
            "id": unique_id(f"terrestrial__{e['from']}__{e['to']}"),
            "type": "terrestrial",
            "from": e["from"], "to": e["to"],
            "distance_km": e["distance_km"], "latency_ms": round(latency_ms(e["distance_km"]), 2),
            "length_source": e["length_source"], "cable_id": None,
        })

    # Some edges legitimately round to 0.0 km at 1-decimal precision -- the source
    # data reports identical or sub-50m-apart coordinates for two distinct landing
    # point IDs (e.g. manama-bahrain/amwaj-island-bahrain), or a landmass group has
    # exactly one member so its hub coincides with that member exactly. That is a
    # true reflection of the input, not a bug -- surfaced as a warning, not a build
    # failure (Principle 4, "the model is inspectable").
    for e in edges:
        if e["distance_km"] == 0:
            all_warnings.append({
                "type": "zero_distance_edge", "edge_id": e["id"],
                "detail": "edge rounds to 0.0 km -- endpoints identical per source data or under 50 m apart, or hub attachment of a landmass group with only one member",
            })

    adjacency = collections.defaultdict(list)
    edge_index = {}
    nodes_adj = collections.defaultdict(list)  # for Dijkstra: node -> [(neighbor, weight, edge_key)]
    for idx, e in enumerate(edges):
        adjacency[e["from"]].append(idx)
        adjacency[e["to"]].append(idx)
        edge_index[e["id"]] = idx
        nodes_adj[e["from"]].append((e["to"], e["latency_ms"], idx))
        nodes_adj[e["to"]].append((e["from"], e["latency_ms"], idx))

    cables = collections.defaultdict(lambda: {"name": "", "edge_indices": [], "landing_point_ids": set()})
    for idx, e in enumerate(edges):
        if e["type"] != "submarine":
            continue
        cid = e["cable_id"]
        cables[cid]["name"] = details.get(cid, {}).get("name", cid)
        cables[cid]["edge_indices"].append(idx)
        cables[cid]["landing_point_ids"].add(e["from"])
        cables[cid]["landing_point_ids"].add(e["to"])
    cables = {k: {"name": v["name"], "edge_indices": v["edge_indices"], "landing_point_ids": sorted(v["landing_point_ids"])} for k, v in cables.items()}

    log("computing baseline betweenness + unreachable pairs (003 Point 5)...")
    hubs_by_country = collections.defaultdict(list)
    for h in hubs:
        hubs_by_country[h["country"]].append(h["id"])
    baseline_count, unreachable_pairs, total_pairs, isolated_countries, pair_records = compute_baseline_and_unreachable(nodes_adj, hubs_by_country, edges)
    for idx, e in enumerate(edges):
        e["baseline_pair_path_count"] = baseline_count.get(idx, 0)

    log("computing Stage 2 latency baseline (per hub-pair shortest path)...")
    latency_cable_index = sorted(cables.keys())
    latency_baseline = compute_latency_baseline(nodes_adj, edges, hubs, latency_cable_index)

    log("fetching RIPE Atlas validation layer (curated country pairs)...")
    atlas_validation = build_atlas_validation(latency_baseline, nodes, log=log)

    log("computing Stage 3 reroute pressure (per cable, top affected edges)...")
    reroute_pressure = compute_reroute_pressure(nodes_adj, cables, baseline_count, pair_records, log=log)

    log("computing historical event validation (Stage 4)...")
    historical_events = build_historical_events(edges, cables, hubs_by_country, isolated_countries, log=log)

    artifact = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": [{
            "name": "TeleGeography Submarine Cable Map",
            "license": TELEGEOGRAPHY_LICENSE,
            "fetched_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "raw_feature_count": len(cable_geo["features"]),
            "unique_cable_count": len(cable_ids),
            "landing_point_count": len(lp_geo["features"]),
        }],
        "constants": {
            "speed_of_light_km_s": SPEED_OF_LIGHT_KM_S,
            "fiber_index_factor": FIBER_INDEX_FACTOR,
            "fiber_speed_km_s": round(FIBER_SPEED_KM_S, 2),
            "cluster_threshold_km": CLUSTER_THRESHOLD_KM,
            "high_intra_group_latency_warning_ms": HIGH_LATENCY_WARNING_MS,
        },
        "scope_note": (
            "This model represents submarine cable connectivity only. Any purely "
            "land-based connection between two countries is missing -- even between "
            "neighboring countries with their own landing points. The only exception "
            "are the mergers declared in data/landmass_groups.json to preserve the "
            "intra-country cohesion of individual large countries -- not general "
            "border modelling, and not its own edge type."
        ),
        "unreachable_baseline_pairs": unreachable_pairs,
        "total_country_pairs": total_pairs,
        "isolated_countries": sorted(isolated_countries),
        "landmass_groups_file": "data/landmass_groups.json",
        "warnings": all_warnings,
        "nodes": nodes,
        "edges": edges,
        "adjacency": adjacency,
        "edge_index": edge_index,
        "cables": cables,
        "latency_cable_index": latency_cable_index,
        "latency_baseline": latency_baseline,
        "atlas_validation": atlas_validation,
        "historical_events": historical_events,
        "reroute_pressure": reroute_pressure,
    }
    return artifact


# --------------------------------------------------------------------------
# Sanity checks (Phase B requirement, round 1 requirement)
# --------------------------------------------------------------------------

def run_sanity_checks(artifact, log=print):
    failures = []

    nodes = artifact["nodes"]
    edges = artifact["edges"]
    adjacency = artifact["adjacency"]

    # no orphaned nodes: every node must appear in at least one edge
    touched = set()
    for e in edges:
        touched.add(e["from"])
        touched.add(e["to"])
    orphaned = [nid for nid in nodes if nid not in touched]
    if orphaned:
        failures.append(f"{len(orphaned)} orphaned nodes with zero edges: {orphaned[:10]}")

    # negative distance is impossible and always a real bug; exact 0.0 can be
    # legitimate (identical/sub-50m source coordinates, or a single-member landmass
    # group's hub coinciding with its only point) -- surfaced as a "zero_distance_edge"
    # warning instead, not a build failure.
    negative_length = [e["id"] for e in edges if e["distance_km"] < 0]
    if negative_length:
        failures.append(f"{len(negative_length)} edges with negative distance_km: {negative_length[:10]}")
    zero_length = [e["id"] for e in edges if e["distance_km"] == 0]
    if zero_length:
        log(f"  note: {len(zero_length)} edges have distance_km == 0.0 (see 'zero_distance_edge' warnings): {zero_length[:10]}")
    absurd_length = [e["id"] for e in edges if e["distance_km"] > 20040]  # > half Earth circumference
    if absurd_length:
        failures.append(f"{len(absurd_length)} edges longer than half the Earth's circumference: {absurd_length[:10]}")

    # node/edge counts in expected order of magnitude (per docs/decisions/003, round 3)
    n_landing_points = sum(1 for n in nodes.values() if n["type"] == "landing_point")
    n_hubs = sum(1 for n in nodes.values() if n["type"] == "country_hub")
    if not (1500 <= n_landing_points <= 2500):
        failures.append(f"landing point count {n_landing_points} outside expected range [1500, 2500]")
    if not (100 <= n_hubs <= 300):
        failures.append(f"hub count {n_hubs} outside expected range [100, 300]")
    if not (3000 <= len(edges) <= 6000):
        failures.append(f"edge count {len(edges)} outside expected range [3000, 6000]")

    # known-islands check: isolated countries must be listed explicitly and stay below
    # the stop threshold set in review round 3 -- a sudden jump means the matching/
    # chaining broke, not that the world got more disconnected overnight
    unreachable = artifact["unreachable_baseline_pairs"]
    total_pairs = artifact["total_country_pairs"]
    isolated = artifact["isolated_countries"]
    if len(isolated) > SANITY_MAX_ISOLATED_COUNTRIES:
        failures.append(
            f"{len(isolated)} fully isolated countries, above the stop threshold of "
            f"{SANITY_MAX_ISOLATED_COUNTRIES} (003, Point 5): {isolated}"
        )
    log(f"unreachable_baseline_pairs: {unreachable} / {total_pairs}, isolated countries: {isolated}")

    if failures:
        log("SANITY CHECKS FAILED:")
        for f in failures:
            log(f"  - {f}")
        raise SystemExit(1)

    log("all sanity checks passed.")
    log(f"  nodes: {len(nodes)} ({n_landing_points} landing points, {n_hubs} hubs)")
    log(f"  edges: {len(edges)}")
    log(f"  cables: {len(artifact['cables'])}")
    log(f"  unreachable_baseline_pairs: {unreachable} / {total_pairs}")
    log(f"  warnings: {len(artifact['warnings'])}")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    artifact = build_artifact()
    run_sanity_checks(artifact)

    out_path = REPO_ROOT / "data" / "graph.json"
    with open(out_path, "w") as f:
        json.dump(artifact, f, separators=(",", ":"))

    size_kb = out_path.stat().st_size / 1024
    print(f"wrote {out_path} ({size_kb:.1f} KB)")
    if size_kb > ARTIFACT_BUDGET_KB:
        print(f"WARNING: artifact size {size_kb:.1f} KB exceeds the {ARTIFACT_BUDGET_KB} KB budget "
              f"(docs/decisions/003-graph-schema.md, Groessenbudget)", file=sys.stderr)


if __name__ == "__main__":
    main()
