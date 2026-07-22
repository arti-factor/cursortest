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

Die CLI und die Webanwendung nutzen unterschiedliche OAuth-Client-Typen, da
die Webanwendung eine Weiterleitungs-URI statt eines lokalen Browser-Popups
braucht:

- **Für die CLI** (`gbp-audit auth <kunde>`): OAuth-Client-ID vom Typ
  **"Desktop-App"**.
- **Für die Webanwendung** (Button "Modus B einrichten"): OAuth-Client-ID vom
  Typ **"Web-Anwendung"** mit der Weiterleitungs-URI
  `http://<host>:<port>/clients/<kunde>/auth/callback` (bei lokalem Testen
  z.B. `http://127.0.0.1:8000/clients/beispiel-gmbh/auth/callback`).

Schritte:

1. In der Google Cloud Console unter **APIs & Dienste -> Zugangsdaten ->
   Anmeldedaten erstellen -> OAuth-Client-ID** den passenden Client-Typ (siehe
   oben) anlegen, JSON herunterladen.
2. Pfad zur JSON-Datei in `.env` als `GOOGLE_OAUTH_CLIENT_SECRET_FILE`
   eintragen.
3. Die Business-Profile-APIs (Account Management, Business Information,
   Performance, My Business v4) haben standardmäßig **Quota = 0**. Zugriff
   muss über das offizielle
   [GBP-API-Antragsformular](https://developers.google.com/my-business/content/prereqs#request-access)
   beantragt werden (Google prüft manuell, das kann einige Tage dauern).
4. Sobald der Zugriff freigeschaltet ist: `gbp-audit auth <kunde>` (CLI) oder
   den Button "Modus B einrichten" auf der Mandanten-Seite (Webanwendung)
   nutzen. Der Token wird unter `clients/<kunde>/token.json` gespeichert. Ab
   dann laufen Audit-Läufe für diesen Mandanten automatisch im Modus B.

Ohne Schritt 3/4 bleibt die App voll nutzbar - sie arbeitet dann dauerhaft im
Modus A.

### 4. Foursquare- und Yelp-API-Keys (optional, für Verzeichnis-Konsistenz)

Zwei der Verzeichnis-Portale (siehe Abschnitt "Verzeichnis-Konsistenz" unten)
werden automatisch per API geprüft:

**Foursquare:**
1. Auf [foursquare.com/developers](https://foursquare.com/developers) registrieren.
2. Ein Projekt anlegen, API-Key kopieren.
3. Key in `.env` als `FOURSQUARE_API_KEY` eintragen.

**Yelp Fusion API:**
1. Auf [yelp.com/developers](https://www.yelp.com/developers) registrieren.
2. Eine App anlegen, den API-Key (Fusion API) kopieren.
3. Key in `.env` als `YELP_API_KEY` eintragen.

Ohne diese Keys bleiben die beiden Prüfungen einfach "nicht prüfbar" - der
Rest der App (inklusive der übrigen Verzeichnis-Prüfungen per Bookmarklet)
funktioniert unverändert.

## Mandantenstruktur

```
clients/<kunde>/
  config.yaml     # kundenspezifische Overrides von config.yaml (Gewichtungen,
                   # Soll-Hauptkategorie, erwartete Attribute, Bewertungs-
                   # Keywords, ...)
  locations.yaml   # extrahierte/bestätigte Standorte inkl. GBP Place-ID
  portale.yaml     # Verzeichnis-Konsistenz-Prüfungen je Standort/Portal (unabhängig vom Audit-Lauf)
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

## Webanwendung

Neben der CLI gibt es eine eigenständige Webanwendung mit HTML-Oberfläche
(FastAPI) - dieselbe Geschäftslogik, aber bedienbar über den Browser statt
das Terminal. Gedacht zum Verlinken/Einbetten aus einer bestehenden
Agenturverwaltung heraus (z.B. als Menüpunkt/Link oder in einem iframe), ganz
ohne eigenes Login.

### Starten

```bash
source .venv/bin/activate
uvicorn src.webapp.main:app --host 0.0.0.0 --port 8000
```

Danach ist die Oberfläche unter `http://<server>:8000/` erreichbar. Für die
lokale Entwicklung mit Autoreload: `uvicorn src.webapp.main:app --reload`.

**In die Agenturverwaltung einbinden:** Da es sich um eine eigenständige
Webanwendung handelt, reicht ein einfacher Link oder ein `<iframe>` auf die
laufende Instanz, z.B.:

```html
<a href="https://gbp-audit.eure-domain.de/" target="_blank">GBP-Audit öffnen</a>
<!-- oder eingebettet: -->
<iframe src="https://gbp-audit.eure-domain.de/" style="width:100%; height:90vh; border:0;"></iframe>
```

Für den produktiven Betrieb hinter einem Reverse-Proxy (nginx/Apache/Caddy)
der Agenturverwaltung reicht ein einfacher Proxy-Pass auf den uvicorn-Prozess
(z.B. Port 8000) - eine gemeinsame Datenbank oder ein gemeinsames Login sind
nicht nötig, da die Webanwendung komplett unabhängig läuft.

### Bedienung

- **Mandanten** (Startseite): Übersicht aller Kunden, "+ Neuer Mandant"
- **Neuer Mandant**: Name + Domain/URL eingeben -> Discovery läuft im
  Hintergrund -> Ergebnis zur Prüfung/Bearbeitung (Standorte korrigieren,
  entfernen, manuell ergänzen) -> Speichern
- **Mandanten-Seite**: Standortliste mit Zuordnungsstatus, Buttons für
  "GBP-Matching starten" und "Audit-Lauf starten" (beides läuft als
  Hintergrund-Job mit Live-Log), Linkliste vergangener Läufe, "Modus B
  einrichten"
- **Mehrdeutige Treffer**: falls das Matching mehrere mögliche
  Google-Profile findet, erscheint eine Auswahlseite mit Kandidaten je
  Standort
- **Report-Ansicht**: eingebettetes HTML-Dashboard je Lauf + Download-Link
  für den Excel-Report
- **Läufe vergleichen**: zwei Läufe per Dropdown wählen, Score-Delta je
  Standort

Hintergrund-Jobs (Discovery/Matching/Audit-Lauf) laufen im Prozessspeicher
des Webservers - bei einem Neustart des Servers gehen nur laufende
Job-Status-Anzeigen verloren, nicht die bereits gespeicherten Standorte/
Reports unter `clients/<kunde>/`.

## Verzeichnis-Konsistenz

Zusätzlich zum Google-Unternehmensprofil prüft die App, ob ein Standort auf
weiteren Branchenverzeichnissen gelistet ist und ob dort Name/Adresse/Telefon
(NAP) mit den Originaldaten übereinstimmen. Erreichbar über den Button
"Verzeichnisse prüfen" auf der Mandanten-Seite.

**Unabhängig vom monatlichen GBP-Audit:** Diese Prüfung läuft nie automatisch
mit, sondern wird pro Standort/Portal manuell ausgelöst, wann immer es
gebraucht wird. Das Ergebnis fließt trotzdem ins Gesamtscoring ein (Gruppe
"Verzeichnis-Konsistenz") - ein Portal, das noch nie geprüft wurde, gilt als
"nicht prüfbar" und wird (wie bei allen anderen Gruppen) automatisch aus der
Score-Berechnung herausgerechnet, bis der erste Check erfolgt ist.

**Zwei automatisch geprüfte Portale** (Foursquare, Yelp Deutschland - siehe
Einrichtung oben): ein Klick auf "Prüfen" ruft die jeweilige offizielle API
auf und vergleicht das Ergebnis automatisch mit den Standort-NAP-Daten.

**Neun Portale ohne öffentliche API** (Bing Places for Business, Apple
Business Connect, Das Örtliche, Gelbe Seiten, Wer liefert was, 11880.com,
Branchenbuch Deutschland, Cylex, meinestadt.de) haben keine Möglichkeit für
eine automatisierte, ToS-konforme Abfrage - hierfür gibt es das
**Bookmarklet**:

1. Auf der Verzeichnisse-Seite den Link "🔖 gbp-audit erfassen" auf die
   Lesezeichenleiste **ziehen** (einmalig, nicht anklicken - ein Bookmarklet
   muss als Lesezeichen gespeichert sein, um auf einer fremden Seite zu
   funktionieren).
2. Auf "Prüfen" bei einem Portal klicken - öffnet die Suchergebnisseite des
   Portals in einem neuen Tab.
3. Dort die passenden NAP-Angaben mit der Maus markieren.
4. Das Lesezeichen anklicken - es erscheint eine schwebende Leiste mit
   "Übernehmen" (aktiv sobald Text markiert ist) und "Kein Eintrag vorhanden".
5. "Übernehmen" klicken - der markierte Text wird automatisch an die App
   übertragen und mit den Original-NAP-Daten abgeglichen (gleiche
   Ähnlichkeitslogik wie beim Google-Matching). Existiert kein Eintrag, direkt
   "Kein Eintrag vorhanden" klicken, ganz ohne zu markieren.

Falls das Übertragen auf einer bestimmten Portal-Seite nicht funktioniert
(manche Seiten blockieren aus Sicherheitsgründen abgehende Anfragen an fremde
Domains) steht auf der Verzeichnisse-Seite je Standort/Portal zusätzlich ein
Textfeld zum manuellen Einfügen bereit - identische Auswertung, nur ohne den
Umweg über die fremde Seite.

**Technischer Hinweis:** Es wird bewusst nicht automatisiert gescraped - ein
Mensch markiert nur, was er ohnehin im Browser sieht (wie beim Kopieren in
ein Dokument). Die App merkt sich dabei jeweils nur *eine* aktive Prüfung
gleichzeitig (kein Login/keine Mehrbenutzer-Sitzungsverwaltung) - bei
paralleler Nutzung durch mehrere Personen am selben Server könnten sich
Prüfungen im ungünstigsten Fall überschneiden; für den vorgesehenen
Einzelfall-nach-Einzelfall-Workflow eines kleinen Teams ist das
unproblematisch.

Die genauen Such-URLs je Portal (`config.yaml`, Abschnitt
`verzeichnis_portale`) sind bestmöglich recherchiert, aber Verzeichnisse
ändern ihre URL-Schemata gelegentlich - bei Bedarf dort anpassen.

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
| Existenz & Auffindbarkeit | 9% | A |
| Basisdaten & NAP | 13,5% | A |
| Kategorien | 9% | A |
| Öffnungszeiten | 9% | A (Feiertage: B) |
| Beschreibung & Attribute | 9% | B |
| Fotos | 9% | A eingeschränkt, voll in B |
| Bewertungen | 13,5% | A eingeschränkt, voll in B |
| Q&A | 4,5% | B |
| Leistungen/Produkte | 4,5% | B |
| Performance-Baseline | 9% | B (Datenerhebung, kein Pass/Fail) |
| Verzeichnis-Konsistenz | 10% | A (Foursquare/Yelp automatisch, Rest per Bookmarklet) |

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
HTML-Fixtures, inkl. einem Fixture mit 55 Standorten, sowie NAP-Extraktion aus
Freitext für die Bookmarklet-Erfassung), Matching (eindeutig/mehrdeutig/kein
Treffer/Duplikat), den GBP-API-Client (Quota-Fehler, Pagination,
OAuth-Web-Flow), die Foursquare-/Yelp-Clients, alle elf Check-Gruppen,
Scoring/Renormalisierung, die Excel-/HTML-Reports sowie die Webanwendung
(Routen/Weiterleitungen/Job-Status/Verzeichnis-Konsistenz-Flow über FastAPIs
TestClient) ab - ohne echte Netzwerkaufrufe (HTTP wird über
Fixtures/Fakes/Mock-Transports ersetzt).

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
- Die Such-URLs der Bookmarklet-Portale (`config.yaml`, `verzeichnis_portale`)
  sind bestmöglich recherchiert, aber nicht live gegen jedes Portal verifiziert
  - bei Bedarf dort anpassen, falls eine URL nicht mehr zur echten
  Suchergebnisseite führt. Yelp Deutschland hat zudem deutlich dünnere
  Datenabdeckung als in den USA.
- Die Verzeichnis-Konsistenz merkt sich nur eine aktive Bookmarklet-Prüfung
  gleichzeitig (kein Login/keine Mehrbenutzer-Sitzungen) - für den
  vorgesehenen Einzelfall-Workflow eines kleinen Teams ausreichend, aber nicht
  für viele gleichzeitige Nutzer gedacht.
