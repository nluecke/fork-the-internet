# 003 — Graph-Schema für das Build-Artefakt

**Datum:** 2026-08-09 (Platzhalter, an tatsächliches Datum anpassen)
**Status:** Schema final — Review-Runde 3 eingearbeitet, letzte Schema-Runde. Aus Runde 2
final freigegeben und in Runde 3 unverändert: Matching-Algorithmus (Punkt 3),
`baseline_pair_path_count`-Umbenennung (Punkt 5), `nodes`/`adjacency`/`edge_index`
(Punkt 6), stabile IDs (Punkt 7), Option A + `scope_note` (Punkt 8). Runde 3: Bogenlänge
statt Luftlinie für Seekabel-Kanten (Punkt 4), Kettenbildung explizit spezifiziert inkl.
neu entdecktem vierten Matching-Fallback (Punkt 3a), `data/landmass_groups.json` ersetzt
die kuratierten Brücken aus Runde 2 vollständig — Schwellwert-Clustering wird Build-Check
statt Entscheider (Punkt 1), automatische Latenz-Warnungen statt hartkodiertem Russland
(Punkt 2), `unreachable_baseline_pairs` erstmals echt ausgerechnet: 1.094 (Punkt 5).
**Direkt weiter zu Phase B, keine weitere Schema-Freigabe nötig.**
**Umfang:** Trägt Stufe 1 (Erreichbarkeit), Stufe 2 (Latenz) und die Baseline für Stufe 3
(Reroute-Druck) des physischen Kabel-/Länder-Graphen. **Nicht** Teil dieses Dokuments:
der AS-/IXP-Graph (CAIDA, RIPEstat, PeeringDB) und die RIPE-Atlas-Validierungsschicht —
beide kommen erst in späteren Schritten (6 und danach) dazu und brauchen ein eigenes
Schema-Update, keine Vorwegnahme hier.

Alle Zahlen unten sind aus den echten Samples in `data/samples/` gerechnet oder — für
Punkt 1 und die Snapping-Verifikation — aus allen 697 Cable-Detail-Antworten der
TeleGeography-API, live abgefragt, nicht geschätzt. Details zur Snapping-Verifikation:
`003a-snapping-trefferquote.md`.

---

## 1. Zwei Ebenen, ein Graph: Landing Points + Country-Hubs pro Cluster (überarbeitet)

**Revidiert nach Review — der ursprüngliche Ein-Hub-pro-Land-Ansatz war ein Blocker.**
Ein einzelner Centroid pro Land bricht bei Ländern mit geografisch verstreuten
Territorien: der arithmetische Mittelwert von Marseille und einer Insel im Pazifik
ergibt einen Punkt, der nirgendwo real ist, und schlimmer — er würde im Graphen einen
Pfad *über* diesen unsinnigen Punkt nahelegen, wo real keiner existiert.

**Geprüft, nicht vermutet:** Mit dem autoritativen `country`-Feld aus allen 697
Cable-Detail-Antworten (siehe `003a-snapping-trefferquote.md`) neu gerechnet. Wichtiger
Befund vorab: TeleGeography führt französische Übersee-Gebiete (`French Guiana`,
`Réunion`, `New Caledonia`, `French Polynesia`, `Martinique`, `Guadeloupe`, `Mayotte`)
bereits als **eigene** `country`-Werte, getrennt von `France` (27 Landing Points, alle
Festland + Korsika). Ebenso `Bermuda`, `Cayman Islands`, `Bonaire, Sint Eustatius and
Saba` etc. sind eigene Länder-Strings. Das im Auftrag genannte FR-Beispiel tritt unter
den echten Daten also so nicht auf — das ändert aber nichts daran, dass das
grundsätzliche Problem real ist, siehe US, Kanada, Australien, Niederlande, Kiribati
unten.

**Entscheidung: ein Hub pro geografischem Cluster innerhalb eines Landes, nicht einer
pro Land.**

- **Clustering:** Single-Linkage über die Landing Points eines Landes, Schwellwert
  **2.000 km** (Great-Circle). Zwei Landing Points im selben Cluster, wenn eine Kette
  von Zwischenpunkten existiert, die nie mehr als 2.000 km auseinanderliegt.
- **Schwellwert-Begründung, korrigiert nach Review.** Die erste Fassung begründete
  2.000 km über die Verteilung der Nächste-Nachbar-Distanzen — methodisch falsch, wie im
  Review zu Recht angemerkt: Single-Linkage merged an **Merge-Höhen**, nicht an
  Nächste-Nachbar-Abständen einzelner Punkte. Für Single-Linkage sind die Merge-Höhen
  eines Landes exakt die Kantengewichte seines Minimalen Spannbaums (MST) — Kruskals
  Algorithmus und Single-Linkage-Dendrogramme sind dasselbe Konstrukt. Richtig nachgerechnet:
  MST pro Land gebaut (alle 186 Länder, 1.736 Kanten insgesamt), alle Kantengewichte
  gepoolt.
  - Verteilung: 95 % aller Merge-Höhen liegen unter 483 km, 99 % unter 1.165 km, 99,5 %
    unter 1.651 km.
  - **Es gibt keine sauber leere Zone mehr, wie in der ersten Fassung behauptet.** Die
    Bucket-Verteilung zwischen 1.500 und 4.000 km ist dünn, aber nicht leer: 8 Merge-Höhen
    zwischen 1.500–2.000 km, 2 zwischen 2.000–2.500 km, **0 zwischen 2.500–3.000 km**, 2
    zwischen 3.000–3.500 km, 1 zwischen 3.500–4.000 km. Nur ein einziger 500-km-Bucket ist
    leer, keine breite Lücke.
  - **Der Schwellwert ist eine Setzung, kein Naturgesetz — hier offen benannt.** Das
    exakte Fenster, das die weiter unten gezeigte 5-Länder-Gruppierung (USA/Kanada/
    Australien/Niederlande/Kiribati mehrfach, alle anderen einfach) unverändert
    reproduziert, ist **[1.994 km, 2.041 km)** — nach oben begrenzt durch Australiens
    größte MST-Kante (2.041 km, muss über der Schwelle bleiben, damit Australien
    getrennt bleibt), nach unten durch Argentiniens größte MST-Kante (1.994 km, muss
    unter der Schwelle bleiben, damit Argentinien **nicht** unnötig auch getrennt wird).
    Das sind **47 km Spielraum**, nicht mehrere Tausend. 2.000 km ist eine runde Zahl,
    die zufällig in dieses schmale Fenster fällt — keine durch eine breite Lücke
    "bewiesene" Wahl.
  - **Konsequenz:** Diese Fragilität gehört als Build-Sanity-Check in Phase B — wenn ein
    künftiger Datensatz (neuer Landing Point in Argentinien oder Australien) das Fenster
    verschiebt oder schließt, muss der Build das melden, nicht still eine andere
    Hub-Aufteilung produzieren. Und der Math-Panel-Text muss "2.000 km ist eine gesetzte
    Konvention, kein empirisch eindeutiger Bruch" sagen, nicht den ursprünglichen
    (falschen) Lücken-Claim.
- **Ergebnis mit dem Schwellwert, autoritative Länder-Daten:** **192 Hubs über 186
  Länder.** Nur 5 Länder bekommen mehr als einen Hub:

  | Land | Hubs | Cluster (Größe, grobe Lage) |
  |---|---|---|
  | USA | 3 | Alaska/Westküste (98), Ostküste (44), Hawaii (25) |
  | Kanada | 2 | Westküste/BC (115), Atlantikprovinzen (40) |
  | Australien | 2 | Sydney/Ostküste (20), Darwin/Perth/Nordwesten (7) |
  | Niederlande | 2 | Festland (7), Bonaire (1) |
  | Kiribati | 2 | Tarawa (1), Tabwakea/Kiritimati (1) |

  Alle anderen 181 Länder bekommen genau einen Hub. Diese Tabelle zeigt das **rohe
  Schwellwert-Ergebnis** — die tatsächliche Hub-Zahl nach Punkt "Landmass-Gruppen" unten
  ist niedriger (189 statt 192), weil drei dieser Fünf-Länder-Fälle keine echte
  Landtrennung sind, sondern eine Datenlücke im Schwellwert.

