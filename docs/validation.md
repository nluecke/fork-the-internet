# Datenquellen-Validierung — Stand 2026-08-02

> Kompakte Zusammenfassung für's Planen der nächsten Schritte. Volle Details,
> Rohbegründungen und das Entscheidungslog stehen in den internen Projektnotizen
> (nicht Teil dieses Repos), Abschnitt "Offene Frage 1" — dieses Dokument ist der
> Extrakt daraus.

## Ergebnis: Gate 1 ("Reichen die Daten?") erreicht ✅

Alle 7 Quellen aus der ursprünglichen Checkliste wurden real angefragt, Response-Samples
liegen unter `data/samples/`.

| Quelle | Status | Liefert | Kernbefund |
|---|---|---|---|
| TeleGeography Submarine Cable Map | ✅ anonym | Kabelgeometrie (718 Kabel), Landing Points (1922) | Lizenz CC BY-SA 4.0 für Referenzen/Screenshots geklärt, kommerzielle Datennutzung separat lizenzpflichtig (nicht relevant für uns) |
| PeeringDB | ✅ anonym | IXPs, Netze, Facilities | `info_traffic` als grobe Kapazitäts-Kategorie (z.B. "50-100Tbps") |
| CAIDA AS Rank | ✅ anonym | AS-Graph, Beziehungstyp (customer/peer/provider) | Graphstruktur, keine Latenz/Kapazität |
| RIPEstat | ✅ anonym | AS-Nachbarn, Country-Routing-Stats | Baseline-Zeitreihen, keine Latenz als Kantengewicht |
| **RIPE Atlas** | ✅ anonym | Traceroute-Messungen, tausende Probes seit 2010 | **Echte gemessene Per-Hop-RTT** — schließt die Latenzlücke der vier obigen Quellen |
| **IODA** | ✅ anonym (Domain umgezogen: `ioda.inetintel.cc.gatech.edu`) | Historische Outage-/Latenz-Zeitreihen pro Land | Direkt nutzbar für die geplante Validierung gegen echte Kabelschnitte |
| Cloudflare Radar | ⚠️ auth-pflichtig | Traffic, Outage-Annotationen, AS-Rankings | Braucht Free-Tier-Token; architektonisch okay (Token bleibt Server-Secret in Grafana, kein Leak über die URL), aber Rate-Limit gegen Voting-Woche-Traffic ungeklärt, Account noch nicht angelegt |

**Kriterium erfüllt:** Graph aus Topologie (TeleGeography, CAIDA, RIPEstat, PeeringDB) plus
echter Latenz (RIPE Atlas) plus Validierungsdaten (IODA) trägt. Die zwischenzeitlich
erwogene Notlösung — Latenz aus Kabelgeometrie via Great-Circle-Distanz × Lichtgeschwindigkeit
in Faser — ist nicht mehr nötig, bleibt aber als dokumentierter Fallback für Kantenpaare ohne
Atlas-Messung.

## Offene Punkte aus der Datenrunde

- Cloudflare Radar: Free-Tier-Account + Token anlegen, Rate-Limit gegen erwarteten
  Voting-Woche-Traffic abschätzen.
- RIPE Atlas: bei jeder künftigen Abfrage `probe_ids` eng filtern und `start`/`stop` klein
  halten — ein ungefiltertes 2h-Fenster über alle Probes einer Messung zog 56 MB.
- IODA-Entities-Liste ist groß (alle Länder/Kontinente); für konkrete Szenarien reicht ein
  gezielter `fqid`-Lookup pro betroffenem Land.

## Nicht Teil dieses Dokuments

Die eigentliche historische Ereignis-Validierung (Modell-Vorhersage vs. RIPE-Atlas-/IODA-
Messwerte beim Rotes-Meer- oder Tonga-Kabelschnitt) ist noch nicht gebaut — dafür muss erst
das Graph-Modell Stufe 1/2 stehen (siehe "Nächste Schritte" in den internen
Projektnotizen). Dieses Dokument bekommt dann einen zweiten Abschnitt.

## Nächstes Gate

Globus-Panel verifizieren (Business Charts Panel / ECharts-GL vs. Dynamic-Text-Panel mit
`globe.gl` vs. native Geomap als Fallback) — siehe `docs/decisions/` für den Ausgang.
