# TESTDATEN

Alles in diesem Ordner ist **Testmaterial**. Es wird nur für automatische Tests und für den Probelauf
`python -m waechter pruefen --testdaten` benutzt. Ein Testdaten-Lauf schreibt nie nach `data/` und sendet nie
an Telegram.

Jede Datei sagt im Feld `_testdaten` (JSON) bzw. im Kommentar (HTML), woher sie stammt:

| Kennzeichnung | Bedeutung |
|---|---|
| `ECHT, gekürzt` | Am 06.10.2026 tatsächlich von der genannten URL abgerufen. Nur lange Beschreibungstexte/Bilder wurden gekürzt. |
| `NACHGEBAUT aus Echtdaten` | Titel, Handle, Preis und Verfügbarkeit stammen aus einem echten Abruf vom 06.10.2026. Das Dateiformat (IDs, Felder) wurde nachgebaut. |
| `KÜNSTLICH` | Frei erfundenes Beispiel, um einen Grenzfall zu testen (z. B. Abruffehler, Preis 0,00, falsche Sprache). |

Die Preise und Bestände sind **nicht aktuell** und dürfen nicht als Kaufgrundlage dienen.