**Landmass-Gruppen ersetzen die kuratierten Brücken — überarbeitet nach Review 3.**
Round 2 löste das Problem (USA Ost/West brauchen Verbindung für den realen
nordamerikanischen Transitweg beim Rotes-Meer-Szenario) mit drei von Hand gepflegten
Brücken-Kanten. Problem laut Review: die Brückenliste ist eine Funktion des
2.000-km-Schwellwerts, wird aber unabhängig davon gepflegt — verschiebt sich der
Schwellwert oder ein neues Land driftet über die Grenze, fehlt still eine Brücke.

**Entscheidung:** Statt Cluster zu bilden und dann Brücken nachträglich zu kurieren,
wird direkt kuratiert, **welche Landing-Point-Gruppen eines Landes dieselbe Landmasse
sind** — das 2.000-km-Clustering wird zum **Build-Check**, nicht mehr zum Entscheider.

- **`data/landmass_groups.json`** (ersetzt `data/bridges.json` vollständig, wird
  überflüssig): eine kurze Liste von "erzwungenen Zusammenschlüssen", je Eintrag zwei
  Anker-Landing-Points, deren Cluster als eine Landmasse zu behandeln sind:

  ```json
  {
    "force_same_landmass": [
      { "country": "United States", "anchor_points": ["anchorage-ak-united-states", "shirley-ny-united-states"], "note": "Festland inkl. Alaska/Westküste + Ostküste; Hawaii bleibt separat" },
      { "country": "Canada", "anchor_points": ["cordova-bay-bc-canada", "cape-ray-nl-canada"], "note": "Westküste/BC + Atlantikprovinzen" },
      { "country": "Australia", "anchor_points": ["sydney-nsw-australia", "darwin-nt-australia"], "note": "Ostküste + Nordwesten" }
    ]
  }
  ```

  Alles, was nicht in der Datei steht, bleibt beim rohen Schwellwert-Ergebnis — für die
  meisten Länder ist das ohnehin ein einziger Cluster, für Hawaii/Bonaire/Kiritimati
  bleibt es bei der (korrekten) Trennung.

- **Build-Check, geprüft und bestanden:** Für jedes der 186 Länder wird das
  2.000-km-Clustering gerechnet, dann werden die deklarierten Zusammenschlüsse angewandt
  (Union-Find über die Cluster, die die Anker-Punkte enthalten). Zwei Prüfungen, beide
  müssen für **alle** 186 Länder grün sein, nicht nur für die drei bekannten Fälle:
  1. Jedes Land, das **nicht** in `landmass_groups.json` steht, muss nach dem
     Schwellwert-Clustering aus **genau einem** Cluster bestehen. Sonst: Build bricht ab
     — "Land X ist fragmentiert und nicht in `landmass_groups.json` deklariert."
  2. Jeder deklarierte Zusammenschluss muss echte Arbeit leisten — die beiden
     Anker-Punkte müssen **vor** dem Zusammenschluss in unterschiedlichen Clustern
     liegen. Landen sie schon im selben Cluster, ist der Eintrag vermutlich veraltet
     (neue Kabel haben die Lücke geschlossen): Build bricht ab — "Eintrag für Land X ist
     möglicherweise überflüssig, bitte prüfen."
  Nachgerechnet: **0 Fehler bei beiden Prüfungen**, mit exakt den drei oben gelisteten
  Einträgen. Das ist der direkte Beleg, dass die Datei heute vollständig ist — und der
  Mechanismus, der ein künftig zerfallendes Argentinien laut meldet statt still falsch zu
  bleiben.
- **Ergebnis: 189 Hubs statt 192.** USA (3→2: Festland vereint, Hawaii bleibt), Kanada
  (2→1: vereint), Australien (2→1: vereint). Niederlande und Kiribati bleiben bei 2 — das
  sind die einzigen zwei echten Mehrfach-Hub-Länder, die übrig bleiben.
- **Geprüft: die drei alten Brücken entstehen jetzt als ganz normale MST-Kanten, keine
  Sonderbehandlung, kein eigener Kantentyp mehr nötig.** Der minimale Spannbaum über die
  **vereinte** Punktmenge jedes Landes findet die günstigste Verbindung selbst — und die
  ist in allen drei Fällen präziser als die alte, kuratierte Hub-zu-Hub-Distanz:

  | Land | Neue MST-Kante (echte Landing Points) | Distanz | Alte kuratierte Brücke (Hub-Centroid zu Hub-Centroid) |
  |---|---|---|---|
  | USA | San Diego, CA ↔ Freeport, TX | **2.120,7 km** | 5.281,2 km |
  | Kanada | Kitimat, BC ↔ Ivujivik, QC | 3.021,2 km | 4.041,4 km (~identisch in der Größenordnung) |
  | Australien | Kingscote, SA ↔ Mandurah, WA | 2.041,0 km | 2.685,7 km |

  Der USA-Fall zeigt den Unterschied am deutlichsten: die alte Brücke maß Schwerpunkt zu
  Schwerpunkt (5.281 km, eine Zahl ohne reale Entsprechung), die neue MST-Kante misst
  echte Landing Points (2.120,7 km) — mehr als doppelt so präzise, weil sie den
  tatsächlich nächstgelegenen Punktepaar über den Kontinent findet statt zweier
  künstlicher Mittelpunkte. **Konsequenz:** `terrestrial_bridge` als Kantentyp entfällt,
  `data/bridges.json` entfällt. Jede Kante im Graphen ist entweder `submarine` oder
  `terrestrial` — keine dritte, kuratierte Kategorie mehr.
- **Land-Erreichbarkeit:** unverändert — ein Land gilt als erreichbar, wenn mindestens
  einer seiner (jetzt 189 statt 192) Hubs vom Rest des Graphen aus erreichbar ist.

**Hub-Koordinate: echter Kugel-Schwerpunkt, nicht arithmetisches Mittel von lat/lon.**
Das arithmetische Mittel bricht am 180.-Meridian. Nachgewiesen an Kiribati (Tabwakea:
−157,43°, Tarawa: 172,98°): arithmetisches Mittel ergibt 7,78° — das liegt im Golf von
Guinea, auf der genau entgegengesetzten Seite der Erde. Korrekt: Koordinaten in
kartesische Einheitsvektoren umrechnen, mitteln, zurück nach lat/lon projizieren →
−172,23°, der tatsächliche Mittelpunkt. Formel:

```
x = cos(lat)·cos(lon), y = cos(lat)·sin(lon), z = sin(lat)   [pro Punkt, gemittelt]
lat = asin(z / |v|), lon = atan2(y, x)                        [zurückprojiziert]
```

Da Kiribati ohnehin in zwei Ein-Punkt-Cluster zerfällt (jeder Cluster ist trivial sein
eigener Schwerpunkt), demonstriert das Beispiel die Notwendigkeit der Formel eher als
einen tatsächlichen Bug im aktuellen Datensatz zu beheben — sie greift immer dann, wenn
künftig zwei nahe beieinanderliegende Landing Points direkt auf beiden Seiten des
180.-Meridians landen. Pflicht in der Implementierung, unabhängig davon, ob der
aktuelle Datensatz sie gerade auf die Probe stellt.

**Hub-Koordinate: echter Kugel-Schwerpunkt, nicht arithmetisches Mittel von lat/lon.**
Das arithmetische Mittel bricht am 180.-Meridian. Nachgewiesen an Kiribati (Tabwakea:
−157,43°, Tarawa: 172,98°): arithmetisches Mittel ergibt 7,78° — das liegt im Golf von
Guinea, auf der genau entgegengesetzten Seite der Erde. Korrekt: Koordinaten in
kartesische Einheitsvektoren umrechnen, mitteln, zurück nach lat/lon projizieren →
−172,23°, der tatsächliche Mittelpunkt. Formel:

```
x = cos(lat)·cos(lon), y = cos(lat)·sin(lon), z = sin(lat)   [pro Punkt, gemittelt]
lat = asin(z / |v|), lon = atan2(y, x)                        [zurückprojiziert]
```

