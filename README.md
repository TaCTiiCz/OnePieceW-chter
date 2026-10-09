# TCG-Wächter: NARUTO CARD GAME (Priorität 1) und One Piece (Priorität 2)

Der Wächter soll dir die **erste seriöse Vorbestellmöglichkeit für das NARUTO CARD GAME von Bandai** früh genug melden,
damit du selbst kaufen kannst. Daneben überwacht er weiterhin englische One-Piece-Displays.
**Er kauft niemals automatisch.**

- **Produkt:** NARUTO CARD GAME, BANDAI CO., LTD. (Marke BANDAI CARD GAMES), weltweit im Sommer 2027. Englisch
  (Region „en“, gilt für Deutschland) hat Vorrang. Japanisch, traditionelles Chinesisch und Englisch-Asien werden
  getrennt gemeldet. Belege und Abgrenzung (Mythos TCG, Kayou, altes CCG usw.) stehen in
  [docs/naruto_produktidentitaet.md](docs/naruto_produktidentitaet.md).
- **Händler:** Die Datenbank enthält 148 Kandidaten. **105 davon sind live geprüft und geeignet** (Stand 07.10.2026),
  siehe [docs/haendlerpruefung.md](docs/haendlerpruefung.md).
- **Dashboard (Betriebsnachweis):** Datei `dashboard.md` im Zweig `waechter-daten`:
  <https://github.com/TaCTiiCz/OnePieceW-chter/blob/waechter-daten/dashboard.md>

---

## Inhalt

