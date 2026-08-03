#!/usr/bin/env python3
"""Build the normalized topology artifact for "Fork the Internet".

Pulls live submarine-cable topology from TeleGeography, builds the
physical/country graph described in docs/decisions/003-graph-schema.md
(final after review round 3), and writes data/graph.json.

Run: python3 scripts/build_graph.py
"""

import json
import math
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

def build_terrestrial_edges(final_groups):
    """Returns (edges, hubs, warnings).

    edges: list of dicts (MST within each group + one hub-attach edge).
    hubs: list of dicts {id, country, lon, lat, member_count}.
    warnings: high_intra_group_latency entries (003, Point 2).
    """
    edges = []
    hubs = []
    warnings = []
    hub_counter = 0

    for country, groups in final_groups.items():
        for group in groups:
            hub_counter += 1
            hub_id = f"hub__{hub_counter}"
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

def dijkstra(adj, src):
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


def compute_baseline_and_unreachable(nodes_adj, hubs_by_country):
    """Runs one Dijkstra per hub, derives country-pair reachability (min over hub
    combinations) and increments baseline_pair_path_count per edge on each country
    pair's shortest path. Also counts unreachable country pairs and countries
    isolated from the largest connected component (003, Point 5).
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
            while node in prev:
                parent, edge_key = prev[node]
                baseline_count[edge_key] += 1
                node = parent

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

    return baseline_count, unreachable, total_pairs, isolated_countries


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
    baseline_count, unreachable_pairs, total_pairs, isolated_countries = compute_baseline_and_unreachable(nodes_adj, hubs_by_country)
    for idx, e in enumerate(edges):
        e["baseline_pair_path_count"] = baseline_count.get(idx, 0)

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