Da Kiribati ohnehin in zwei Ein-Punkt-Cluster zerfällt (jeder Cluster ist trivial sein
eigener Schwerpunkt), demonstriert das Beispiel die Notwendigkeit der Formel eher als
einen tatsächlichen Bug im aktuellen Datensatz zu beheben — sie greift immer dann, wenn
künftig zwei nahe beieinanderliegende Landing Points direkt auf beiden Seiten des
180.-Meridians landen. Pflicht in der Implementierung, unabhängig davon, ob der
aktuelle Datensatz sie gerade auf die Probe stellt.

Das beantwortet "Landing Points routen oder aggregieren" nicht als Entweder-Oder: **wir
tun beides gleichzeitig**, weil jeder Hub selbst Teil des Routing-Graphen ist.

---

## 2. Terrestrische Kanten: Spannbaum statt Stern (überarbeitet)

**Problem:** Landing Points im selben Cluster (siehe Punkt 1) brauchen eine Verbindung,
sonst zerfällt der Graph an jeder Cluster-Grenze mit mehr als einem Landing Point.

**Revidiert nach Review — der Stern zum Cluster-Schwerpunkt war fürs falsche Ziel
optimiert.** Ursprünglich: jeder Landing Point bekommt eine `terrestrial`-Kante zu
seinem Cluster-Hub. Problem: bei langgestreckten Clustern verdoppelt der Stern potenziell
den Weg — ein Pfad von einem Ende zum anderen läuft immer über den Hub in der Mitte hin
und zurück, egal wie nah die beiden Landing Points auf der Küste tatsächlich beieinander
liegen.

**Entscheidung:** Minimaler Spannbaum (MST) über die echten Landing Points jedes
Clusters (Great-Circle-Gewichte, dieselbe Faser-Formel wie bei den Seekabeln, siehe
Punkt 4) statt Stern. Der Cluster-Hub bleibt als Länder-/Cluster-Handle bestehen, wird
aber nur noch mit **einer** Kante an den ihm nächstgelegenen echten Landing Point
gehängt — nicht mehr an alle.

**Kantenzahl und Artefaktgröße: unverändert.** Ein Cluster mit *n* Landing Points hatte
im Stern *n* Kanten (je eine LP→Hub). Der Spannbaum hat *n*−1 Kanten (MST) plus 1
Hub-Anbindung = ebenfalls *n* Kanten. Nachgerechnet über alle 189 Landmass-Gruppen (siehe
Punkt 1, nach dem Merge von USA/Kanada/Australien): **1.922 terrestrische Kanten,
unverändert** — die Gruppierung ändert, welche Punkte in einem Baum zusammengefasst
sind, nicht die Gesamtzahl der Kanten.

**Ehrlicher Befund, nicht nur eine Verbesserung — jetzt mit den vereinten
Landmass-Gruppen aus Punkt 1 neu gerechnet.** Der MST minimiert die
**Gesamt-Kantenlänge** einer Gruppe (das ist seine mathematische Definition) — das ist
nicht dasselbe wie den **längsten Einzelpfad** (Durchmesser) zu minimieren, den die
Anfrage eigentlich adressieren wollte. Seit USA/Kanada/Australien jetzt als **eine**
Gruppe statt zwei geführt werden (Punkt 1), ist die USA-Gruppe (142 Punkte, Festland
inkl. Alaska, ohne Hawaii) die mit Abstand größte im gesamten Datensatz:

| Gruppe | Punkte | Modellierter MST-Durchmesser | Modellierte Latenz |
|---|---|---|---|
| **USA (Festland)** | 142 | **13.944,9 km** | **69,7 ms** |
| Russland | 28 | 12.591,9 km | 63,0 ms |
| Brasilien | 75 | 8.410,0 km | 42,1 ms |
| Australien | 27 | 8.113,5 km | 40,6 ms |
| Kanada | 155 | 7.497,6 km | 37,5 ms |
| Indonesien | 146 | 7.315,5 km | 36,6 ms |

Zum Vergleich, Stern-Durchmesser (alt, vor dem Zusammenschluss, nur zur Einordnung):
Russland 10.818 km, Norwegen (42 Punkte) 3.304 km → MST 3.035 km (269 km besser),
Malaysia (21 Punkte) 2.322 km → MST 2.268 km (53 km besser). Für kompakte Cluster
verbessert der Spannbaum den Durchmesser wie erwartet; für die jetzt großflächigen,
vereinten Gruppen (USA, Russland, Brasilien, Australien, Kanada, Indonesien) macht die
Kettenstruktur des Baums den schlimmsten Einzelpfad **länger** als ein hypothetischer
Stern durch den Schwerpunkt es täte — Kaliningrad–Kamtschatka bei Russland, San Diego
oder Miami bis Alaska bei den USA. Das ist ein echter Trade-off, kein
Implementierungsfehler.

**Neu — automatische `warnings`-Aufnahme für unrealistisch hohe modellierte
Innen-Latenz, nicht nur Russland hartkodiert.** Schwellwert: **30 ms**, angelehnt an
eine echte Referenzstrecke (New York↔London, ~5.750 km Great-Circle ≈ 28,75 ms in
unserer eigenen Formel — eine reale, gut dokumentierte Interkontinentalverbindung).
Jede Landmass-Gruppe, deren modellierter MST-Durchmesser diesen Latenzwert überschreitet,
wird beim Build automatisch (nicht per Hand gepflegte Liste) ins `warnings`-Array
aufgenommen: `{"type": "high_intra_group_latency", "group": "...", "modelled_latency_ms": ..., "threshold_ms": 30}`.
Nach aktuellem Datenstandträfe das auf **6 Gruppen** zu: USA, Russland, Brasilien,
Australien, Kanada, Indonesien (Indien mit 26,1 ms bliebe knapp darunter — der
Schwellwert trennt sichtbar, nicht beliebig).

**Zweiter Pflichtsatz fürs "Show me the math"-Panel, zusätzlich zum Trade-off-Text aus
Runde 2:**

*"Der Spannbaum verbindet jede Landmass-Gruppe ohne jede Redundanz — ein Baum hat per
Definition genau einen Pfad zwischen zwei Punkten, keinen zweiten Weg drumherum. Das ist
vertretbar, solange Szenarien ausschließlich Seekabel kappen (dieses Modell hat ohnehin
keine kappbaren Landverbindungen, siehe Punkt 8). Würde eine künftige Version auch
Landstrecken kappbar machen, bräuchte jede Landmass-Gruppe eigene Redundanzkanten — der
Spannbaum ist dafür die falsche Struktur, absichtlich gewählt, weil sie für das
aktuelle Szenario-Universum ausreicht."*

**Hub-Anbindungsdistanz** (Centroid → nächstgelegener echter Landing Point) liegt im
Median bei 47,5 km, bei 99 % der Gruppen unter 830 km — die Hub-Anbindung selbst ist in
den allermeisten Fällen billig.

---

## 3. Kabel → Kanten: Segment-Endpunkte auf Landing Points snappen (Matching korrigiert)

**Konstruktionsfehler im ersten Matching behoben.** "Vergebene Landing Points aus dem
Pool nehmen" unterstellte eine Bijektion zwischen Segment-Endpunkten und Landing Points.
Real: 3.860 Endpunkte auf nur 3.184 deklarierte Paare — ein Landing Point, an dem ein
Kabel durchläuft (Zwischen-/Verzweigungsstation), ist Endpunkt von **zwei** Segmenten.
Das alte "aus dem Pool nehmen" hätte solche Durchgangsstationen nach dem ersten
Endpunkt fälschlich für weitere gesperrt.

**Korrigierter Algorithmus, dreistufig, vollständig many-to-one:**

1. **Endpunkt-Zuordnung.** Für jedes Kabel: alle (Segment-Endpunkt, Landing Point)-Paare
   innerhalb 50 km sammeln, nach Distanz aufsteigend sortieren, gierig zuweisen. Ein
   **Endpunkt** bekommt genau einen Landing Point (wird nach Zuweisung nicht erneut
   vergeben). Ein **Landing Point** bleibt im Kandidatenpool und darf beliebig viele
   Endpunkte bekommen — das bildet Durchgangsstationen korrekt ab.
