# 003a — Snapping-Trefferquote (Verifikation vor dem Generator)

**Datum:** 2026-08-09, aktualisiert in Review-Runde 2 (Matching-Algorithmus korrigiert).
**Gehört zu:** `003-graph-schema.md`, Punkt 3 (Kabel → Kanten). Punkt 3 selbst (welcher
Landing Point zu welchem Segment/Vertex gehört — die Tiers 1–3 unten) wurde in
Review-Runde 3 final freigegeben und unverändert übernommen. Was sich in Runde 3 änderte,
ist eine Ebene darüber: **wie** aus den hier ermittelten Zuordnungen tatsächlich Kanten
werden (Reihenfolge/Kettenbildung, plus ein vierter Fallback für Landing Points ohne
Kettenpartner) — das steht in `003-graph-schema.md`, Punkt 3a, nicht hier. Die Zahlen in
diesem Dokument (Tier 1/2/3-Verteilung) bleiben gültig.
**Methode:** Alle 697 eindeutigen Kabel per `GET
https://www.submarinecablemap.com/api/v3/cable/{id}.json` einzeln abgefragt (697/697
erfolgreich, 0 Fehler), gegen `data/samples/telegeography-cable-geo.json` (Geometrie)
und `data/samples/telegeography-landing-point-geo.json` (Koordinaten) geprüft. Skript
und Rohdaten liegen nicht im Repo (Verifikationslauf, kein Build-Artefakt) — Ergebnis
hier vollständig dokumentiert, reproduzierbar mit derselben API.

**Erste Korrektur gegenüber `003-graph-schema.md`:** Das Schema-Dokument zählte
"718 Kabel". Das ist die Zahl der GeoJSON-*Features* in `cable-geo.json` — 21 Kabel sind
auf mehrere Features aufgeteilt (dieselbe `properties.id` erscheint mehrfach, mit
jeweils eigenem `MultiLineString`). Die Zahl der **eindeutigen Kabel** (und damit der
`cables`-Index-Einträge im Artefakt) ist **697**, nicht 718. `cable-geo.json`- und
Cable-Detail-IDs stimmen exakt überein (697 = 697, keine Differenz in beide Richtungen).

---

## Review-Runde 2: Matching-Algorithmus korrigiert

Die Zahlen unten ersetzen die erste Fassung. Der ursprüngliche Zähl-Algorithmus
("unabhängiges Nearest-Match pro Landing Point") unterstellte implizit eine Bijektion
zwischen Segment-Endpunkten und Landing Points. Es gibt aber 3.860 Segment-Endpunkte auf
nur 3.184 deklarierte Paare — ein Landing Point, an dem ein Kabel durchläuft, ist
Endpunkt von **zwei** Segmenten, keine Ausnahme, sondern der Normalfall bei
Durchgangsstationen. Korrigiert auf ein echtes many-to-one-Matching (siehe
`003-graph-schema.md`, Punkt 3, für den vollen Algorithmus): jeder Endpunkt bekommt
genau einen Landing Point, ein Landing Point darf mehrere Endpunkte bekommen.

## Ergebnis: 99,8 % → weiterhin 99,8 % sauber, aber andere Verteilung

| Kategorie | Anzahl (korrigiert) | Anteil | Anzahl (erste, fehlerhafte Zählung) |
|---|---|---|---|
| Tier 1: Endpunkt-Match (≤ 50 km) | 2.646 | 83,1 % | 2.772 |
| Tier 2: Vertex-Split (innerer Linienpunkt ≤ 50 km) | 531 | 16,7 % | 405 |
| **sauber (Tier 1 + 2)** | **3.177** | **99,8 %** | 3.177 |
| Tier 3: inferred (Kante zum nächsten bereits zugeordneten Landing Point) | 7 | 0,2 % | 7 |
| kein Match möglich | 0 | 0 % | 0 |
| **Gesamt (deklarierte Cable↔Landing-Point-Paare)** | **3.184** | 100 % | 3.184 |

Die Gesamtquote (99,8 % sauber) bleibt identisch — aber deutlich mehr Fälle landen jetzt
korrekt im Vertex-Tier statt fälschlich als Endpunkt-Match durchzugehen. Grund: im alten
Algorithmus konnte ein Landing Point, sobald es als "vergeben" markiert war, keinem
weiteren Endpunkt mehr zugeordnet werden — bei Durchgangsstationen (zwei Endpunkte am
selben Ort) hat das den zweiten Endpunkt dann fälschlich einem entfernteren, falschen
Landing Point zugeschlagen, der zufällig noch "frei" war, statt korrekt im Vertex-Tier
oder am selben (jetzt zweifach genutzten) Landing Point zu landen. Die 7
`inferred_edge`-Fälle sind identisch geblieben (dieselben 3 Kabel, siehe unten) — dort
ändert die Korrektur nichts, weil dort ohnehin kein Konkurrenzfall vorlag.

