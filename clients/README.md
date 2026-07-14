# clients/

Hier legt die App pro Mandant ein eigenes Verzeichnis an:

```
clients/<kunde>/
  config.yaml     # kundenspezifische Overrides der globalen config.yaml
  locations.yaml  # extrahierte/bestätigte Standorte inkl. GBP Place-ID-Zuordnung
  token.json      # OAuth-Token für Modus B (falls eingerichtet)
  runs/YYYY-MM-DD/ # Rohdaten (JSON) je Lauf
  output/         # generierte Excel-/HTML-Reports
```

Diese Verzeichnisse enthalten kundenspezifische NAP-Daten, GBP-Rohdaten und
Reports und werden daher standardmäßig **nicht** in dieses Repository
committet (siehe `.gitignore`). Für produktiven Einsatz je Kunde entweder
lokal belassen oder in einem separaten, privaten Datenspeicher sichern.
