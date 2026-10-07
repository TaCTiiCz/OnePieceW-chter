# Händlerdatenbank und Händlerprüfung

## Wie die Datenbank entsteht

1. **Kandidaten** stehen in [`config/haendler_kandidaten.csv`](../config/haendler_kandidaten.csv). Jede Zeile nennt die
   **Herkunft**: z. B. „Suche One Piece DE 2026-10-07“ (Fundstelle einer Websuche) oder „Vorwissen (unbestätigt)“.
   Suchtreffer dienen nur zur Entdeckung, nie als Nachweis.
2. Die **live Händlerprüfung** (Workflow „Händlerprüfung“, läuft in der GitHub-Cloud) ruft für jeden Kandidaten ab, was
   öffentlich und laut robots.txt erlaubt ist: Startseite, robots.txt, Impressum, Versandseite und – je nach
   Shopsystem – öffentliche Produkt-Schnittstellen (Shopify `/meta.json`, WooCommerce Store-API).
3. Das Ergebnis mit Belegen und Zeitstempel steht in [`data/haendler_db.json`](../data/haendler_db.json).
   Es wird **wöchentlich komplett** und **täglich für neue Kandidaten** erneuert.

## Ergebnis der Live-Prüfung vom 07.10.2026 (gemessen in der GitHub-Cloud)

| | Anzahl |
|---|---|
| Kandidaten | 148 |
| **geeignet** (erreichbar, TCG-Sortiment, Europa, liefert nicht nachweislich NICHT nach DE) | **105** |
| davon **automatisch vorgeprüft** (Impressum mit Register/USt-ID **und** Versand nach DE belegt) | 41 |
| blockieren automatische Abrufe (403/Bot-Schutz) – wird respektiert | 13 |
| eigene Bot-Regeln (Games Island) – nicht automatisch überwacht | 1 |
| nicht erreichbar | 2 |
| ungeeignet (kein TCG-Sortiment erkennbar, liefert nicht nach DE) | 27 |

Die aktuellen Zahlen stehen immer in `data/haendler_db.json` (`zusammenfassung`) und im Dashboard.

## Vertrauensstufen (entscheiden über die Art der Meldung)

| Stufe | Bedeutung | Meldung bei Bestellbarkeit |
|---|---|---|
| ✅ **geprüft** | dokumentiert von Hand geprüft (`config/shops.toml`, `kaufalarm_freigegeben = true`) | **KAUFALARM** |
| ☑️ **vorgeprüft** | automatisch: Impressum mit Handelsregister/USt-ID gefunden **und** Versand nach DE belegt | **KAUFALARM** (mit Hinweis „automatisch vorgeprüft“) |
| ❗ **ungeprüft** | Belege fehlen | nur **UNGEPRÜFTER HINWEIS**, keine Kaufempfehlung |

**Nicht bewertet** werden Seriosität, Zuverlässigkeit, Kundenerfahrungen und Case-Hunting-Risiko – dafür liegen keine
belastbaren Belege vor. Eine Originalversiegelung beweist **nicht**, dass ein Display aus einem unselektierten Case stammt.

## Ausschlüsse

- **TCG Distro / tcgdistronline.com:** dauerhaft ausgeschlossen (fest im Code).
- **TCG Zenith:** gesperrt **bis zu einer dokumentierten Vertrauensprüfung** (`config/shops.toml`,
  `[ausschluss] bis_vertrauenspruefung`). Erst nach dieser Prüfung den Eintrag dort entfernen.
- **Games Island:** legt eigene Regeln für automatische Abrufe fest (u. a. keine Verfügbarkeitsabfragen über die
  Hauptseite, Scalper nicht erwünscht) – wird respektiert und nicht automatisch überwacht.
- Shops, die mit **403 oder Bot-Schutz** antworten, werden nicht umgangen, sondern als Abdeckungslücke geführt.

## Manuell dokumentiert geprüfte Händler (One Piece, Stand 06.10.2026)

| Händler | Land | Impressum | Versand DE | Freigabe |
|---|---|---|---|---|
| cardcosmos | DE | cardcosmos GmbH, Fahrdorf, HRB16880 AG Flensburg, USt-ID DE366668128 ([Quelle](https://cardcosmos.de/policies/legal-notice)) | 4,99 € ([Quelle](https://cardcosmos.de/policies/shipping-policy)) | ✅ |
| Prime Protector | AT | Wenig GmbH, Ilztal, FN 550752f LG Graz, UID ATU76568607 ([Quelle](https://primeprotector.at/policies/legal-notice)) | DPD 5,90 €, ab 200 € frei ([Quelle](https://primeprotector.at/policies/shipping-policy)) | ✅ |
| Universe TCG | ES | Einzelunternehmer, NIF 77123245J ([Quelle](https://www.universetcg.com/policies/legal-notice)) | nicht angegeben | ⛔ (Versandkosten fehlen) |
| Otakura | IT | nicht gefunden | 12,50 € ([Quelle](https://otakura.com/en/policies/shipping-policy)) | ⛔ (Impressum fehlt) |

## Einen Händler hinzufügen oder freigeben

- **Neuer Kandidat:** Zeile in `config/haendler_kandidaten.csv` ergänzen (Domain; Name; Land; Herkunft) und speichern
  → die Händlerprüfung startet automatisch.
- **Freigeben (KAUFALARM statt Hinweis):** Impressum und Versandseite im Browser prüfen, dann einen Block in
  `config/shops.toml` anlegen (Vorlage: cardcosmos) mit `kaufalarm_freigegeben = true` und den belegten Versandkosten.