**Stresstest, nicht ursprünglich angefordert:** `apcn-2` (Singapur–Japan-Trunk, 52
Segmente) fiel beim ersten fehlerhaften Algorithmus mit 8 von 10 Landing Points komplett
unmatched auf. Mit dem korrigierten Vertex-Tier: alle 8 matchen auf 0,0–1,4 km genau als
innere Linienpunkte zweier langer Trunk-Segmente (Hongkong, Shantou, Busan, Taipeh etc.
als echte Zwischenstationen). Ohne den Vertex-Tier wäre das ein sehr sichtbarer Fehler
auf einem der größten Kabel im Datensatz gewesen — der beste Beleg, dass Tier 2 kein
Nice-to-have ist.

**Die 7 `inferred_edge`-Fälle, unverändert gegenüber der ersten Zählung:**

| Kabel | Landing Point |
|---|---|
| `america-movil-submarine-cable-system-1-amx-1` | `cancn-mexico` |
| `eaufon-2` | `kangiqsujuaq-qc-canada` |
| `eaufon-2` | `puvirnituq-qc-canada` |
| `trans-global-cable-system-tgcs` | `balikpapan-indonesia` |
| `trans-global-cable-system-tgcs` | `makassar-indonesia` |
| `trans-global-cable-system-tgcs` | `manado-indonesia` |
| `trans-global-cable-system-tgcs` | `surabaya-indonesia` |

Nur 3 Kabel betroffen, alle mit plausibler Erklärung: `eaufon-2` und
`trans-global-cable-system-tgcs` sind Multi-Landing-Point-Systeme mit vereinfachter
öffentlicher Geometrie; `cancn-mexico` liegt vermutlich auf einer Stichleitung, die in
der Geometrie nicht separat gezeichnet ist.

Kein Kabel ist vollständig unmatched, keine fehlende Geometrie, keine fehlende
Koordinate — bei 697 von 697 Kabeln bekommt jeder deklarierte Landing Point am Ende
einen Platz im Graphen.

---

## Mehrdeutigkeits-Check: durch das many-to-one-Matching strukturell gelöst

**Frage:** Liegen zwei deklarierte Landing Points *desselben* Kabels jemals innerhalb
50 km voneinander? Dann könnte ein einzelner Match-Versuch einen Endpunkt der falschen
von beiden zuordnen.

**Ergebnis: Ja, bei 210 von 697 Kabeln (30,1 %)** — häufiger als erwartet. Beispiele:
`5-villages-6-islands` (13 mehrdeutige Paare), `au-aleutian` (8), `aqualink` (6),
`aurora` (7), `2africa` (3), plus 205 weitere Kabel mit meist 1–2 Paaren.

**Gelöst, nicht nur eingeordnet.** Der in Runde 1 vorgeschlagene Fix — gieriges
Matching, alle Kandidatenpaare nach Distanz sortiert, aufsteigend zugewiesen — ist jetzt
Teil des korrigierten Algorithmus selbst (Tier 1) und wurde genau an den in der Review
genannten Beispielen getestet:

| Kabel | Deklariert | Tier 1 | Tier 2 | Tier 3 | Unmatched |
|---|---|---|---|---|---|
| `2africa` | 50 | 49 | 1 | 0 | 0 |
| `5-villages-6-islands` | 9 | 8 | 1 | 0 | 0 |
| `au-aleutian` | 14 | 12 | 2 | 0 | 0 |
| `aqualink` | 11 | 10 | 1 | 0 | 0 |
| `aurora` | 12 | 12 | 0 | 0 | 0 |

Für alle fünf: vollständige, eindeutige Zuordnung, keine offenen Fälle. Der frühere
Rest-Risiko-Rahmen ("Beschriftungsrisiko, kein Genauigkeitsrisiko") war richtig
eingeschätzt — mit dem korrigierten Algorithmus ist er jetzt behoben, nicht nur
eingegrenzt.

---

## Zusatzbefund: Country-Feld ist konsistent

Nebenbei mitgeprüft, weil aus denselben Daten ableitbar: das `country`-Feld aus den
Cable-Details ist für alle 1.922 Landing Points, die in mindestens einem Kabel
auftauchen, **widerspruchsfrei** — keine zwei Kabel nennen für dieselbe
`landing_point.id` unterschiedliche Länder. Das ist die Datengrundlage für die
Country-Hub-Neufassung in Punkt 1 des Hauptdokuments; ohne diese Konsistenzprüfung wäre
das Clustering pro Land nicht verlässlich gewesen.
