# gbp-audit

Mandantenfähige CLI-App, die für beliebige Kunden (vom Einzelstandort bis zur
120+-Filialkette) automatisiert Google-Unternehmensprofile (GBP) findet, gegen
einen festen Kriterienkatalog prüft, einen Audit-Score je Standort berechnet
und einen priorisierten Mängelbericht als Excel-Datei (optional zusätzlich als
HTML-Dashboard) erzeugt.

Als Eingabe genügt die Domain bzw. die URL der Kontakt-/Standortseite des
Kunden - die App extrahiert daraus die Standorte (NAP-Daten), findet die
zugehörigen Google-Unternehmensprofile und führt den Audit durch.

## Zwei Betriebsmodi

- **Modus A - "Public Audit" (Standard, nur Domain nötig):** Prüfung auf Basis
  der Google **Places API (New)**. Erfordert lediglich einen API-Key mit
  aktivierter Abrechnung. Deckt Existenz/Auffindbarkeit, Basisdaten, Kategorien,
  reguläre Öffnungszeiten, Bewertungs-Kennzahlen und ein Foto-Indiz ab.
- **Modus B - "Full Audit" (optional):** Zusätzliche OAuth-Anbindung an das
  GBP-Konto des Kunden (Business-Profile-APIs von Google). Erst damit sind
  Beschreibung/Attribute, vollständige Foto-/Bewertungs-/Q&A-Prüfung,
  Leistungen/Produkte und die Performance-Baseline (Impressionen, Klicks,
  Wegbeschreibungen) auswertbar.

Jeder Check deklariert, in welchem Modus er läuft. Im Public Audit erscheinen
Modus-B-Checks im Report unter "Nicht geprüft" - das dient zugleich als
Verkaufsargument für den Full Audit.

Die App ist read-only: es wird nie in ein GBP-Profil geschrieben, keine
Bewertungsantworten generiert und keine Google-Suche/Maps gescraped - GBP-Daten
kommen ausschließlich über die offiziellen APIs. Gecrawlt wird nur die Website
des Kunden (für Discovery/NAP-Abgleich), unter Beachtung der robots.txt.

## Einrichtung

### 1. Python-Umgebung

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Places-API-Key (erforderlich, für Modus A)