1. [Meldungsarten](#1-meldungsarten)
2. [So funktioniert es](#2-so-funktioniert-es)
3. [Einrichtung im Browser](#3-einrichtung-im-browser)
4. [Dauerbetrieb: Kosten und Grenzen](#4-dauerbetrieb-kosten-und-grenzen)
5. [Dashboard lesen](#5-dashboard-lesen)
6. [Händler und Produkte ändern](#6-händler-und-produkte-ändern)
7. [Schutz vor Fehlalarmen](#7-schutz-vor-fehlalarmen)
8. [One Piece](#8-one-piece)
9. [Probleme lösen](#9-probleme-lösen)
10. [Für Fortgeschrittene](#10-für-fortgeschrittene)

---

## 1. Meldungsarten

| Meldung | Wann | Bestellen möglich? |
|---|---|---|
| 🚨 **KAUFALARM** | Die passende Variante (Englisch, versiegeltes Spielprodukt) ist **erstmals oder erneut wirklich bestellbar**. Vorher wird die Produktseite **erneut abgerufen** und Bestellbarkeit, Sprache und Preis werden geprüft. Nur bei geprüften oder vorgeprüften Händlern. | **Ja** |
| 🔔 **KAUFALARM (andere Sprache)** | wie oben, aber Japanisch, traditionelles Chinesisch oder Englisch-Asien | Ja |
| 🟡 **FRÜHHINWEIS** | Neue passende Produktseite, angekündigter Vorbestellstart, neue offizielle Meldung – oder bestellbar, aber nicht bestätigt (Anzahlung ohne Gesamtpreis, Sprache unklar). Die Meldung sagt ausdrücklich, dass noch **nicht** bestellt werden kann. | **Nein / unklar** |
| ⚠️ **UNGEPRÜFTER HINWEIS** | bestellbar, aber bei einem Shop ohne Vertrauensprüfung | keine Empfehlung |
| ⛔ **FEHLER** | Eine wichtige Seite ließ sich 3-mal nicht abrufen. Status bleibt **unbekannt**, **nicht** „ausverkauft“. | – |
| 📋 **AUSGANGSLAGE** | Einmalig beim ersten Lauf je Shop: bereits bestellbare Angebote (nicht neu) | Ja |

Jede Meldung enthält: Produkt, Shop (mit Vertrauensstufe), Sprache, Variante, Preis, Versand und Gesamt nach
Deutschland, Release, Prüfzeit und einen direkten Link. Fehlendes steht sichtbar als **„❓ fehlt“** in der Meldung.
Solange Bandai keine Produkte angekündigt hat, steht in jedem Kaufalarm **„SPEKULATIV“**. Es gibt **keine
Preisgrenze**. Angebote deutlich über dem Median vergleichbarer Angebote werden mit „💰 Teuer“ markiert.
Dasselbe unveränderte Angebot wird nicht mehrfach gemeldet.

## 2. So funktioniert es

```
Jeder Lauf (z. B. alle 5 Minuten in GitHub Actions oder alle 1–3 Minuten auf einem eigenen Server):
  1. Bekannte Naruto-Produktseiten prüfen               (Ziel: alle 3 Min., Fokus: 1 Min.)
  2. Offizielle Naruto-Website auf Neuigkeiten prüfen   (30 Min.)
  3. Neuheiten-/Vorbestellkategorien, Shopsuche, Feeds  (15 Min.)
  4. weitere Kategorien, Shopify-Gesamtkatalog          (3 Std.), Sitemaps (täglich)
  5. One Piece                                          (stündlich, niedrigere Priorität)
  -> nur was fällig ist; pro Shop höflich nacheinander, Shops parallel; danach Ende
Täglich: neue Händler suchen (optional) und neue Kandidaten live prüfen. Wöchentlich: alle Händler neu prüfen.
```

Zustand, Verlauf, gesendete Alarme und Dashboard liegen dauerhaft im Zweig **`waechter-daten`**. Die
Händlerdatenbank liegt in `data/haendler_db.json`.

## 3. Einrichtung im Browser

### 3.1 Code in den Hauptzweig übernehmen (einmalig)

1. Öffne <https://github.com/TaCTiiCz/OnePieceW-chter/pull/new/claude/serene-fermat-a01vy2>.
2. Klicke auf **„Create pull request“**.
3. Warte, bis unten die Prüfungen grün sind (ca. 2 Minuten).
4. Klicke auf **„Merge pull request“** und dann auf **„Confirm merge“**.

### 3.2 Telegram einrichten (Pushkanal)

**Kosten:** keine.

1. Öffne <https://web.telegram.org>, melde dich an und suche **@BotFather** (blauer Haken).
2. Sende `/newbot`, gib einen Namen ein (z. B. `Mein TCG Wächter`) und dann einen Benutzernamen, der auf `bot` endet.
3. Kopiere den **Token**, den BotFather schickt (z. B. `123456789:AA…`). **Gib ihn niemandem.**
4. Öffne deinen neuen Bot, klicke auf **„Start“** und schreibe `hallo`.
5. Öffne in einem neuen Tab `https://api.telegram.org/botDEIN_TOKEN/getUpdates` (Token einsetzen) und suche
   `"chat":{"id":`. Die Zahl dahinter ist deine **Chat-ID**.
6. In GitHub: **Settings → Secrets and variables → Actions**
   - Reiter **Secrets** → **New repository secret**: `TELEGRAM_BOT_TOKEN` = Token → **Add secret**
   - **New repository secret**: `TELEGRAM_CHAT_ID` = Chat-ID → **Add secret**
   - Reiter **Variables** → **New repository variable**: `TELEGRAM_AKTIV` = `1` → **Add variable**
7. **Test mit simuliertem Restock:** **Actions → „Wächter“ → „Run workflow“ → aktion
   `simulation-mit-echtem-telegram` → „Run workflow“.** Du bekommst eine Meldung mit
   **„🧪 TEST – SIMULIERTER RESTOCK – KEIN ECHTES ANGEBOT“**. Die gemessene Verzögerung steht danach im Dashboard.

### 3.3 Dauerbetrieb einschalten (läuft auch bei geschlossenem Browser)

Zuerst Abschnitt 4 lesen und eine Variante wählen. Danach:

1. **Code → `.github/workflows/waechter.yml` → Stift-Symbol** („Edit this file“).
2. Entferne bei diesen zwei Zeilen jeweils nur `# ` am Anfang und trage das gewählte Intervall ein:
   ```yaml
     schedule:
       - cron: "*/5 * * * *"
   ```
3. **„Commit changes…“ → „Commit changes“.**
4. Prüfen: Unter **Actions → „Wächter“** erscheint nach einigen Minuten ein Lauf mit dem Auslöser „schedule“.

**Ausschalten:** **Actions → „Wächter“ → „…“ (oben rechts) → „Disable workflow“.**

### 3.4 Tägliche Händlersuche (optional)

Damit täglich automatisch **neue** Händler gefunden werden, braucht der Wächter einen Zugang zu einer offiziellen
Such-Schnittstelle. Das Auslesen normaler Suchmaschinen-Ergebnisseiten ist nicht erlaubt.

1. Bei <https://brave.com/search/api/> ein Konto anlegen und einen API-Schlüssel erstellen. Preise und
   Freikontingent stehen beim Anbieter, bitte dort prüfen.
2. In GitHub: **Settings → Secrets and variables → Actions → New repository secret**:
   `BRAVE_SEARCH_API_KEY` = Schlüssel.

Ohne Schlüssel prüft der Wächter weiterhin täglich neue Kandidaten, die du in `config/haendler_kandidaten.csv`
einträgst, und wöchentlich alle Händler.

## 4. Dauerbetrieb: Kosten und Grenzen

Dein Repository ist **privat**. GitHub enthält dafür **2.000 Actions-Minuten pro Monat**, jeder Lauf wird auf volle
Minuten aufgerundet. Ein Wächter-Lauf dauert erfahrungsgemäß 1–3 Minuten (Werte im Dashboard).

| Variante | Prüfabstand | Kosten | Zuverlässigkeit |
|---|---|---|---|
| **A: Repository öffentlich machen** + Zeitplan `*/5` | 5 Min. (GitHub verzögert geplante Läufe oft um einige Minuten, bei hoher Last fallen einzelne aus) | **kostenlos** (öffentliche Repositorys haben unbegrenzte Standard-Minuten) | mittel |
| **B: privat bleiben** + Zeitplan `7 * * * *` | stündlich | kostenlos im Freikontingent (~720–1.500 Min./Monat) | mittel, zu langsam für schnelle Vorbestellungen |
| **C: eigener kleiner Server** (z. B. Cloud-VM) mit `python -m waechter dauerlauf` | **1–3 Min.** | ca. 4–6 €/Monat bei üblichen Anbietern (bitte beim Anbieter prüfen) | hoch |

Hinweise:
- **Öffentlich** heißt: Code, Händlerliste, Verlauf und Dashboard sind für alle sichtbar. Telegram-Token und Chat-ID
  bleiben als Secrets geheim. Umstellen: **Settings → General → ganz unten „Change repository visibility“**.
- Mit Variante A **im privaten** Repository (ohne Umstellung) wäre das Freikontingent nach etwa 4–7 Tagen
  verbraucht. Ohne hinterlegte Zahlungsmethode werden Läufe dann bis Monatsende blockiert, mit Zahlungsmethode
  entstehen Kosten. Den Verbrauch siehst du unter **Profilbild → Settings → Billing and plans**.
- GitHub-Zeitpläne laufen in **UTC** und nur im Hauptzweig `main`.
- Die Händlerprüfung (täglich/wöchentlich, je ca. 5–10 Min.) kommt hinzu.

## 5. Dashboard lesen

<https://github.com/TaCTiiCz/OnePieceW-chter/blob/waechter-daten/dashboard.md>. Das Dashboard erscheint auch nach
jedem Lauf direkt unter **Actions → Lauf → Summary**.

- **Betrieb in Zahlen:** Wie viele Shops **tatsächlich** überwacht werden (mindestens 1 erfolgreicher Abruf in
  24 Stunden), wie viele Naruto-Produktseiten bekannt und geprüft sind, Fehler und Pushkanal, dazu der letzte Push
  und der letzte Simulationstest mit gemessener Verzögerung.
- **Naruto-Angebote:** Status, Shop, Vertrauen, Sprache, Variante, Preis, Versand, Gesamt, Release, Link.
- **Händler:** letzter erfolgreicher Abruf je Shop, Fehler, Zeitpunkt der Ausgangsbasis.
- **Aktive Prüfintervalle** und **Abdeckungslücken** (blockierte Shops, fehlende Versandkosten, ungeprüfte Shops).

## 6. Händler und Produkte ändern

- **Neuer Händler:** Zeile in `config/haendler_kandidaten.csv` ergänzen (`domain;Name;Land;Herkunft`). Nach dem
  Speichern wird er automatisch live geprüft.
- **Händler freigeben (KAUFALARM statt Hinweis):** siehe [docs/haendlerpruefung.md](docs/haendlerpruefung.md).
- **Bekannter Vorbestellstart:** in `config/naruto.toml` unter `[[termine]]` eintragen. Vorbestellstarts auf
  Shopseiten werden auch automatisch erkannt. Rund um den Termin prüft der Wächter häufiger (Fokus).
- **Intervalle und Grenzen:** `config/betrieb.toml`.
- **Sobald Bandai Produkte ankündigt:** in `config/naruto.toml` `produkte_offiziell_angekuendigt = true` setzen. Dann
  entfällt der Hinweis „SPEKULATIV“.

## 7. Schutz vor Fehlalarmen

- **Suchtreffer zählen nie:** Jede Produktseite wird einzeln abgerufen. Vor jedem Kaufalarm wird sie **ein zweites
  Mal** abgerufen und geprüft.
- **Nicht bestellbar** sind: Warteliste, „Coming soon“, „Benachrichtigen“, Anzahlung ohne klaren Gesamtpreis,
  fehlender Preis, widersprüchliche Angaben.
- **Abruffehler** ergeben „unbekannt“, **nie „ausverkauft“**, und lösen keinen Alarm aus. Wiederholungen erfolgen mit
  wachsendem Abstand (Intervall ×1, ×2, ×4 …).
- **Erster Lauf je Shop = Ausgangsbasis:** Es werden keine angeblichen Restocks gemeldet.
- **Höflichkeit:** ehrliche Kennung, robots.txt (24 Std. zwischengespeichert), Abstand pro Shop, Obergrenze pro Lauf.
  Bei 403, Captcha oder Bot-Schutz hört der Wächter sofort auf, umgeht nichts und pausiert den Shop.
- **TCG Distro / tcgdistronline.com** ist dauerhaft ausgeschlossen, **TCG Zenith** bis zu einer Vertrauensprüfung.
- **Über 140 automatische Tests** und eine **End-to-End-Simulation** laufen bei jeder Änderung. Testdaten sind gekennzeichnet.

## 8. One Piece

Die One-Piece-Überwachung läuft im selben Lauf, **alle 15 Minuten** (`onepiece` in `config/betrieb.toml`). Sie meldet
**Restock** (wieder bestellbar) und **neue Vorbestellungen** für englische Displays **OP01–OP18**, Sleeved Booster und
die Sonderprodukte aus `config/products.toml`.

- **Händler:** die 4 handverlesenen Shops aus `config/shops.toml` plus alle geprüften Shopify-Händler aus der
  Händlerdatenbank (derzeit rund 50). Händler mit Plattform außer Shopify werden noch nicht abgedeckt.
- **Kaufalarm per Telegram** gibt es nur für freigegebene und „vorgeprüfte“ Händler. Alle anderen werden beobachtet und
  stehen im Bericht, lösen aber keinen Alarm aus. Versandkosten bleiben „unbekannt“, wenn sie nicht belegt sind.
- **Zeitbudget:** Ein Lauf prüft höchstens ca. 2,5 Minuten (`onepiece_zeitbudget_sekunden`). Der am längsten ungeprüfte
  Shop kommt zuerst dran, der Rest im nächsten Lauf. Mit dem GitHub-Zeitplan wird so jeder Shop meist alle 15–30 Minuten
  geprüft; schneller geht es nur mit einem eigenen Server.
- **Grenze:** Große Shops werden nur bis zu den ersten ca. 1.000 Produkten gelesen. Ein Display, das dahinter steht,
  kann übersehen werden.
- **Bericht:** `laufzeit/onepiece_bericht.md` im Zweig `waechter-daten`. Im Dojo erscheint der Alarm am One-Piece-Tisch
  (der Seemann springt auf, der Rahmen blinkt).

## 9. Probleme lösen

| Problem | Lösung |
|---|---|
| Kein „Run workflow“-Knopf | Code ist noch nicht in `main` (3.1). |
| Speichern schlägt fehl (403) | **Settings → Actions → General → Workflow permissions → „Read and write permissions“ → Save**. |
| Keine Telegram-Nachricht | Secrets/Variable genau wie in 3.2 benennen; Simulation mit echtem Telegram starten; Dashboard zeigt den Fehler. |
| Shop „blockiert“ | Der Shop lehnt automatische Abrufe ab. Das wird respektiert. |
| Zeitplan läuft nicht | GitHub pausiert geplante Workflows in öffentlichen Repos nach 60 Tagen ohne Aktivität: **Actions → „Wächter“ → „Enable workflow“**. |

## 10. Für Fortgeschrittene

```bash
python -m waechter lauf                    # ein Lauf (fällige Aufgaben)
python -m waechter dauerlauf               # Dauerbetrieb auf eigenem Server (prüft je nach Fälligkeit, ca. alle 20–60 s)
python -m waechter simulation              # simulierter Restock bis zur Test-Pushmeldung, misst die Verzögerung
python -m waechter haendler-pruefen        # Händlerdatenbank live prüfen
python -m waechter haendler-suchen         # neue Händler suchen (BRAVE_SEARCH_API_KEY nötig)
python -m waechter pruefen --testdaten     # One-Piece-Probelauf mit Testdaten (ohne Internet)
python -m unittest discover -s tests -t .  # alle Tests
```

Es wird nur Python 3.11 oder neuer gebraucht, keine Zusatzpakete. Auf einem eigenen Server läuft der Dauerbetrieb
z. B. als systemd-Dienst mit `python -m waechter dauerlauf`. Die Telegram-Zugangsdaten kommen dort als
Umgebungsvariablen hinzu, niemals in Dateien im Repository.

## 5. Pixel-Dojo (Live-Ansicht im Browser)

Ein kleines Pixel-Dojo zeigt, was der Wächter gerade tut: Der Ninja-Wächter geht zu dem Pult der Prüfgruppe, die im
letzten Lauf dran war (Produkte, Offiziell, Neuheiten, Kategorien, Sitemaps, One Piece). Bei einem Kaufalarm hebt er die
Arme, der Gong wackelt und ein Falke fliegt los. Ist ein Pult kaputt, steigt Rauch auf. Läuft seit über 30 Minuten kein
Wächter-Lauf, „schläft“ er – das ist die ehrliche Warnung, dass der Dauerbetrieb nicht läuft.

- Die Seite liegt in `dojo/index.html`, die Daten kommen aus `status.json` (erzeugt von `waechter/dojo.py` bei jedem Lauf).
- `status.json` enthält nur Statuswerte (Stationen, Zeiten, Meldungstexte) – nie Token, Chat-ID oder Zugangsdaten.
- Veröffentlicht wird nur `index.html` + `status.json` über GitHub Pages, nicht der gesamte Zustand.
- **Einmalig einschalten:** Settings → Pages → Source: **„GitHub Actions“**. Danach Actions → „Wächter“ → „Run workflow“.
  Die Adresse steht anschließend im Lauf unter „dojo-veroeffentlichen“ (`https://<name>.github.io/<repo>/`).
- Ohne `status.json` zeigt die Seite einen **Demo-Modus** (oben als „DEMO-MODUS“ gekennzeichnet).
- Hinweis: Die Aktion `simulation` läuft in einer getrennten Testumgebung und löst im Dojo keinen Alarm aus. Der Alarm erscheint nur bei einem echten Restock (Kaufalarm der letzten 3 Stunden).