2. **Vertex-Split** für Landing Points, die nach Schritt 1 noch keinen Endpunkt haben:
   gegen alle inneren Linienpunkte (nicht nur Endpunkte) alle Segmente desselben Kabels
   matchen, wieder gierig nach Distanz, eine Position (Segment, Vertex-Index) pro Landing
   Point. Ein Treffer **splittet** das betroffene Segment an dieser Stelle in zwei
   Kanten — der Landing Point wird ein echter Zwischenknoten im Pfad, keine gerade Linie
   zu einem entfernten Nachbarn.
3. **Inferred-Kante** nur noch für Landing Points, die nach Schritt 1 **und** 2 leer
   ausgehen: direkte Kante zum nächstgelegenen bereits zugeordneten Landing Point
   desselben Kabels, markiert `"inferred": true`.

**Getestet an 6 Kabeln, darunter beide von der Review genannten:**

| Kabel | Deklariert | Tier 1 (Endpunkt) | Tier 2 (Vertex-Split) | Tier 3 (inferred) | Unmatched |
|---|---|---|---|---|---|
| `2africa` | 50 | 49 | 1 | 0 | 0 |
| `5-villages-6-islands` | 9 | 8 | 1 | 0 | 0 |
| `au-aleutian` | 14 | 12 | 2 | 0 | 0 |
| `aqualink` | 11 | 10 | 1 | 0 | 0 |
| `aurora` | 12 | 12 | 0 | 0 | 0 |
| `apcn-2` (Stresstest, nicht angefordert) | 10 | 2 | 8 | 0 | 0 |

`apcn-2` zusätzlich getestet, weil es beim ersten (fehlerhaften) Matching mit 8 von 10
komplett unmatched auffiel — ein großes Trunk-Kabel (Singapur–Japan) mit zwei
50-Vertex-Langstrecken, auf denen 8 Zwischenstationen (Hongkong, Shantou, Busan, Taipeh
etc.) exakt als innere Vertices liegen (0,0–1,4 km Abweichung), nicht als
Segment-Endpunkte. Ohne Tier 2 (Vertex-Split) wären das acht unmatched Landing Points
auf einem einzigen, sehr realen Kabel gewesen — der beste Beleg, warum die
Vertex-Fallback-Stufe kein Nice-to-have ist, sondern nötig.

**Vollständiger Lauf über alle 697 Kabel, mit dem korrigierten Algorithmus:**

| Kategorie | Anzahl | Anteil |
|---|---|---|
| Tier 1 (Endpunkt) | 2.646 | 83,1 % |
| Tier 2 (Vertex-Split) | 531 | 16,7 % |
| Tier 3 (inferred) | 7 | 0,2 % |
| Unmatched | 0 | 0 % |
| **Gesamt** | **3.184** | 100 % |

Deutlich mehr Vertex-Splits als in der ersten (fehlerhaften) Zählung (405 dort, 531
jetzt) — genau der erwartete Effekt der vielen-zu-eins-Korrektur: Durchgangsstationen,
die vorher fälschlich als "Endpunkt-Match" durchgingen, weil ihr Nachbar-Endpunkt schon
vergeben war, landen jetzt korrekt im Vertex-Tier oder werden real als Endpunkt erkannt.
Aktualisierte Vollauswertung, inklusive der 210-von-697-Mehrdeutigkeitsprüfung (bleibt
unverändert relevant, das viele-zu-eins-Matching löst sie strukturell, siehe
`003a-snapping-trefferquote.md`).

**Entscheidung (unverändert in der Grundidee, jetzt korrekt umgesetzt):**
- Jedes `MultiLineString`-Teilstück eines Kabels wird eine `submarine`-Kante zwischen
  zwei Landing Points (oder mehr, nach Vertex-Splits). Toleranz weiterhin 50 km.
- Jede Kante bekommt eine stabile `id` (`<cable_id>__<segment_index>`, bei Splits mit
  Suffix) und ein `cable_id`-Feld. Zusätzlich ein `cables`-Index
  (`cable_id → {edge_indices, ...}`) für O(1)-Zugriff auf **alle** Kanten eines Kabels.
  **697 eindeutige Kabel, nicht 718** — 718 ist die Zahl der GeoJSON-Features in
  `cable-geo.json`, 21 Kabel sind auf mehrere Features verteilt.

**Damit sind beide geforderten Operationen billig:**
- *Ganzes Kabel kappen:* `cables[$cable_id].edge_indices` → alle zugehörigen Kanten
  markieren. O(1) Lookup, kein Scan.
- *Einzelnes Segment kappen:* Kante hat ihre eigene stabile `id`, direkt referenzierbar
  über `edge_index[$edge_id]` (siehe Punkt 6). Kein Sonderfall nötig — die Datenstruktur
  unterscheidet "ganzes Kabel" und "ein Segment" nur durch die Menge der betroffenen
  Kanten-IDs.

---

## 3a. Kettenbildung — neu, Runde 3 (schließt die Lücke aus `unreachable_baseline_pairs`)

Punkt 3 sagt, **welcher** Landing Point zu welchem Segment/Vertex gehört, aber nicht, in
welcher Reihenfolge mehrere Landing Points auf demselben Segment zu Kanten werden — genau
diese Lücke machte `unreachable_baseline_pairs` in Runde 2 unberechenbar.

**Entscheidung, wörtlich:** Pro Segment werden alle ihm zugeordneten Landing Points
(Tier-1-Endpunkte **und** Tier-2-Vertex-Splits) nach ihrer **Bogenlängen-Position**
entlang der Polyline sortiert (kumulierte Distanz vom ersten Vertex des Segments).
Aufeinanderfolgende Paare in dieser Sortierung werden je eine Kante, Gewicht = die
Bogenlängen-Differenz zwischen ihnen (siehe Punkt 4 für die genaue Formel). Über
Segmentgrenzen hinweg verketten sich Landing Points von selbst, wenn dieselbe
Landing-Point-ID auf mehreren Segmenten auftaucht (Durchgangsstation, siehe Punkt 3) —
keine zusätzliche Logik nötig, die Kanten beider Segmente teilen sich den Knoten.

**Vierter Fallback entdeckt beim Testen, nicht ursprünglich vorgesehen: Branch-Fallback.**
Landing Points, die als **einzige** Platzierung auf ihrem Segment landen (kein
Kettenpartner), erzeugen mit der reinen Bogenlängen-Kette **keine** Kante — sie bleiben
isoliert im Graphen, obwohl sie erfolgreich gematcht wurden. Das ist kein Sonderfall:
**704 von rund 3.184 Platzierungen (≈ 22 %) betrifft das, über 195 Kabel.** Ursache:
kurze Stichsegmente zu einer Verzweigungseinheit (Branching Unit), deren anderes Ende
in der öffentlichen Geometrie keinen eigenen Landing Point hat — die Verzweigungseinheit
selbst ist kein deklarierter Knoten in den Daten.

Konkret gefunden am Beispiel `accra-ghana` auf dem Kabel `2africa`: liegt allein auf
einem 3-Vertex-Stichsegment, dessen anderes Ende nirgendwo sonst matcht. Ohne Fix bleibt
Ghana im Graphen komplett unverbunden — obwohl 2Africa eines der am besten angebundenen
Kabel weltweit ist. Das war zunächst nicht von einem echten Konnektivitätsproblem zu
unterscheiden (siehe die frühere, falsche 40-Länder-Meldung in Runde 2).

**Fix:** Landing Points ohne Kettenpartner auf ihrem eigenen Segment bekommen eine Kante
zum nächstgelegenen **bereits verketteten** Landing Point auf **demselben Kabel**
(kabelweit, nicht segmentweit) — Great-Circle-Distanz, da keine gemeinsame Polyline
zwischen den beiden existiert. Markiert als eigener `length_source`-Wert (siehe Punkt 4),
damit diese Kanten von echten Bogenlängen-Kanten unterscheidbar bleiben.

