# Gemeinsame Assets

- `brand/teichwiese.svg`: nachgezeichnetes Logo, Text als Pfade, korrigiertes fünftes Fenster.
- `fonts/NunitoSans-ExtraBold.ttf`: statische Instanz (Gewicht 800) der Google-Fonts-Version von Nunito Sans. Andere Achsen entsprechen den Standardwerten der Quelldatei. Lizenz: SIL Open Font License, siehe `fonts/OFL.txt`.
- `images/ansicht-01.jpg` bis `ansicht-03.jpg`: optimierte Kopien der bereitgestellten Dateien `3D - 01.jpg` bis `3D - 03.jpg`. Originale bleiben in den Projektunterlagen. Visualisierungen sind kein Nachweis des aktuellen Bauzustands.

- `brand/teichwiese-obstbaeume.png`: aktuelle Logovariante mit Obstbäumen (transparentes PNG, zugeschnitten aus `TEICHWIESE mit skulpturalen Obstbäumen.png`). Markenfarben daraus: Grün `#024C20`, Gold `#C9980A`, Anthrazit `#26261E`.
- `images/modell-*.jpg`: Renderings des 3D-Modells (Blender), erzeugt mit `scripts/blender/build_teichwiese.py`. `uebersicht` (von Südwesten über Billa), `panorama` (von Westen auf die Schaufronten), `b54` und `abend` (Bauteil 1 von der B54), `einfahrt-sued` (Zufahrt gegenüber Billa), `eingang`, `hero` (Ecke Bauteil 1 mit Logotafel und viel Himmel für Headlines, Variante 04), `draufsicht` (senkrecht, Norden oben, zur Lagekontrolle).
- `images/modell-*-v5.jpg` und `3d/teichwiese-v5.glb`: Stand für Variante 05 (zeitgemäße Fahrzeuge in verschiedenen Farben, zusätzlich `lager` mit den Lagertoren an der Rückseite), erzeugt mit `--tag v5`. Die Dateien ohne Suffix bleiben für die Varianten 03 und 04 unverändert.
- `3d/teichwiese.glb`: vereinfachtes 3D-Modell für das Web (glTF, Draco-komprimiert, ca. 1,5 MB) mit Grundstück, Bauteilen 1–4 und naher Umgebung.

Grundlage des Modells: Plan „Entwurf 3“ vom 25.10.2025 (Grundrisse, Systemschnitt, Übersicht M 1:1000). Lage: östlich der B54 auf Gst. 110 ff., nördlich anschließend an Gst. 105 gegenüber Billa; Bauteil 1+2 im Süden (Ortsseite), Bauteil 3 und 4 im Norden. Eine Zufahrt als vierter Knotenarm gegenüber der geplanten Aufschließung West, nach der verkehrstechnischen Stellungnahme vom 14.12.2023; Lage abgegriffen, nicht vermessen. Bauteil 2 ist spiegelgleich zu Bauteil 1; für die Bauteile 3 und 4 wird mangels Grundrissen derselbe Gebäudetyp angenommen. Fassaden, Holzlamellen, PV-Module, Bepflanzung, Stellplätze, Zufahrten, Stelen und Fahrzeuge sind Gestaltungsannahmen nach den vorhandenen Renderings. Die Bilder sind Visualisierungen und weder Zusage zu Ausstattung, Flächen, Zufahrten oder Kooperationen noch Nachweis des Bauzustands. Mieter- oder Firmennamen sind bewusst nicht dargestellt.

Umgebung im Modell, bei Verwendung der Bilder oder des Modells anzugeben: Orthofoto © basemap.at (CC BY 4.0), Gebäude und Straßen © OpenStreetMap-Mitwirkende (ODbL), Gelände: Terrain Tiles (Mapzen/AWS, u. a. Land Österreich DGM). Nachbargebäude sind vereinfacht, Höhen und Dachformen geschätzt.

Alle Varianten referenzieren dieselben Dateien. Referenz-Screenshots anderer Websites liegen absichtlich ausserhalb des veröffentlichten Website-Ordners.
