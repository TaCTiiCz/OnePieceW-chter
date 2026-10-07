# One-Piece-TCG-Wächter

Überwacht **englische** One-Piece-Kartenspiel-Produkte bei europäischen Händlern mit Lieferung nach Deutschland.
Er erkennt **Restocks**, **neue Vorbestellungen** und **Preisrückgänge**.
**Er kauft niemals etwas.** Er liest nur öffentliche Produktseiten.

Beobachtet werden:

- Original versiegelte **Booster Displays** (24 Packs) aller OP-Sets ab OP01. **Priorität:** OP13, OP15, OP09, OP18, OP16, OP11
- Englische **Sleeved Booster** von OP09 und OP13
- **Premium Card Collection -29th Anniversary Edition-** (Englisch)
- **English Version 2nd Anniversary Set**. Zur Bezeichnung „2nd Anniversary LIMITED COLLECTION“ siehe
  [docs/produktidentitaet.md](docs/produktidentitaet.md).

Den aktuellen Bericht findest du in **[reports/latest.md](reports/latest.md)**.

---

## Inhalt

1. [So funktioniert es](#1-so-funktioniert-es)
2. [Einmalig: Code in den Hauptzweig übernehmen](#2-einmalig-code-in-den-hauptzweig-übernehmen)
3. [Ersten Prüflauf starten](#3-ersten-prüflauf-starten)
4. [Bericht lesen](#4-bericht-lesen)
5. [Telegram einrichten (optional)](#5-telegram-einrichten-optional)
6. [Regelmäßig ausführen: Kosten und Grenzen](#6-regelmäßig-ausführen-kosten-und-grenzen)
7. [Händler oder Produkte ändern](#7-händler-oder-produkte-ändern)
8. [Was der Wächter tut, um Fehlalarme zu vermeiden](#8-was-der-wächter-tut-um-fehlalarme-zu-vermeiden)
9. [Probleme lösen](#9-probleme-lösen)

---

## 1. So funktioniert es

```
GitHub Actions (Cloud, kein eigener PC nötig)
   │  startet  python -m waechter pruefen
   ▼
1. Produktlisten der Händler lesen         → nur zum Finden von Kandidaten
2. Jede passende Produktseite einzeln abrufen → Status, Preis, Varianten
3. Sprache / Produkttyp / Set / Versiegelung / Vollständigkeit erkennen
4. Mit dem gespeicherten Stand vergleichen → Restock? Vorbestellung? Preis gefallen?
5. Speichern: data/ (Verlauf)  +  reports/latest.md (Bericht)
6. Optional: Telegram-Nachricht bei freigegebenen Händlern
```

- **Keine Server, keine Datenbank:** Der Verlauf liegt als Textdateien im Repository (`data/`).
- **Erweiterbar:** Weitere Shopify-Händler sind nur ein Eintrag in `config/shops.toml`. Andere Shop-Systeme
  bekommen später einen eigenen Adapter in `waechter/haendler/`.
- **Aktuelle Händler (4):** cardcosmos (DE), Prime Protector (AT), Universe TCG (ES), Otakura (IT).
  Die dokumentierte Prüfung steht in [docs/haendlerpruefung.md](docs/haendlerpruefung.md).
  **Kaufalarme sind nur für cardcosmos und Prime Protector freigegeben.**
- **Ausgeschlossen:** TCG Distro / tcgdistronline.com und TCG Zenith. Das ist im Code verankert und lässt sich
  nicht versehentlich einschalten.

## 2. Einmalig: Code in den Hauptzweig übernehmen

Der Code liegt zunächst im Zweig `claude/serene-fermat-a01vy2`. GitHub zeigt den Startknopf eines Workflows erst
an, wenn der Workflow im Hauptzweig `main` liegt.

1. Öffne <https://github.com/TaCTiiCz/OnePieceW-chter>.
2. Oben erscheint ein gelber Hinweis **„claude/serene-fermat-a01vy2 had recent pushes“**. Klicke auf
   **„Compare & pull request“**.
   *Falls der Hinweis fehlt:* Klicke auf den Reiter **„Pull requests“**, dann auf **„New pull request“**. Wähle
   bei **„compare:“** den Zweig `claude/serene-fermat-a01vy2`.
3. Klicke auf **„Create pull request“**.
4. Warte, bis unten der Test-Haken grün ist (ca. 1 Minute).
5. Klicke auf **„Merge pull request“** und danach auf **„Confirm merge“**.

## 3. Ersten Prüflauf starten

1. Klicke im Repository oben auf den Reiter **„Actions“**.
   *Falls GitHub fragt, ob Workflows aktiviert werden sollen:* Klicke auf
   **„I understand my workflows, go ahead and enable them“**.
2. Klicke links auf **„Wächter – Prüflauf“**.
3. Rechts erscheint der Knopf **„Run workflow“**. Klicke darauf.
4. Lass **Branch: main** und **aktion: pruefen** stehen und klicke auf den grünen Knopf **„Run workflow“**.
5. Nach einigen Sekunden erscheint ein neuer Eintrag. Ein Lauf dauert etwa 3–10 Minuten, weil der Wächter
   absichtlich langsam abfragt.
6. **Starte nach dem ersten Lauf einen zweiten.** Der erste erfolgreiche Lauf speichert nur die
   **Ausgangsbasis** und meldet absichtlich nichts. Veränderungen erkennt der Wächter erst ab dem zweiten Lauf.

> Hinweis: Der Code wurde in einer Umgebung ohne Zugriff auf die Händler-Websites entwickelt. Die Logik ist mit
> Tests und echten, gespeicherten Händlerdaten geprüft. **Ein echter Live-Lauf hat aber noch nicht
> stattgefunden.** Der erste Lauf in GitHub Actions ist der erste echte Live-Test. Sperrt ein Händler den Zugriff
> aus der GitHub-Cloud, steht das im Bericht unter „Abruffehler“. Der Wächter umgeht solche Sperren nicht.

## 4. Bericht lesen

- **Schnell:** Klicke in **Actions** auf den Lauf. Der Bericht steht direkt auf der Seite unter **„Summary“**.
- **Dauerhaft:** Reiter **„Code“**, dann `reports` und `latest.md`.

| Symbol | Bedeutung |
|---|---|
| 🟢 IN STOCK | laut Produktseite bestellbar und lieferbar |
| 🟡 PREORDER | Vorbestellung möglich |
| 🟠 WAITLIST | nicht bestellbar, Warteliste/Benachrichtigung |
| 🔴 SOLD OUT | ausverkauft |
| ⚪ UNCLEAR | unklar, z. B. Abruffehler oder widersprüchliche Angaben. **Löst nie einen Alarm aus.** |
| ❓ | unbekannt, z. B. Versandkosten. **Wird nie als 0 € gezählt.** |
| ⛔ | Händler nicht für Kaufalarme freigegeben |
| ⚠️ | Währung nicht auf der Produktseite bestätigt |

Spalten: Preis, **Versand nach DE**, **Gesamtpreis** (nur wenn beides bekannt ist), Sprache, Produkttyp,
versiegelt (JA/NEIN/UNBEKANNT), 24 Packs (JA/NEIN/UNBEKANNT) und der direkte Link zur Produktseite.

Der vollständige Verlauf mit Zeitstempel und Quellenlink liegt in `data/verlauf/`.

## 5. Telegram einrichten (optional)

Telegram ist **vorbereitet, aber ausgeschaltet**. Zugangsdaten gehören **nur in GitHub-Secrets**, nie in Dateien.

**Kosten:** Telegram und Telegram-Bots sind kostenlos.

### 5.1 Bot anlegen (im Browser über Telegram Web)

1. Öffne <https://web.telegram.org> und melde dich an.
2. Suche oben nach **@BotFather** (blauer Haken) und öffne den Chat.
3. Schreibe `/newbot` und sende es.
4. Gib einen Namen ein, z. B. `Mein One Piece Wächter`.
5. Gib einen Benutzernamen ein, der auf `bot` endet, z. B. `meinopwaechter_bot`.
6. BotFather antwortet mit einem **Token**, etwa `123456789:AA…`. **Kopiere ihn und gib ihn niemandem.**

### 5.2 Chat-ID herausfinden

1. Suche in Telegram Web nach deinem neuen Bot, öffne den Chat und klicke auf **„Start“**. Schreibe danach
   irgendeine Nachricht, z. B. `hallo`.
2. Öffne in einem neuen Browser-Tab diese Adresse und ersetze `DEIN_TOKEN` durch deinen Token:
   `https://api.telegram.org/botDEIN_TOKEN/getUpdates`
3. Suche im angezeigten Text nach `"chat":{"id":`. Die Zahl dahinter ist deine **Chat-ID**,
   z. B. `987654321`.

### 5.3 In GitHub hinterlegen

1. Repository → Reiter **„Settings“** → links **„Secrets and variables“** → **„Actions“**.
2. Reiter **„Secrets“** → **„New repository secret“**:
   - Name: `TELEGRAM_BOT_TOKEN`, Secret: dein Token → **„Add secret“**
3. Noch einmal **„New repository secret“**:
   - Name: `TELEGRAM_CHAT_ID`, Secret: deine Chat-ID → **„Add secret“**
4. Reiter **„Variables“** → **„New repository variable“**:
   - Name: `TELEGRAM_AKTIV`, Value: `1` → **„Add variable“**

### 5.4 Testen

**Actions** → **„Wächter – Prüflauf“** → **„Run workflow“** → bei **aktion** `telegram-test` wählen →
**„Run workflow“**. Du solltest eine Testnachricht bekommen.

**Ausschalten:** Ändere die Variable `TELEGRAM_AKTIV` auf `0`.

Gemeldet wird nur bei **freigegebenen Händlern** und **sicheren Treffern**: Restock, neu gelistet und lieferbar,
neue Vorbestellung und Preisrückgang (mindestens 3 % **und** 2 €). Dieselbe Meldung kommt höchstens einmal in
24 Stunden.

## 6. Regelmäßig ausführen: Kosten und Grenzen

Die regelmäßige Ausführung ist **vorbereitet, aber ausgeschaltet**. Bitte lies diesen Abschnitt, bevor du sie
einschaltest.

### Kosten (Stand der GitHub-Regeln: bitte selbst unter Settings → Billing prüfen)

- Dein Repository ist **privat**. Mit dem kostenlosen GitHub-Konto sind dafür **2.000 Actions-Minuten pro Monat**
  enthalten.
- Jeder Lauf wird auf **volle Minuten aufgerundet**. Ein Prüflauf mit Tests dauert voraussichtlich **3–10 Minuten**.
  Der genaue Wert zeigt sich beim ersten Live-Lauf.
- Beispielrechnung bei etwa 6 Minuten pro Lauf:

  | Intervall | Läufe/Monat | Minuten/Monat | im Freikontingent? |
  |---|---|---|---|
  | alle 6 Stunden | ~120 | ~720 | ✅ |
  | **alle 4 Stunden (Vorschlag)** | ~180 | ~1.080 | ✅ |
  | alle 2 Stunden | ~360 | ~2.160 | ❌ knapp darüber |
  | jede Stunde | ~720 | ~4.320 | ❌ |

- Ohne hinterlegte Zahlungsmethode entstehen nach GitHubs Regeln keine Kosten. Läufe werden dann bis zum
  Monatsende blockiert. Den Verbrauch siehst du unter **Profilbild → Settings → Billing and plans**.
- Alternative: Ein **öffentliches** Repository hat bei GitHub keine Minutenbegrenzung. Dann wären aber Code,
  Verlauf und Bericht für alle sichtbar. Die Secrets blieben trotzdem geheim.

### Grenzen der Zeitplanung

- Zeiten im Zeitplan sind **UTC** (deutsche Winterzeit = UTC+1, Sommerzeit = UTC+2).
- Der kürzeste mögliche Abstand ist 5 Minuten. Das wäre hier aber zu teuer und gegenüber den Händlern unhöflich.
- Geplante Läufe können sich **verzögern oder bei hoher Last ausfallen**, besonders zur vollen Stunde. Deshalb ist
  Minute 23 eingestellt. Ein Restock, der nur wenige Minuten dauert, kann verpasst werden.
- Geplante Läufe laufen nur auf dem Hauptzweig `main`.

### Einschalten (im Browser)

1. Reiter **„Code“** → `.github` → `workflows` → `waechter.yml`.
2. Klicke rechts oben auf das **Stift-Symbol** („Edit this file“).
3. Suche diese zwei Zeilen:
   ```yaml
     # schedule:
     #   - cron: "23 */4 * * *"
   ```
   Entferne jeweils nur `# ` am Zeilenanfang, sodass dort steht:
   ```yaml
     schedule:
       - cron: "23 */4 * * *"
   ```
   Die Einrückung (Leerzeichen vorne) muss bleiben.
4. Klicke auf **„Commit changes…“** und dann auf **„Commit changes“**.

**Ausschalten:** **Actions** → **„Wächter – Prüflauf“** → rechts oben **„…“** → **„Disable workflow“**.

## 7. Händler oder Produkte ändern

Alle Einstellungen stehen in zwei gut kommentierten Dateien. Du kannst sie direkt im Browser über das
Stift-Symbol bearbeiten:

- `config/shops.toml`: Händler, Versandkosten nach DE, Freigabe für Kaufalarme, Abfrage-Abstände
- `config/products.toml`: Prioritäts-Sets, Set-Namen, Sonderprodukte, Schwellen für Preisrückgang

**Einen weiteren Shopify-Händler hinzufügen:** Kopiere einen bestehenden `[shops.…]`-Block und passe ihn an. Trage
Versandkosten nur ein, wenn sie auf der Versandseite des Händlers belegt sind, sonst `status = "unbekannt"`. Lass
`kaufalarm_freigegeben = false`, bis du die Prüfung in `docs/haendlerpruefung.md` dokumentiert hast. Nach dem
Speichern prüft der Test-Workflow automatisch, ob die Datei gültig ist.

## 8. Was der Wächter tut, um Fehlalarme zu vermeiden

- **Suchtreffer zählen nicht:** Jede Produktseite wird einzeln geprüft.
- **Ausgangsbasis:** Der erste erfolgreiche Lauf je Händler meldet nichts.
- **Abruffehler** (Zeitüberschreitung, 503, Sperre) ergeben den Status UNCLEAR. Sie lösen nie einen Restock aus,
  und der letzte sichere Status bleibt erhalten.
- **Typische Shop-Fallen:** Vorbestellungen werden von Shopify als „verfügbar“ gemeldet. Artikel ohne
  Bestandsführung sind immer „verfügbar“. Preis 0,00 € ist ein Platzhalter. Beschreibungen sind manchmal
  veraltet. All diese Fälle werden erkannt.
- **Sprachverwechslung:** Die Sprache wird nur aus Titel, Variante, URL und Tags gelesen. JP, CN, KR, Asia-English
  usw. werden ausgeschlossen. Bei fehlender oder widersprüchlicher Angabe gibt es keinen Kaufalarm.
- **Produkttyp:** Case, Booster Pack, Einzelkarte, Zubehör, Starter Deck und Double Pack werden **nicht** als Display
  gezählt. Geöffnete oder unvollständige Ware wird ausgeschlossen.
- **Unbekannte Versandkosten** werden nie als 0 € gerechnet. Der Gesamtpreis bleibt dann „unbekannt“.
- **Händlerlimits:** ehrliche Kennung (kein Browser-Tarnname), robots.txt, mindestens 4 Sekunden Abstand pro
  Händler und eine Obergrenze pro Lauf. Bei 429/5xx wartet der Wächter länger. Bei 403 oder Captcha hört er sofort
  auf und pausiert den Händler für 6 Stunden.
- Über 100 automatische Tests prüfen das bei jeder Änderung. Siehe Ordner `tests/`. Alle Testdaten sind dort
  gekennzeichnet.

## 9. Probleme lösen

| Problem | Lösung |
|---|---|
| Kein „Run workflow“-Knopf | Der Code ist noch nicht in `main` (Abschnitt 2). |
| Schritt „Verlauf und Bericht speichern“ schlägt fehl (403) | **Settings → Actions → General → Workflow permissions →** „Read and write permissions“ wählen → **Save**. |
| Händler zeigt „Zugriff verweigert“ oder „Bot-Schutz“ | Der Händler blockiert automatische Abrufe aus der GitHub-Cloud. Das wird respektiert. Händler in `config/shops.toml` entfernen oder so lassen. |
| „Telegram eingeschaltet, aber Secret … fehlt“ | Secret-Namen genau wie in Abschnitt 5.3 schreiben. |
| Neue Ausgangsbasis gewünscht | Datei `data/zustand.json` löschen (Datei öffnen → „…“ → „Delete file“). |

### Für Fortgeschrittene (optional, nicht nötig)

```bash
python -m waechter pruefen --testdaten   # Probelauf mit Testdaten, ohne Internet
python -m unittest discover -s tests -t . # alle Tests
python -m waechter konfig                 # Konfiguration prüfen
```

Benötigt nur Python 3.11 oder neuer, keine Zusatzpakete.