1. In der [Google Cloud Console](https://console.cloud.google.com/) ein Projekt
   anlegen oder auswählen.
2. Unter **APIs & Dienste -> Bibliothek** die **"Places API (New)"** aktivieren.
3. Unter **Abrechnung** ein Abrechnungskonto verknüpfen (ohne aktivierte
   Abrechnung liefert die API 401/403-Fehler, auch im kostenlosen Kontingent).
4. Unter **APIs & Dienste -> Zugangsdaten -> Anmeldedaten erstellen -> API-Key**
   einen Key erzeugen und auf "Places API (New)" einschränken.
5. Den Key in `.env` als `GOOGLE_PLACES_API_KEY` eintragen.

### 3. OAuth + GBP-API-Quota (optional, für Modus B)

1. In derselben Google-Cloud-Console unter **APIs & Dienste -> Zugangsdaten ->
   Anmeldedaten erstellen -> OAuth-Client-ID** einen Client vom Typ
   **"Desktop-App"** anlegen, das JSON herunterladen.
2. Pfad zur JSON-Datei in `.env` als `GOOGLE_OAUTH_CLIENT_SECRET_FILE`
   eintragen.
3. Die Business-Profile-APIs (Account Management, Business Information,
   Performance, My Business v4) haben standardmäßig **Quota = 0**. Zugriff
   muss über das offizielle
   [GBP-API-Antragsformular](https://developers.google.com/my-business/content/prereqs#request-access)
   beantragt werden (Google prüft manuell, das kann einige Tage dauern).
4. Sobald der Zugriff freigeschaltet ist: `gbp-audit auth <kunde>` ausführen.
   Das öffnet den OAuth-Consent-Flow im Browser und speichert den Token unter
   `clients/<kunde>/token.json`. Ab dann läuft `gbp-audit run <kunde>`
   automatisch im Modus B.

Ohne Schritt 3/4 bleibt die App voll nutzbar - sie arbeitet dann dauerhaft im
Modus A.

## Mandantenstruktur

```
clients/<kunde>/
  config.yaml     # kundenspezifische Overrides von config.yaml (Gewichtungen,
                   # Soll-Hauptkategorie, erwartete Attribute, Bewertungs-
                   # Keywords, ...)
  locations.yaml   # extrahierte/bestätigte Standorte inkl. GBP Place-ID
  token.json       # OAuth-Token für Modus B (falls eingerichtet)
  runs/YYYY-MM-DD/ # Rohdaten (JSON) je Lauf, Basis für 'diff' und Performance-Deltas
  output/          # generierte Excel-/HTML-Reports
```

`clients/` wird standardmäßig nicht versioniert (siehe `.gitignore`) - dort
liegen kundenspezifische NAP-Daten und Rohdaten aus den GBP-APIs.

## CLI-Befehle

```bash
gbp-audit client add <name> --url https://beispiel-gmbh.de   # Kunde anlegen, Discovery + Matching starten
gbp-audit client list                                        # alle Kunden anzeigen
gbp-audit discover <kunde>                                   # Standorte neu von der Website extrahieren
gbp-audit match <kunde>                                      # GBP-Matching (erneut) durchführen
gbp-audit auth <kunde>                                       # OAuth für Modus B einrichten (optional)
gbp-audit run <kunde>                                        # fetch + check + report in einem Durchlauf
gbp-audit run <kunde> --html                                 # zusätzlich HTML-Dashboard erzeugen
gbp-audit diff <kunde> RUN1 RUN2                              # zwei Läufe vergleichen (Datumsordner unter runs/)
```

## Typische Workflows

### Einzelstandort-Kunde

```bash
gbp-audit client add praxis-weber --url https://praxis-weber.de/impressum
# -> findet genau 1 Standort, zeigt ihn zur Bestätigung an, matcht ihn gegen die Places API
gbp-audit run praxis-weber --html
```

Läuft ohne jede Sonderbehandlung durch dieselbe Pipeline wie ein
Filialkunde - der Excel-Report enthält dann eben eine Zeile.

### Filialkette (viele Standorte)

```bash
gbp-audit client add fitcorp --url https://fitcorp-beispiel.de
# -> crawlt die Website (Sitemap, /standorte, /filialen, ...), extrahiert alle
#    Standorte per JSON-LD/Heuristik, zeigt sie zur Bestätigung an
gbp-audit match fitcorp
# -> bei mehrdeutigen Treffern wird interaktiv nachgefragt, welcher Google-
#    Eintrag korrekt ist; Standorte ohne Treffer werden markiert
gbp-audit run fitcorp --html
```

Kriterien wie "einheitliches Namensschema", "Abweichung vom häufigsten
Kategorien-Set" oder "Quartilseinteilung der Performance" werden automatisch
aktiv, sobald ein Kunde mehr als einen Standort hat.

### Monatlicher Re-Audit

```bash
gbp-audit run fitcorp --html
gbp-audit diff fitcorp 2026-06-14 2026-07-14
```

## Report-Inhalte (Excel)

- **Übersicht:** eine Zeile je Standort, Gesamtscore, Gruppen-Scores (Ampel als
  Zellfarbe), Top-Mängel.
- **Ein Blatt je Kriteriengruppe** mit allen Einzelbefunden.
- **Maßnahmenliste:** alle Warnungen/Fehler über alle Standorte, sortiert nach
  Impact (Gewicht der Gruppe × Punkteabzug).
- **Nicht geprüft** (nur Modus A): Ausblick auf die Modus-B-Checks.
- **Performance** (nur Modus B): Rohdaten der Performance-Baseline.

## Prüfkatalog

| Gruppe | Gewicht | Modus |
|---|---|---|
| Existenz & Auffindbarkeit | 10% | A |
| Basisdaten & NAP | 15% | A |
| Kategorien | 10% | A |
| Öffnungszeiten | 10% | A (Feiertage: B) |
| Beschreibung & Attribute | 10% | B |
| Fotos | 10% | A eingeschränkt, voll in B |
| Bewertungen | 15% | A eingeschränkt, voll in B |
| Q&A | 5% | B |
| Leistungen/Produkte | 5% | B |
| Performance-Baseline | 10% | B (Datenerhebung, kein Pass/Fail) |

Im Modus A werden die Gewichte automatisch auf die lauffähigen Gruppen
renormalisiert (Summe bleibt 100%), damit der Score modusübergreifend
vergleichbar bleibt. "Nicht prüfbar" fließt nie in den Score ein, wird aber im
Report gezählt/aufgeführt.

Der Prüfkatalog ist unter `src/checks/` als ein Modul je Kriteriengruppe
implementiert (`src/checks/__init__.py` registriert sie in `GROUPS`) - eine
neue Gruppe hinzuzufügen bedeutet: neues Modul schreiben + dort eintragen.

## Tests

```bash
pytest
```

Die Testsuite deckt Discovery (JSON-LD/Mikrodaten/Heuristik-Extraktion auf
HTML-Fixtures, inkl. einem Fixture mit 55 Standorten), Matching (eindeutig/
mehrdeutig/kein Treffer/Duplikat), den GBP-API-Client (Quota-Fehler, Pagination),
alle zehn Check-Gruppen, Scoring/Renormalisierung sowie die Excel-/HTML-Reports
ab - ohne echte Netzwerkaufrufe (HTTP wird über Fixtures/Fakes/Mock-Transports
ersetzt).

## Bekannte Einschränkungen

- Für Modus B fehlende Endpunkte (Bewertungen/Q&A/Medien) laufen über die
  ältere **My Business API v4**, die Google nicht mehr aktiv weiterentwickelt.
  Sollte Google diese Endpunkte abschalten, müsste `src/api_gbp.py` auf einen
  Ersatz umgestellt werden.
- Die PLZ-zu-Bundesland-Zuordnung (`src/util_geo.py`, für die Feiertagsprüfung)
  ist eine grobe Heuristik über die ersten beiden PLZ-Ziffern, keine exakte
  Zuordnung.
- Die Places API (New) liefert i.d.R. keine Inhaber-Antworten auf einzelne
  Bewertungen - die "Antwortquote (Indiz)" im Modus A ist daher meist "nicht
  prüfbar" und wird erst im Modus B ausgewertet.
