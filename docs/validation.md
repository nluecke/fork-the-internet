# Data Source Validation — Status 2026-08-02

> Compact summary for planning next steps. Full details, raw rationale, and the
> decision log live in the internal project notes (not part of this repo), section
> "Open Question 1" — this document is the extract from that.

## Result: Gate 1 ("Is the data sufficient?") reached ✅

All 7 sources from the original checklist were queried for real; response samples
live under `data/samples/`.

| Source | Status | Provides | Key finding |
|---|---|---|---|
| TeleGeography Submarine Cable Map | ✅ anonymous | Cable geometry (718 cables), landing points (1922) | License CC BY-SA 4.0 clarified for references/screenshots; commercial data use is separately licensed (not relevant to us) |
| PeeringDB | ✅ anonymous | IXPs, networks, facilities | `info_traffic` as a coarse capacity category (e.g. "50-100Tbps") |
| CAIDA AS Rank | ✅ anonymous | AS graph, relationship type (customer/peer/provider) | Graph structure, no latency/capacity |
| RIPEstat | ✅ anonymous | AS neighbors, country routing stats | Baseline time series, no latency as an edge weight |
| **RIPE Atlas** | ✅ anonymous | Traceroute measurements, thousands of probes since 2010 | **Real measured per-hop RTT** — closes the latency gap left by the four sources above |
| **IODA** | ✅ anonymous (domain moved: `ioda.inetintel.cc.gatech.edu`) | Historical outage/latency time series per country | Directly usable for the planned validation against real cable cuts |
| Cloudflare Radar | ⚠️ requires auth | Traffic, outage annotations, AS rankings | Needs a free-tier token; architecturally fine (token stays a server secret in Grafana, no leak via the URL), but the rate limit against voting-week traffic is unresolved, account not yet created |

**Criterion met:** a graph built from topology (TeleGeography, CAIDA, RIPEstat, PeeringDB)
plus real latency (RIPE Atlas) plus validation data (IODA) holds up. The stopgap
considered in the meantime — latency derived from cable geometry via great-circle
distance × speed of light in fiber — is no longer necessary, but remains a documented
fallback for edge pairs without an Atlas measurement.

## Open items from the data round

- Cloudflare Radar: create a free-tier account + token, estimate the rate limit against
  expected voting-week traffic.
- RIPE Atlas: for every future query, filter `probe_ids` tightly and keep `start`/`stop`
  narrow — an unfiltered 2h window across all probes of one measurement pulled 56 MB.
- The IODA entities list is large (all countries/continents); for concrete scenarios a
  targeted `fqid` lookup per affected country is enough.

## Not part of this document

The actual historical event validation (model prediction vs. RIPE Atlas/IODA
measurements for the Red Sea or Tonga cable cuts) has not been built yet — that
requires graph model Stage 1/2 to be in place first (see "Next steps" in the internal
project notes). This document will then get a second section.

## Next gate

Verify the globe panel (Business Charts panel / ECharts-GL vs. dynamic text panel with
`globe.gl` vs. native Geomap as fallback) — see `docs/decisions/` for the outcome.
