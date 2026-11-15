# TEICHWIESE – Website-Varianten

Statische Entwurfsumgebung mit gemeinsam genutzten Assets und GitHub-Pages-Veröffentlichung. Keine Installation oder Build-Abhängigkeiten nötig.

## Struktur

| Pfad | Zweck |
|---|---|
| `docs/index.html` | Öffentliche Auswahl aller Varianten |
| `docs/variants.json` | Titel, Beschreibung, Vorschaubild und Pfad je Variante |
| `docs/variants/<id>/index.html` | Eigenständiger Webentwurf |
| `docs/assets/` | Öffentliche, wiederverwendbare Bilder, Logo und Schrift |
| `docs/shared/` | Gemeinsames CSS und Index-Script |
| `assets/references/` | Referenzanalyse und Screenshots, nicht im Pages-Paket |
| `assets/templates/` | Inhaltsvorlagen für die weitere Entwicklung |
| `.github/workflows/pages.yml` | Prüft und veröffentlicht `docs/` bei Änderungen auf main |

Das Repository ist öffentlich. Auch Dateien ausserhalb von `docs/` sind über GitHub sichtbar. Vertrauliche Pläne, Kontaktdaten und interne Unterlagen gehören nicht hierher. Die ursprünglichen PDF-Pläne wurden nicht übernommen.

## Lokal ansehen

```sh
python3 scripts/check_site.py
python3 -m http.server 8000 --directory docs
```

Im Browser `http://localhost:8000` öffnen. Nicht per `file://`, weil die Auswahl `variants.json` lädt.

## Assets hochladen

Im GitHub-Ordner `docs/assets/images` → Add file → Upload files → Commit auf main. Die Asset-Seite enthält einen direkten Upload-Link. Alternativ per Git hinzufügen und pushen. Kurze Dateinamen ohne Leerzeichen verwenden; Webbilder vorab optimieren. Danach im HTML der gewünschten Variante referenzieren. Gemeinsame Pfade: `../../assets/images/datei.jpg` aus einer Variante. Das ist ein GitHub-Uploadprozess, kein anonymes Upload-Backend der Website.

## Neue Variante

1. `docs/variants/01-natur/` nach `docs/variants/03-name/` kopieren.
2. Titel und Inhalt ändern; Gestaltung in eigener CSS-Datei ergänzen, falls andere Varianten unverändert bleiben sollen.
3. Eintrag in `docs/variants.json` ergänzen: `id`, `title`, `description`, `path`, `image`.
4. Lokale Prüfung ausführen und auf main committen. Die Indexseite baut die Auswahl automatisch aus der JSON-Datei.

## GitHub Pages

Einmalig Settings → Pages → Build and deployment → Source: **GitHub Actions** auswählen. Danach veröffentlicht der Workflow Änderungen automatisch. Erwartete URL: `https://wasabrot.github.io/teichwiese/`. Aktivierung und tatsächlicher Live-Test werden separat verifiziert; dieser Text allein bestätigt keine erfolgreiche Veröffentlichung.

Testmarker: `TW-ROUNDTRIP-001`. Für einen vollständigen Test: grüner Actions-Run, HTTP 200 auf Index und Varianten, sichtbares Logo/Bilder und geladene Schrift, funktionierender Rücklink.

## Assets und Entwurfsstatus

Logo: TEICHWIESE mit Nunito Sans ExtraBold. Drei optimierte JPGs aus den vom Eigentümer bereitgestellten Projektvisualisierungen. Herkunft und Fontlizenz siehe `docs/assets/README.md`. Texte sind erste Gestaltungsproben; keine erfundenen Mietpreise, Flächenangaben oder Kontaktdaten. Die Entwurfsseiten setzen noindex; sie sind dennoch öffentlich erreichbar.

## Review-Verlauf: eine feste URL

`docs/index.html` bleibt der Einstieg. Die Variantenliste wächst mit jedem neuen Review-Stand; höchste `sequence` steht oben. Jeder JSON-Eintrag enthält zusätzlich `version`, `sequence`, `date` (YYYY-MM-DD) und `changes` (Liste kurzer Änderungen). Datum bezeichnet den Entwurfstag, nicht eine bestätigte Veröffentlichung. Bestehende Varianten-URLs bleiben erhalten. Bei einer neuen gestalterischen Iteration einen neuen Variantenordner anlegen, den bisherigen Stand nicht überschreiben.

Gemeinsame Assets nur ersetzen, wenn alle bisherigen Varianten die Änderung erhalten sollen. Für historische Vergleichbarkeit bei einer Bild-/Logoänderung einen neuen Dateinamen verwenden. Bei grösseren Stiländerungen eine eigene CSS-Datei je Variante anlegen; geteiltes CSS wirkt auf ältere Varianten mit.

Der Workflow prüft nach dem Deployment die öffentliche URL mit `scripts/check_live.py`. Erfolg bedeutet: Testmarker, beide ersten Varianten, Logo, Schrift und Bild sind öffentlich abrufbar.