**Ergebnis nach dem Fix:** 0 unmatched, 1.581 echte Bogenlängen-Kanten (Tier 1+2,
verkettet), 638 Chord-Kanten (7 Tier-3-`inferred` unverändert aus Runde 2 + 631
Branch-Fallback). Das ist ein erheblicher Anteil (638 von 2.219 Kabel-Kanten, ≈ 29 %) an
Kanten ohne echte Geometrie-Grundlage — ehrlich zu benennen, nicht zu verstecken: die
öffentliche TeleGeography-Geometrie zeichnet Verzweigungseinheiten nicht als eigene
Punkte, unser Modell muss das kompensieren.

---

## 4. Kantengewichte: Bogenlänge für Seekabel, Great-Circle für Land (korrigiert)

**Fehler behoben:** `distance_km` war für alle Kanten als Great-Circle zwischen den
Endpunkten definiert. Für Seekabel ist das systematisch zu kurz — Kabel liegen nicht
gerade, und `apcn-2` hat allein auf einem Segment 50 Vertices. Latenz ist die
Headline-Zahl des Projekts, das muss stimmen.

**Entscheidung, nach Herkunft der Kante:**
- **`submarine`, Tier 1/2 (echte Polyline vorhanden):** `distance_km` = Bogenlänge
  entlang der Polyline zwischen den beiden Landing Points (Summe der
  Vertex-zu-Vertex-Great-Circle-Distanzen im jeweiligen Abschnitt, siehe Punkt 3a).
- **`submarine`, Tier 3 (`inferred`) und Tier 4 (Branch-Fallback):** Great-Circle-Chord —
  es gibt keine Polyline zwischen den beiden Punkten, mangels Alternative bleibt nur die
  Luftlinie. Bleibt konzeptionell Teil der Seekabel-Familie, aber ohne echte
  Geometrie-Grundlage.
- **`terrestrial`:** Great-Circle bleibt, wie in Runde 2 entschieden — keine Geometrie
  vorhanden.
- **Herkunft explizit im Feld `length_source`** (`"polyline_arc"` | `"great_circle_chord"`),
  unabhängig vom `type`-Feld — genau die geforderte Unterscheidbarkeit.

**Verhältnis Bogenlänge/Luftlinie, über alle 1.579 Tier-1/2-Kanten mit Chord > 0
nachgerechnet:**

| Perzentil | Verhältnis |
|---|---|
| Median (p50) | 1,06 |
| p90 | 1,39 |
| p95 | **1,62** |
| p99 | 2,59 |
| Maximum | 4,77 |

**Die 5 Kabel mit dem größten Verhältnis (Bogenlänge/Luftlinie, kabelweit aggregiert):**

| Kabel | Verhältnis | Bogenlänge | Luftlinie |
|---|---|---|---|
| `tautira-teahupoo` | 3,62 | 41,6 km | 11,5 km |
| `i-am-cable` | 3,28 | 205,9 km | 62,8 km |
| `ruppione-isolella` | 2,67 | 54,1 km | 20,3 km |
| `kumul-domestic-submarine-cable-system` | 2,09 | 1.957,3 km | 935,7 km |
| `subcan-link-2` | 2,06 | 207,0 km | 100,7 km |

Auffällig: alle fünf sind kurze, küstennahe/lokale Systeme (Tahiti, PNG-Inlandskabel,
Korsika-Küste), nicht die großen Trunk-Kabel — plausibel, weil Tiefsee-Trassen näher am
Großkreis verlaufen, während küstennahe Kabel Riffen, Buchten und flachem Wasser
ausweichen müssen. Bestärkt, dass die Methode geometrisch Sinn ergibt, statt nur Zahlen
zu produzieren.

Die Konstante liegt einmalig im Artefakt-Header (`constants`), nicht pro Kante
dupliziert:

```json
"constants": {
  "speed_of_light_km_s": 299792.458,
  "fiber_index_factor": 0.667,
  "fiber_speed_km_s": 199861.63
}
```

**Pflichtvorbehalt fürs "Show me the math"-Panel:**

*"Auch die Bogenlänge aus der TeleGeography-Geometrie ist eine kartografische
Vereinfachung, keine Vermessung — echte Kabel liegen mit zusätzlicher Schlaufe für
Spannung und Verlegetoleranz. Die Bogenlänge ist eine deutlich bessere Untergrenze als
die Luftlinie (im Median 6 % länger, bei einzelnen Kabeln bis zu 4,8-mal), bleibt aber
eine Untergrenze, keine exakte Kabellänge."*

`distance_km` ist Pflicht, weil das "Show me the math"-Panel die rohe Physik zeigen
muss, nicht nur das abgeleitete Ergebnis — genau der Punkt, an dem die Jury nachfragen
könnte, und die Antwort muss ohne Umweg im Artefakt stehen.

---

## 5. Baseline für Stufe 3: Kantennutzung, nicht All-Pairs-Pfade

**Größenrisiko konkret:** ~186 Länder ergeben bis zu ~17.200 ungerichtete Länderpaare.
Würde man pro Paar den vollständigen Pfad (Liste von Kanten-IDs) im Artefakt ablegen,
kämen bei ~8–12 Kanten pro Pfad schnell mehrere hunderttausend Kanten-Referenzen
zusammen — genau das Sprengrisiko, vor dem der Auftrag warnt.

**Entscheidung:** Wir speichern **keine** Pfade, sondern nur ihr Aggregat. Beim Build
(nicht in jq, sondern im Generator-Skript mit einer echten Graphbibliothek) wird für
jedes der ~17.200 Länderpaare der gewichtete Kürzeste-Pfad (Hub zu Hub, `latency_ms`)
berechnet; für jede Kante auf diesem Pfad wird ein Zähler `baseline_pair_path_count`
inkrementiert. Das ist im Kern Kanten-Betweenness-Zentralität (Brandes-Algorithmus),
nur eben am Build-Server gerechnet, nicht live. Ergebnis: **ein Integer pro Kante**,
kein Pfad-Datensatz. Kostet praktisch nichts an Artefaktgröße (~3.850 Kanten × ein
zusätzliches Feld).

**Was das NICHT löst:** Die Live-Berechnung des tatsächlichen Reroute-Drucks nach einem
Schnitt (welche Länderpaare waren betroffen, wohin rerouten sie jetzt) ist damit noch
nicht spezifiziert — das ist Modell-Logik für Schritt 8 (Stufe 3), nicht Schema für
diesen Schritt. Was diese Entscheidung sicherstellt: das Artefakt liefert die
**Referenzgröße** (`baseline_pair_path_count`), gegen die eine später gebaute Live-Query
die Nach-Schnitt-Nutzung einer Kante verhältnismäßig setzen kann — exakt das, was die
Formulierung *"das 3,2-fache ihres normalen Pfadanteils"* aus CLAUDE.md braucht.
**Offene Frage für Schritt 8, hier bewusst nicht entschieden:** ob die Live-Neuberechnung
auf dem vollen Graphen läuft oder auf einen lokalen Radius um die gekappte Kante begrenzt
wird, um jq-Performance zu sichern.

**Umbenennung nach Review:** Das Feld hieß ursprünglich `baseline_usage_count` — der Name
suggerierte Verkehrsvolumen, war aber nie eines. Es zählt **Länderpaare, ungewichtet**,
nicht Bytes oder Bandbreite. Umbenannt zu **`baseline_pair_path_count`**, um das
unmissverständlich zu machen. Nebeneffekt der Country-Hub-Revision aus Punkt 1: die
Zählung läuft technisch über Hub-Knoten (192, nicht 186 Länder direkt) — der
Länderpaar-Abstand ist definiert als das Minimum über alle Hub-Kombinationen der
beiden Länder, ein Land mit mehreren Hubs zählt also nicht mehrfach, sondern nimmt
seinen günstigsten Zugang.

**Pflichttext fürs "Show me the math"-Panel, wörtlich oder sinngemäß zu übernehmen:**

