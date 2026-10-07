# Dokumentierte Händlerprüfung

Stand: **06.10.2026**. Geprüft wurden nur öffentlich sichtbare Angaben auf den Shop-Seiten
(Impressum, Versandbedingungen, Sortiment, Format der Produktdaten). Abgerufen wurde über einen
Web-Abrufdienst, weil die Entwicklungsumgebung selbst keinen Zugriff auf die Shops hatte.

**Nicht bewertet** wurden: Seriosität, Zuverlässigkeit, Kundenerfahrungen und das Risiko von Case-Hunting
(Herausnehmen wertvoller Packs vor dem Verkauf). Dafür lagen keine belastbaren Belege vor. Eine
Originalversiegelung beweist **nicht**, dass ein Display aus einem unselektierten Case stammt.

## Kriterien für die Freigabe von Kaufalarmen

Ein Händler wird nur freigegeben (`kaufalarm_freigegeben = true` in `config/shops.toml`), wenn

1. ein Impressum mit Firmenname, Anschrift und Registernummer/USt-ID gefunden wurde,
2. die Lieferung nach Deutschland auf der Versandseite belegt ist,
3. die Versandkosten nach Deutschland auf der Versandseite belegt sind,
4. der Shop nicht auf der Ausschlussliste steht (TCG Distro / tcgdistronline.com, TCG Zenith),
5. die Produktdaten maschinenlesbar und ohne Umgehung von Schutzmaßnahmen abrufbar sind.

Nicht freigegebene Händler werden trotzdem beobachtet und erscheinen im Bericht (mit ⛔), lösen aber keine
Telegram-Kaufalarme aus.

## Ergebnis

| Händler | Land | Impressum | Lieferung DE | Versandkosten DE | Engl. OP-Displays im Sortiment | Freigabe |
|---|---|---|---|---|---|---|
| cardcosmos | DE | ✅ cardcosmos GmbH, Fahrdorf, HRB16880 AG Flensburg, USt-ID DE366668128 | ✅ | ✅ 4,99 € pro Bestellung | ✅ (OP09, OP10, OP11, OP13, OP15, OP18, OP19, EB02 gelistet; am Prüftag alle ausverkauft) | ✅ |
| Prime Protector | AT | ✅ Wenig GmbH, Ilztal, FN 550752f LG Graz, UID ATU76568607 | ✅ | ✅ DPD 5,90 €, ab 200 € frei | ⚠️ am Prüftag keine englischen OP-Displays gefunden (nur Zubehör/Sondersets) | ✅ |
| Universe TCG | ES | ✅ Einzelunternehmer, NIF 77123245J, Mollet del Vallès | ✅ (EU-Versand) | ❌ nicht angegeben | ✅ (OP15, OP16, OP17, EB05, EB06; auch ganze Cases) | ⛔ |
| Otakura | IT | ❌ nicht gefunden | ✅ (EU-Versand) | ✅ 12,50 €; 500–999,98 € → 24,90 €; ab 999,99 € frei | ✅ (OP15 ENG, am Prüftag ausverkauft) | ⛔ |

### Quellen

- cardcosmos: [Impressum](https://cardcosmos.de/policies/legal-notice), [Versand](https://cardcosmos.de/policies/shipping-policy)
- Prime Protector: [Impressum](https://primeprotector.at/policies/legal-notice), [Versand](https://primeprotector.at/policies/shipping-policy)
- Universe TCG: [Legal notice](https://www.universetcg.com/policies/legal-notice), [Shipping](https://www.universetcg.com/policies/shipping-policy)
- Otakura: [Shipping](https://otakura.com/en/policies/shipping-policy), [Legal notice (ohne Firmenangaben)](https://otakura.com/en/policies/legal-notice)

### Beobachtungen bei der Prüfung (wichtig für die Zuverlässigkeit)

- **cardcosmos**: Die Shop-Suche nach „one piece display english“ lieferte fast nur **japanische** Displays.
  Suchtreffer sind deshalb kein Nachweis – der Wächter prüft jede Produktseite und die Sprache einzeln.
  Ein englisches OP19-Display stand mit **Preis 0,00 €** im Katalog (Platzhalter). Der Wächter behandelt das als
  „Preis unbekannt“.
- **Universe TCG**: Das OP15-Display war als „verfügbar“ markiert, die Beschreibung sagte aber „Status: PRE-ORDER“
  bei einem Erscheinungsdatum vom 3. April 2026. Der Wächter meldet solche Widersprüche als **UNCLEAR**.
- **Otakura**: Shopify-Suchergebnisse zeigten Vorbestellungen ebenfalls als „available“. Vorbestellungen
  werden über Tags (z. B. „preordine“), Titel und Verkaufspläne erkannt.

## Nicht aufgenommene Kandidaten

| Händler | Grund |
|---|---|
| TCG Distro / tcgdistronline.com, TCG Zenith | auf ausdrücklichen Wunsch ausgeschlossen (im Code fest verankert) |
| Games Island (games-island.eu) | Der Shop legt für automatische Abrufe eigene Regeln fest (u. a. max. 5 Anfragen pro 5 Minuten über eine eigene Schnittstelle; Scalper nicht erwünscht; Preise sollen von Bots nicht ausgegeben werden). Ein Preiswächter würde diesen Regeln widersprechen – daher nicht aufgenommen. |
| Pokitrio | Versandkosten konnten nicht maschinell belegt werden; vorerst nicht aufgenommen. |
| Cardmarket | Marktplatz mit vielen Einzelverkäufern statt eines Händlers; nicht im Umfang dieser ersten Version. |

## Einen Händler selbst freigeben

1. Impressum und Versandseite des Händlers im Browser öffnen und die Angaben oben ergänzen.
2. In `config/shops.toml` beim Händler `kaufalarm_freigegeben = true` setzen.
3. Datum und Quelle bei `[shops.<name>.pruefung]` eintragen.
