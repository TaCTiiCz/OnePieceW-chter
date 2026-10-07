# Gespeicherte Daten (werden vom Wächter geschrieben)

| Datei | Inhalt |
|---|---|
| `zustand.json` | Letzter bekannter Stand je Angebot, letzter *sicherer* Status, Wiederholsperre, Host-Pausen |
| `verlauf/JJJJ-MM.jsonl` | Preis- und Bestandsverlauf: eine Zeile je Änderung oder Abruffehler, mit Zeit (UTC) und Quellenlink |
| `ereignisse.jsonl` | Erkannte Restocks, neue Vorbestellungen, Preisrückgänge (auch die nicht per Telegram gemeldeten) |
| `laeufe.jsonl` | Zusammenfassung jedes Prüflaufs |

Bitte nicht von Hand ändern. Zum Neustart (neue Ausgangsbasis) kann `zustand.json` gelöscht werden.