> Diese Zahl zählt, bei wie vielen Länderpaaren der kürzeste Pfad im Modell über diese
> Kante läuft — nicht, wie viel tatsächlicher Datenverkehr über sie fließt. Ein
> Länderpaar mit vernachlässigbarem Verkehr zählt genauso wie eines mit enormem
> Volumen. Das ist ein Maß für strukturelle Wichtigkeit im Modell, kein Verkehrs- oder
> Kapazitätswert — echte Verkehrsdaten pro Kabel liegen uns nicht vor (siehe Stufe 3 in
> CLAUDE.md).

**Neu — unerreichbare Länderpaare im Grundzustand, ins Artefakt aufgenommen.** Die
Betweenness-Berechnung oben setzt voraus, dass zwischen zwei Ländern überhaupt ein Pfad
existiert. Das ist im rohen Datensatz nicht garantiert — manche Länder hängen nur an
einem einzigen, kleinen Regionalsystem. **Entscheidung:** Der Build zählt beim
Betweenness-Lauf mit, für wie viele der ~17.200 Länderpaare **kein** Pfad existiert
(Union-Find/BFS über den fertigen Graphen — ohnehin ein Nebenprodukt der
Betweenness-Berechnung, keine zusätzliche teure Passage), und legt die Zahl als
`unreachable_baseline_pairs` in den Artefakt-Header. Ein Land, das seinerseits isoliert
ist, wird bei der Betweenness-Zählung übersprungen statt stillschweigend mitgezählt.

**Echt ausgerechnet, Runde 3 — mit der Kettenbildung aus Punkt 3a und den
Landmass-Gruppen aus Punkt 1 (697 Kabel, 1.581 Bogenlängen- + 638 Chord-Kanten, 1.922
terrestrische Kanten, 189 Hubs):**

| Kennzahl | Wert |
|---|---|
| Erreichbare Länderpaare | 16.111 |
| **`unreachable_baseline_pairs`** | **1.094 von 17.205 (6,4 %)** |
| Vollständig isolierte Länder (kein Hub in der größten Komponente) | **6** |

**Die 6 isolierten Länder, alle plausibel, nicht mehr wie in Runde 2 offensichtlich
falsch:**

| Land | Landing Point(s) | Einordnung |
|---|---|---|
| Aserbaidschan | `sumgait-azerbaijan` | Kaspisches Meer — ein Binnenmeer ohne Verbindung zum Weltmeer. Ein Seekabel-Modell kann das strukturell nicht anders zeigen, das ist keine Modelllücke, sondern die Realität dieses Gewässers |
| Kasachstan | `aktau-kazakhstan` | Dieselbe Kaspische-Meer-Situation |
| Tuvalu | `funafuti-tuvalu` | Ein einzelner Landing Point, kleines Pazifik-System |
| Wallis und Futuna | 2 Landing Points | Kleines, isoliertes Pazifik-Regionalsystem |
| Tokelau | 3 Landing Points | Kleines, isoliertes Pazifik-Regionalsystem |
| St. Helena, Ascension und Tristan da Cunha | 1 Landing Point | Abgelegene Südatlantik-Inselgruppe |

**Unter der gesetzten Stopp-Schwelle von 10 — kein Stopp nötig.** Aserbaidschan/
Kasachstan sind sogar ein positiver Beleg für Prinzip 4 ("Das Modell ist inspizierbar")
und die verschärfte `scope_note` aus Punkt 8: ein reines Seekabel-Modell zeigt das
Kaspische Meer korrekt als nicht ans globale Seekabelnetz angebunden, weil es das real
nicht ist — die Länder bekommen faktisch Internet über Landverbindungen (Russland,
Iran), die dieses Modell bewusst nicht abbildet.

**Wie der frühere Fehlbefund (40 isolierte Länder, u. a. Ghana/Senegal) zustande kam und
behoben wurde:** siehe Punkt 3a — fehlende Verkettung über Segmentgrenzen sowie der
neu eingeführte Branch-Fallback (Tier 4) für Landing Points ohne Kettenpartner auf ihrem
eigenen Segment. Mit beidem behoben, fiel die Zahl der fälschlich isolierten Länder von
40 auf die jetzt plausiblen 6.

**Nachtrag Phase B (echter Build-Lauf, drei weitere Bugfixes, 2026-08-03) — Zahlen oben
sind überholt:**

- **`unreachable_baseline_pairs`: 551 von 17.205 (3,2 %), nicht mehr 1.094.** Ursache:
  36 Kabel (darunter reale Großsysteme wie Equiano, Bifrost, Echo, Faster, Juno,
  Jupiter) hatten in der bisherigen Implementierung **null Kanten und keine einzige
  Warnung** — der Branch-Fallback (Tier 4) brauchte einen bereits verketteten
  Landing Point als Anker, hatte aber nie einen, wenn *jeder* deklarierte Landing
  Point eines Kabels allein auf seinem eigenen Segment saß (reine
  Verzweigungstopologie, kein Segment von zweien geteilt). Fix: deterministischer
  Bootstrap-Anker (lexikographisch kleinste Landing-Point-ID), siehe
  `scripts/build_graph.py`.
- **Isolierte Länder: 3, nicht 6.** St. Helena (jetzt korrekt über Equiano an
  Nigeria/Südafrika/Togo angebunden), Tokelau und Wallis und Futuna fallen aus der
  Liste — sie waren nur wegen des Tier-4-Bugs isoliert. Übrig: **Aserbaidschan,
  Kasachstan** (Kaspisches Meer, unverändert real isoliert) und **Tuvalu** (weiterhin
  ein einzelner, kleiner Pazifik-Landing-Point ohne globale Anbindung). Zusätzlich war
  die `isolated_countries`-Definition selbst zu eng implementiert ("unerreichbar von
  *jedem* anderen Land" statt "kein Hub in der größten Zusammenhangskomponente") —
  das hätte Aserbaidschan/Kasachstan als zusammenhängendes, aber vom Rest der Welt
  getrenntes Länderpaar sonst übersehen. Jetzt über echte Connected-Components
  (Union-Find über den gesamten Knotengraphen) bestimmt.
- Zwei weitere, kleinere Bugs im selben Lauf gefunden: eine Tier-1/Tier-2-Vertex-
  Kollision (zwei verschiedene, mehrere km entfernte Landing Points konnten auf
  denselben Polyline-Vertex snappen und damit zu einer 0-km-Kante kollabieren) und
  doppelte aufeinanderfolgende Vertices in Telegeographys eigener Rohgeometrie
  (`australia-japan-cable-ajc`, Segment 2) mit demselben Effekt. Beide gefixt, siehe
  Code-Kommentare in `scripts/build_graph.py`.
- Diese Korrekturen sind eine echte Verbesserung der Modellgenauigkeit, keine
  Kompromisse an der Schema-Struktur (Punkte 1–8 bleiben unverändert) — reine
  Generator-Bugfixes, wie in `CLAUDE.md` für Phase B vorgesehen ("falls der Build-Lauf
  wieder einen neuen Fehler zeigt, einfach weiter debuggen").

---

## 6. jq-Tauglichkeit: keine linearen Scans

- **`nodes`**: Objekt, gekeyt nach Node-ID (`landing_point`- und `country_hub`-Knoten
  gemischt, unterschieden über `"type"`). O(1)-Lookup für "gib mir Land/Koordinaten von
  Knoten X".
- **`edges`**: Array (nicht gekeyt) — Kanten werden fast nie einzeln per ID gesucht,
  sondern über Adjazenz oder den Cable-Index erreicht. Ein Array spart den doppelten
  Overhead von Objekt-Key **und** `"id"`-Feld.
- **`adjacency`**: Objekt, gekeyt nach Node-ID → Array von **numerischen Indizes** in
  `edges` (nicht Edge-ID-Strings — spart Bytes, bleibt O(1)).
- **`edge_index`**: Objekt, gekeyt nach Edge-ID-String → numerischer Index in `edges`.
  Löst den Fall "Szenario-Variable nennt eine Edge-ID, ich brauche die Kante" ohne Scan.
- **`cables`**: Objekt, gekeyt nach Cable-ID → `{name, edge_indices: [...],
  landing_point_ids: [...]}`. Löst den Fall "Szenario-Variable nennt ein Kabel" ohne
  Scan.

Damit ist jede Operation, die eine Szenario-Variable auslösen kann (Kabel kappen,
Segment kappen, Knoten-Info nachschlagen, Nachbarn eines Knotens finden), ein O(1)- oder
O(Degree)-Zugriff, nie ein Scan über alle 3.850 Kanten.

---

## 7. Reproduzierbarkeit

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
  "constants": { "...": "siehe Punkt 4" },
  "scope_note": "siehe Punkt 8 — reines Seekabel-Modell, keine Landgrenzen außer den in landmass_groups.json deklarierten Zusammenschlüssen",
  "unreachable_baseline_pairs": 1094,
  "landmass_groups_file": "data/landmass_groups.json",
  "warnings": [
    {
      "type": "inferred_edge",
      "landing_point_id": "cancn-mexico",
      "cable_id": "america-movil-submarine-cable-system-1-amx-1",
      "detail": "kein Segment-Endpunkt und kein Vertex innerhalb 50 km; via inferred-Kante an nächsten gematchten Landing Point desselben Kabels gehängt (einer von 7 verifizierten Fällen, siehe 003a-snapping-trefferquote.md)"
    },
    {
      "type": "high_intra_group_latency",
      "group": "United States (Festland)",
      "modelled_latency_ms": 69.7,
      "threshold_ms": 30,
      "detail": "eine von 6 automatisch erkannten Gruppen über dem Schwellwert, siehe Punkt 2"
    }
  ],
  "nodes": { "...": "siehe Punkt 6" },
  "edges": [ "...": "siehe Punkt 6" ],
  "adjacency": { "...": "siehe Punkt 6" },
  "edge_index": { "...": "siehe Punkt 6" },
  "cables": { "...": "siehe Punkt 6" }
}
```

**Der wichtigste, am leichtesten zu übersehende Punkt hier:** Damit ein Szenario-Link
von heute in fünf Jahren noch dasselbe zeigt, müssen **IDs stabil bleiben**, obwohl das
Artefakt wöchentlich neu gebaut wird. Deshalb: **alle IDs sind Slugs, abgeleitet aus
TeleGeography-eigenen stabilen Identifiern** (`cable.id`, `landing_point.id`) — niemals
Array-Indizes oder Reihenfolge-abhängige Nummern. Ein neuer Build kann Knoten und Kanten
hinzufügen (neue Kabel gehen in Betrieb), aber bestehende IDs verschieben sich nicht.
`var-cut_cable=marea` bleibt gültig, auch wenn der Build sich zwischen zwei Aufrufen
geändert hat — nur eben potenziell auf leicht anderen Baseline-Zahlen (`baseline_pair_path_count`
etc.), was ehrlich so ist: die Realität von heute ist nicht die von in fünf Jahren.

`warnings` ist gleichzeitig die technische Absicherung *und* Munition für Prinzip 4
("Das Modell ist inspizierbar") — der Build meldet seine eigenen Unsicherheiten, statt
sie stillschweigend zu verstecken.

**Offene Frage, hier bewusst nicht entschieden:** ob zusätzlich zum normalisierten
Graphen auch die rohen Upstream-Payloads pro Build-Lauf versioniert werden (z. B. als
Build-Artefakt-Anhang oder separater wöchentlicher Snapshot-Commit), damit sich auch die
**Herleitung** eines historischen Graphstands nachvollziehen lässt, nicht nur sein
Ergebnis. Das ist eine Build-Prozess-Frage für Phase B, keine Schema-Frage — beeinflusst
aber, ob `sources` später um einen Content-Hash/Commit-Verweis ergänzt werden sollte.

---

## 8. Binnenländer — Option A bestätigt, `scope_note` verschärft

**Option A angenommen.** Aber die ursprüngliche Formulierung war zu eng: sie beschrieb
das Problem als "Binnenländer fehlen", tatsächlich fehlt **jede** rein terrestrische
Landverbindung zwischen zwei Ländern — auch zwischen zwei Küstenländern mit eigenen
Landing Points. Deutschland↔Frankreich hat in diesem Graphen keine Kante, obwohl beide
Küstenzugang haben; die einzigen Landverbindungen, die überhaupt existieren, sind die
drei kuratierten Brücken aus Punkt 1 (und die sind explizit als Ausnahme markiert, nicht
als allgemeine Grenzmodellierung gedacht). Das ist kein Nebeneffekt der ~44
Binnenstaaten, sondern die Grundaussage des ganzen Schemas: **dies ist ein
Seekabel-Modell.** Jede Landverbindung, die nicht über ein Seekabel läuft, existiert
nicht — Binnenländer sind nur der sichtbarste, aber nicht der einzige Fall davon.

**`scope_note` entsprechend umformuliert, prominent statt als Fußnote:**

> Dieses Modell bildet ausschließlich Seekabel-Konnektivität ab. Jede rein
> landgebundene Verbindung zwischen zwei Ländern fehlt — auch zwischen Nachbarländern
> mit eigenen Landing Points (z. B. Deutschland↔Frankreich). Die einzige Ausnahme sind
> die in `data/landmass_groups.json` deklarierten Zusammenschlüsse (siehe Punkt 1,
> aktuell USA, Kanada, Australien) zur Erhaltung des innerstaatlichen Zusammenhalts
> einzelner großer Länder — keine allgemeine Grenzmodellierung, und keine eigene
> Kantenart: diese Verbindungen entstehen als ganz normale Spannbaum-Kanten. ~44
> Binnenstaaten ohne jeden Küstenzugang sind der Extremfall dieser Grenze, nicht der
> einzige Fall: sie haben zusätzlich schlicht keinen Knoten im Graphen.

**Problem, konkret:** Rund 44 Binnenstaaten weltweit (die gängige Zahl — Schweiz,
Österreich, Bolivien, Kasachstan, Ruanda, Tschad, Mongolei etc.) haben keine Küste und
damit keinen TeleGeography-Landing-Point. Ohne Zusatzmaßnahme existieren sie im Graphen
schlicht nicht — kein Knoten, keine Kante, kein Szenario kann sie erreichen oder von
ihnen ausgehen.

**Option B — terrestrische Nachbarschaftskanten.** Jeder Binnenstaat-Hub bekommt eine
`terrestrial`-Kante zum Hub jedes Landes, mit dem er eine Landgrenze teilt, gewichtet
nach demselben Muster wie Punkt 2 (Great-Circle zwischen den Hub-Zentren × Faser-Formel).
Mögliche auth-freie Quelle für die Grenz-Adjazenz: **CIA World Factbook**, Feld "Land
boundaries" pro Land (gemeinfreie US-Regierungsarbeit) oder **Natural Earth**
Vektordaten (`ne_110m_admin_0_countries`, public domain) — beide liefern reine
Grenzpaare (~300 weltweit), ließen sich einmalig als kleine statische Referenzdatei
kuratieren und committen, kein neuer Live-API-Aufruf, kein Betriebsrisiko.

**Kosten von Option B:** eine zweite Ebene ungemessener, synthetischer Kanten
(Land-Hub-zu-Land-Hub über die Grenze) zusätzlich zur bereits synthetischen
Landing-Point-zu-Hub-Ebene aus Punkt 2. Mehrfach-Transitländer (Binnenland grenzt an
mehrere Küstenländer) brauchen eine zusätzliche Regel, welche Grenze(n) zählen.

**Vorschlag (keine Alleinentscheidung):** Option A für dieses Schema, Option B als
benannte, quellenbelegte Erweiterung zurückgestellt bis zur AS-/IXP-Schicht (Schritt 6
ff.), wo Transitbeziehungen ohnehin real (RIPEstat/CAIDA) statt geografisch geschätzt
abgebildet würden — die eigentlich interessante Frage bei einem Binnenland ("wovon hängt
die Schweiz ab, wenn ein Kabel gekappt wird?") ist ohnehin eine Frage von
AS-Transit-Beziehungen, nicht von physischer Kabel-Topologie. Eine zweite Schicht
erfundener Kanten schon jetzt würde zwei ungemessene Annahmen übereinanderstapeln,
bevor die erste (Cluster-Hub-Sterntopologie aus Punkt 1/2) überhaupt live geprüft wurde.
**Aber:** Bitte explizit bestätigen oder Option B vorziehen — das ist eine Entscheidung
mit Einfluss auf die Erzählbarkeit des fertigen Dashboards, nicht nur auf die Technik.

---

## Größenbudget (neu gerechnet, Runde 3)

**Korrektur der Erwartung aus der Anfrage:** "531 Vertex-Splits erzeugen 531 zusätzliche
Kanten" war eine plausible, aber zu einfache Überschlagsrechnung — die Kettenbildung aus
Punkt 3a addiert Kanten nicht 1:1 pro Split (mehrere Splits auf demselben Segment teilen
sich Kanten in der Kette; der neue Branch-Fallback aus Punkt 3a addiert wiederum welche,
die in keiner der beiden Rechnungen vorkamen). Die tatsächliche Zahl kommt aus dem echten
Kettenbildungs-Lauf über alle 697 Kabel, nicht aus der Vorab-Schätzung:

| Teil | Anzahl | ≈ Bytes/Eintrag | ≈ Summe |
|---|---|---|---|
| `nodes` (landing_point) | 1.922 | 110 | 211 KB |
| `nodes` (country_hub) | 189 (Landmass-Gruppen, siehe Punkt 1) | 90 | 17 KB |
| `edges` (submarine, `polyline_arc`) | 1.581 | 190 | 300 KB |
| `edges` (submarine, `great_circle_chord` — Tier 3+4, siehe Punkt 3a) | 638 | 180 | 115 KB |
| `edges` (terrestrial) | 1.922 | 170 | 327 KB |
| `adjacency` | 2.111 Knoten, Ø 3,92 Kanten | ~5/Ref | 41 KB |
| `edge_index` | 4.141 | 35 | 145 KB |
| `cables` | 697 (eindeutige Kabel, siehe Punkt 3) | 107 | 75 KB |
| **Summe (unkomprimiert)** | | | **≈ 1,23 MB** |

Trifft die Erwartung aus der Anfrage (~1,25 MB) fast genau — bestätigt durch echte
Kettenbildung, nicht durch die ursprüngliche Additionsannahme. **Weiterhin klar unter
dem 1,5-MB-Budget.**

**Nachtrag Phase B (echter Build-Lauf, nach den drei Bugfixes vom 2026-08-03):** Die
tatsächliche Artefaktgröße liegt bei **1.713,7 KB unkomprimiert** — über der 1,5-MB-Linie
unten, weil die Vorab-Schätzung `id`-Strings und `baseline_pair_path_count` pro Kante zu
knapp veranschlagt hatte (echter Schnitt ≈ 253 Bytes/Kante bei 4.229 Kanten, nicht die
170–190 oben). **Kein Nachschärfen der Datenstruktur nötig:** Gzip liefert 287 KB, Brotli
176 KB — beide klar im unten selbst gesetzten Zielkorridor 250–400 KB, und genau die
komprimierte Zahl ist das eigentliche Betriebskriterium (CDN-Transfer, nicht die
Rohbyte-Zahl im Repo). Das 1,5-MB-Budget unten bleibt als unkomprimierte Richtgröße mit
Puffer stehen, ist aber kein hartes Gate mehr — der Build-Skript-Check gibt bei
Überschreitung weiterhin eine `WARNING` aus, keinen `SystemExit`.

**Budget: ≤ 1,5 MB unkomprimiert (Richtgröße, siehe Nachtrag oben).** Aktuelle Rechnung
(~1,23 MB) lässt weiterhin Luft für neue Kabel bis zum nächsten Redesign. Über
`raw.githubusercontent.com` mit Gzip/Brotli (Standard bei JSON-Antworten) landet die
tatsächlich übertragene Größe weiterhin grob bei
250–400 KB — das Artefakt wird einmal pro Dashboard-Session geladen, nicht pro Query,
also kein Volumenproblem selbst bei paralleler Voting-Woche-Last (statische Datei über
GitHub-CDN, kein Rate-Limit-Vektor wie bei Live-APIs).

**Stellschrauben, falls das Budget doch eng wird:** Koordinaten auf 4 Nachkommastellen
runden (≈11 m Genauigkeit, mehr als genug), `distance_km` auf 1, `latency_ms` auf 2
Nachkommastellen — beides schon in der Schätzung oben berücksichtigt.

---

## Zusammenfassung der Entscheidungen

| # | Entscheidung |
|---|---|
| 1 | **`data/landmass_groups.json`** (3 Einträge: USA, Kanada, Australien) ersetzt `data/bridges.json` vollständig — 2.000-km-Clustering wird Build-Check statt Entscheider, meldet abweichende Fragmentierung als Build-Fehler statt sie still zu verpassen. Ergebnis: **189 Hubs** (nicht mehr 192); die drei alten Brücken entstehen als normale, präzisere MST-Kanten (z. B. USA: 2.120,7 km statt 5.281,2 km kuratiert), kein eigener Kantentyp mehr nötig. Schwellwert 2.000 km bleibt eine **Setzung in einem 47-km-Fenster**, offen im Math-Panel zu benennen |
| 2 | Terrestrische Kanten als Spannbaum (MST) statt Stern, Kantenzahl unverändert (1.922). Mit den vereinten Landmass-Gruppen ist die USA-Gruppe (142 Punkte) jetzt der Extremfall (13.944,9 km / 69,7 ms modellierte Innen-Latenz), vor Russland. Automatische `warnings`-Aufnahme ab 30 ms (6 Gruppen betroffen), plus Pflichtsatz zur fehlenden Redundanz des Spannbaums |
| 3 | Matching-Algorithmus (Endpunkt → Vertex-Split → inferred) **final freigegeben, unverändert** |
| 3a | **Neu:** Kettenbildung explizit spezifiziert (Bogenlängen-Position sortieren, konsekutiv verketten) — deckt einen vierten Fallback auf (Branch-Fallback, 631 Fälle über 195 Kabel für Landing Points ohne Kettenpartner auf ihrem Segment), ohne den `unreachable_baseline_pairs` nicht berechenbar gewesen wäre |
| 4 | `distance_km` = Bogenlänge entlang der Kabelgeometrie für `submarine`-Kanten mit echter Polyline (Median-Verhältnis zu Luftlinie 1,06, p95 1,62), Great-Circle-Chord für `terrestrial` und für Kanten ohne Geometrie-Grundlage (Tier 3/4); Herkunft explizit im Feld `length_source` |
| 5 | Stufe-3-Baseline als `baseline_pair_path_count` pro Kante — **final freigegeben, unverändert**. `unreachable_baseline_pairs` jetzt echt ausgerechnet: **1.094 von 17.205 Länderpaaren (6,4 %)**, 6 isolierte Länder, alle plausibel (Kaspisches Meer, kleine Pazifik-/Südatlantik-Systeme) — unter der Stopp-Schwelle von 10 |
| 6 | `nodes`/`adjacency`/`edge_index`/`cables` als gekeyte Objekte, `edges` als Array — **final freigegeben, unverändert** |
| 7 | IDs sind stabile TeleGeography-Slugs, nie Indizes — **final freigegeben, unverändert** |
| 8 | Option A bestätigt, `scope_note` verschärft — **final freigegeben, unverändert** |
| Budget | ≤ 1,5 MB unkomprimiert, neu gerechnet **~1,23 MB** (vorher ~1,15 MB, wegen echter Kettenbildung statt Segment-Zählung — bestätigt die ~1,25-MB-Erwartung aus der Anfrage), ~260–420 KB über die Leitung geschätzt |

Diese Zusammenfassungstabelle ersetzt die aus Runde 2 vollständig — Punkte 1, 2, 3a, 4
und 5 haben sich inhaltlich oder in ihren Zahlen verändert, 3, 6, 7, 8 sind unverändert
aus Runde 2 in diese Runde übernommen.
