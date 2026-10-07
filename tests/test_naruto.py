"""Tests: Naruto-Erkennung, Seitenanalyse, Frühhinweis vs. Kaufalarm.

Alle Shopseiten in dieser Datei sind KÜNSTLICHE TESTDATEN (kein echter Shop, keine echten Preise).
"""

import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from waechter import modelle as m
from waechter import naruto, push, seite
from waechter.abruf import Antwort
from waechter.dashboard import erzeuge
from waechter.naruto_lauf import (AUSGANGSLAGE, FEHLER, FRUEHHINWEIS, KAUFALARM, KAUFALARM_SPRACHE, UNGEPRUEFT,
                                  Lauf, erledigt, fokus_shops, lade_betrieb, lade_haendler)

NCFG = naruto.lade_naruto()
HEUTE = dt.date(2026, 10, 7)


def produktseite(titel, verfuegbarkeit="OutOfStock", preis="149.99", knopf=True, extra=""):
    ld = {"@context": "https://schema.org", "@type": "Product", "name": titel,
          "offers": {"@type": "Offer", "price": preis, "priceCurrency": "EUR",
                     "availability": f"https://schema.org/{verfuegbarkeit}"}}
    k = "<button>In den Warenkorb</button>" if knopf else ""
    return f'<html><head><script type="application/ld+json">{json.dumps(ld)}</script></head><body><h1>{titel}</h1>{k}{extra}</body></html>'


class Erkennung(unittest.TestCase):
    def p(self, titel, **kw):
        return naruto.pruefe(titel, cfg=NCFG, **kw)

    def test_offizielles_display_englisch(self):
        t = self.p("NARUTO CARD GAME Booster Display (24 Packs) - English - Bandai")
        self.assertTrue(t.passend)
        self.assertEqual((t.sicherheit, t.sprache, t.variante), (m.SICHER, "EN", m.DISPLAY))

    def test_verwechslungen_werden_ausgeschlossen(self):
        for titel in ["NARUTO Mythos TCG - Set 1 Konoha Shido Booster Box (EN)",
                      "Kayou Naruto Card Game Tier 2 Booster Box",
                      "Naruto CCG Path to Hokage Booster Box (English)",
                      "Naruto Collectible Card Game Starter Deck 2006",
                      "Official MOJI Naruto TCG Booster Box Ninja Road of Konoha",
                      "Boruto Naruto Card Game Booster",
                      "Naruto Ninja Card Game 1st Edition Booster Box 24 ENG (Cicaboom)"]:
            t = self.p(titel)
            self.assertFalse(t.passend, titel)

    def test_ohne_card_game_kein_treffer(self):
        self.assertFalse(self.p("Naruto Shippuden Figur Kakashi").passend)
        self.assertFalse(self.p("Naruto Booster Pack Sammelkarten").passend)

    def test_zubehoer_und_einzelkarten_nicht(self):
        self.assertFalse(self.p("NARUTO CARD GAME Official Playmat -Arriving in 2027-").passend)
        self.assertFalse(self.p("NARUTO CARD GAME CP-001 Chakra Card Promo PSA 10").passend)

    def test_sprachen(self):
        self.assertEqual(self.p("NARUTO CARD GAME Booster Box (JPN)").sprache, "JP")
        jp = self.p("NARUTO CARD GAME Booster Box (JPN)")
        self.assertTrue(jp.sprache_offiziell)
        self.assertEqual(self.p("NARUTO CARD GAME Booster Box Asia English").sprache, m.EN_ASIA)
        de = self.p("NARUTO CARD GAME Booster Display Deutsch")
        self.assertEqual((de.sprache, de.sprache_offiziell, de.sicherheit), ("DE", False, m.UNSICHER))
        self.assertEqual(self.p("NARUTO CARD GAME Booster Display").sicherheit, m.UNSICHER)

    def test_naruto_tcg_ohne_bandai_ist_unsicher(self):
        t = self.p("Naruto TCG Booster Box English")
        self.assertTrue(t.passend)
        self.assertEqual(t.sicherheit, m.UNSICHER)
        t2 = self.p("Naruto TCG Booster Box English", hersteller="Bandai")
        self.assertEqual(t2.sicherheit, m.SICHER)


class Seitenanalyse(unittest.TestCase):
    def test_vorbestellbar(self):
        s = seite.analysiere(produktseite("NARUTO CARD GAME Display EN", "PreOrder"), HEUTE)
        self.assertEqual((s.status, s.preis_cent, s.waehrung), (m.PREORDER, 14999, "EUR"))

    def test_ausverkauft(self):
        self.assertEqual(seite.analysiere(produktseite("X", "OutOfStock", knopf=False), HEUTE).status, m.SOLD_OUT)

    def test_coming_soon_ist_nicht_bestellbar(self):
        s = seite.analysiere(produktseite("X", "InStock", knopf=False, extra="<p>Coming soon</p>"), HEUTE)
        self.assertEqual(s.status, m.WAITLIST)

    def test_nur_benachrichtigung(self):
        s = seite.analysiere(produktseite("X", "PreOrder", knopf=False, extra="<button>Benachrichtigen, wenn verfügbar</button>"), HEUTE)
        self.assertEqual(s.status, m.WAITLIST)

    def test_anzahlung_erkannt(self):
        s = seite.analysiere(produktseite("X", "PreOrder", preis="20.00", extra="<p>Anzahlung 20 €, Restbetrag bei Lieferung</p>"), HEUTE)
        self.assertTrue(s.anzahlung)

    def test_mehrere_varianten_unterschiedlich_ist_unklar(self):
        ld = {"@type": "Product", "name": "X", "offers": [
            {"@type": "Offer", "price": "10", "availability": "https://schema.org/InStock"},
            {"@type": "Offer", "price": "100", "availability": "https://schema.org/OutOfStock"}]}
        html = f'<script type="application/ld+json">{json.dumps(ld)}</script><button>In den Warenkorb</button>'
        self.assertEqual(seite.analysiere(html, HEUTE).status, m.UNCLEAR)

    def test_ohne_strukturierte_daten(self):
        self.assertEqual(seite.analysiere("<h1>X</h1><button>Jetzt vorbestellen</button>", HEUTE).status, m.PREORDER)
        self.assertEqual(seite.analysiere("<h1>X</h1><p>Leider ausverkauft</p>", HEUTE).status, m.SOLD_OUT)
        self.assertEqual(seite.analysiere("<h1>X</h1>", HEUTE).status, m.UNCLEAR)

    def test_preisformate(self):
        self.assertEqual(seite._preis_cent("1.299,99"), 129999)
        self.assertEqual(seite._preis_cent("1,299.99"), 129999)
        self.assertEqual(seite._preis_cent("0.00"), None)

    def test_vorbestellstart_wird_erkannt(self):
        s = seite.analysiere(produktseite("X", "OutOfStock", knopf=False, extra="<p>Vorbestellung ab 15.11.2026 möglich</p>"), HEUTE)
        self.assertIn("2026-11-15", s.termine)


class FakeAbrufer:
    def __init__(self, seiten: dict):
        self.seiten = seiten
        self.host_zustand = {}
        self.aufrufe = []

    def setze_host_regeln(self, *a):
        pass

    def host_pausiert(self, host):
        return None

    def hole(self, url):
        self.aufrufe.append(url)
        v = self.seiten.get(url)
        if callable(v):
            v = v()
        if v is None:
            return Antwort(False, 404, fehler="nicht gefunden (Test)", url=url)
        if isinstance(v, int):
            return Antwort(False, v, fehler=f"HTTP {v} (Test)", url=url)
        return Antwort(True, 200, text=v, url=url, url_final=url)


class Kanal(push.Kanal):
    def __init__(self):
        super().__init__("Test", True, self._senden, "Test")
        self.nachrichten = []

    def _senden(self, text):
        self.nachrichten.append(text)
        return True, "ok"


B = "https://shop.test"
KAT = B + "/vorbestellungen"
PROD = B + "/p/naruto-card-game-booster-display-en"


class Szenario:
    def __init__(self, vertrauen="vorgeprueft", titel="NARUTO CARD GAME Booster Display (24) English Bandai", extra_shops=(),
                 pfad="/p/naruto-card-game-booster-display-en"):
        self.prod = B + pfad
        self.tmp = Path(tempfile.mkdtemp())
        shops = {"shop": {"id": "shop", "name": "Testshop", "domain": "shop.test", "basis_url": B, "land": "DE",
                          "plattform": "unbekannt", "status": "geeignet", "vertrauen": vertrauen,
                          "entdeckung": [{"art": "kategorie_vorbestellung", "url": KAT}]}}
        for s in extra_shops:
            shops[s["id"]] = s
        (self.tmp / "db.json").write_text(json.dumps({"haendler": shops}))
        self.kategorie = f'<a href="{pfad}">{titel}</a>'
        self.titel = titel
        self.status = "OutOfStock"
        self.knopf = False
        self.extra = ""
        self.preis = "149.99"
        self.fehler = None
        self.produkt_vorhanden = True
        self.zeit = dt.datetime(2026, 10, 7, 8, 0, tzinfo=dt.timezone.utc)
        self.kanal = Kanal()
        self.ncfg = copy.deepcopy(NCFG)
        self.ncfg["offizielle_quellen"] = []
        self.betrieb = copy.deepcopy(lade_betrieb())

    def seiten(self):
        return {KAT: lambda: self.kategorie if self.produkt_vorhanden else "<p>leer</p>",
                self.prod: lambda: self.fehler or produktseite(self.titel, self.status, self.preis, self.knopf, self.extra)}

    def lauf(self, minuten=10):
        l = Lauf(None, FakeAbrufer(self.seiten()), self.tmp / "daten", db_datei=self.tmp / "db.json", ncfg=self.ncfg,
                 betrieb=self.betrieb, push_kanal=self.kanal, log=lambda s: None, onepiece=False, jetzt=self.zeit)
        l.ausfuehren(nur_faellige=False)  # Zeitsprung: alle Aufgaben ausführen
        l.speichern()
        self.zeit += dt.timedelta(minutes=minuten)
        return [e for e in l.ereignisse if not e["unterdrueckt"]], l

    def bestellbar(self):
        self.status, self.knopf = "PreOrder", True


class Alarme(unittest.TestCase):
    def test_ausgangsbasis_meldet_keinen_restock(self):
        s = Szenario()
        e, _ = s.lauf()
        e2, _ = s.lauf()
        self.assertEqual([x["typ"] for x in e + e2], [])

    def test_ausgangslage_wenn_schon_bestellbar(self):
        s = Szenario()
        s.bestellbar()
        e, _ = s.lauf()
        self.assertEqual([x["typ"] for x in e], [AUSGANGSLAGE])

    def test_kaufalarm_nach_restock_mit_zweitpruefung(self):
        s = Szenario()
        s.lauf()
        s.bestellbar()
        e, l = s.lauf()
        self.assertEqual([x["typ"] for x in e], [KAUFALARM])
        self.assertEqual(e[0]["zweitpruefung"], "bestellbar")
        self.assertTrue(e[0]["gesendet"])
        self.assertTrue(e[0]["spekulativ"])
        self.assertIn("SPEKULATIV", s.kanal.nachrichten[-1])
        self.assertEqual([x["typ"] for x in s.lauf()[0]], [], "keine Wiederholung bei unverändertem Angebot")

    def test_zweitpruefung_verhindert_fehlalarm(self):
        s = Szenario()
        s.lauf()
        aufrufe = {"n": 0}

        def wechselhaft():
            aufrufe["n"] += 1
            return produktseite(s.titel, "PreOrder" if aufrufe["n"] == 1 else "OutOfStock", knopf=aufrufe["n"] == 1)
        s.seiten = lambda: {KAT: s.kategorie, s.prod: wechselhaft}
        e, _ = s.lauf()
        self.assertNotIn(KAUFALARM, [x["typ"] for x in e])

    def test_anzahlung_ist_kein_kaufalarm(self):
        s = Szenario()
        s.lauf()
        s.bestellbar()
        s.extra = "<p>Anzahlung: 20 € jetzt, Restbetrag später</p>"
        e, _ = s.lauf()
        self.assertEqual([x["typ"] for x in e], [FRUEHHINWEIS])
        self.assertIn("Anzahlung", e[0]["text"])

    def test_neue_seite_nicht_bestellbar_ist_fruehhinweis(self):
        s = Szenario()
        s.produkt_vorhanden = False
        s.lauf()  # Ausgangsbasis ohne Produkt
        s.produkt_vorhanden = True
        e, _ = s.lauf()
        self.assertEqual([x["typ"] for x in e], [FRUEHHINWEIS])
        self.assertIn("noch NICHT bestellbar", e[0]["text"])

    def test_neue_seite_sofort_bestellbar_ist_kaufalarm(self):
        s = Szenario()
        s.produkt_vorhanden = False
        s.lauf()
        s.produkt_vorhanden = True
        s.bestellbar()
        self.assertEqual([x["typ"] for x in s.lauf()[0]], [KAUFALARM])

    def test_ungepruefter_shop_nur_hinweis(self):
        s = Szenario(vertrauen="ungeprueft")
        s.lauf()
        s.bestellbar()
        e, _ = s.lauf()
        self.assertEqual([x["typ"] for x in e], [UNGEPRUEFT])

    def test_andere_offizielle_sprache_separat(self):
        s = Szenario(titel="NARUTO CARD GAME Booster Box (JPN) Bandai", pfad="/p/naruto-card-game-booster-box-jpn")
        s.lauf()
        s.bestellbar()
        self.assertEqual([x["typ"] for x in s.lauf()[0]], [KAUFALARM_SPRACHE])

    def test_sprachwiderspruch_titel_url_kein_kaufalarm(self):
        s = Szenario(titel="NARUTO CARD GAME Booster Box (JPN) Bandai", pfad="/p/naruto-card-game-booster-box-en")
        s.lauf()
        s.bestellbar()
        self.assertEqual([x["typ"] for x in s.lauf()[0]], [FRUEHHINWEIS])

    def test_unklare_sprache_kein_kaufalarm(self):
        s = Szenario(titel="NARUTO CARD GAME Booster Display Bandai", pfad="/p/naruto-card-game-booster-display")
        s.lauf()
        s.bestellbar()
        e, _ = s.lauf()
        self.assertEqual([x["typ"] for x in e], [FRUEHHINWEIS])

    def test_abruffehler_nie_ausverkauft_und_fehlermeldung(self):
        s = Szenario()
        s.lauf()
        s.fehler = 503
        typen = []
        for _ in range(3):
            e, l = s.lauf(minuten=30)
            typen += [x["typ"] for x in e]
        ang = next(iter(l.zustand["naruto"]["angebote"].values()))
        self.assertEqual(ang["letzte"]["status"], m.UNCLEAR)
        self.assertEqual(ang["letzter_sicherer_status"], m.SOLD_OUT)
        self.assertEqual(typen, [FEHLER])
        s.fehler = None
        s.bestellbar()
        self.assertEqual([x["typ"] for x in s.lauf()[0]], [KAUFALARM])

    def test_wartezeit_waechst_bei_fehlern(self):
        b = lade_betrieb()
        jetzt = dt.datetime(2026, 10, 7, tzinfo=dt.timezone.utc)
        a = {"intervall": 180, "fehlerserie": 0}
        abstaende = []
        for _ in range(4):
            erledigt(a, False, jetzt, b, "Fehler")
            abstaende.append((dt.datetime.fromisoformat(a["faellig"]) - jetzt).total_seconds())
        self.assertEqual(abstaende, [180, 360, 720, 1440])
        erledigt(a, True, jetzt, b)
        self.assertEqual(a["fehlerserie"], 0)

    def test_fokus_um_vorbestellstart(self):
        b = lade_betrieb()
        z = {"naruto": {"termine": {"x": {"shop": "shop", "zeitpunkt": "2026-11-15"}}}}
        self.assertEqual(fokus_shops(z, NCFG, b, dt.datetime(2026, 11, 15, 9, tzinfo=dt.timezone.utc)), {"shop"})
        self.assertEqual(fokus_shops(z, NCFG, b, dt.datetime(2026, 11, 10, 9, tzinfo=dt.timezone.utc)), set())

    def test_ausgeschlossene_haendler_werden_nie_ueberwacht(self):
        extra = [{"id": "z", "name": "TCG Zenith", "domain": "tcgzenith.com", "basis_url": "https://tcgzenith.com",
                  "status": "geeignet", "entdeckung": [{"art": "shopsuche", "url": "https://tcgzenith.com/?s=naruto"}]},
                 {"id": "d", "name": "Distro", "domain": "tcgdistronline.com", "basis_url": "https://tcgdistronline.com",
                  "status": "geeignet", "entdeckung": [{"art": "shopsuche", "url": "https://tcgdistronline.com/?s=naruto"}]}]
        s = Szenario(extra_shops=extra)
        ids = {h.id for h in lade_haendler(None, s.tmp / "db.json")}
        self.assertEqual(ids, {"shop"})

    def test_pushtext_kennzeichnet_fehlende_angaben_und_test(self):
        e = {"typ": KAUFALARM, "text": "x", "titel": "NARUTO CARD GAME Display", "shop_name": "S", "vertrauen": "vorgeprueft",
             "sprache": "EN", "sprache_offiziell": True, "variante": "DISPLAY", "status": "PREORDER", "preis_cent": 14999,
             "waehrung": "EUR", "versand_cent": None, "gesamt_cent": None, "url": "https://x", "testmodus": True}
        t = push.formatiere(e, NCFG)
        self.assertIn("TEST – SIMULIERTER RESTOCK", t)
        self.assertIn("Versand DE:</b> ❓ fehlt", t)
        self.assertIn("Gesamt:</b> ❓ fehlt", t)
        self.assertIn("Release:</b> ❓", t)
        self.assertIn("Bestelllink", t)

    def test_dashboard_zeigt_betriebszahlen(self):
        s = Szenario()
        s.lauf()
        _, l = s.lauf()
        db = json.loads((s.tmp / "db.json").read_text())
        db["zusammenfassung"] = {"kandidaten": 1, "geeignet": 1}
        text = erzeuge(l.zustand, lade_haendler(None, s.tmp / "db.json"), db, NCFG, l.betrieb, s.zeit)
        self.assertIn("tatsächlich überwacht", text)
        self.assertIn("**1** von 1", text)
        self.assertIn("Aktive Prüfintervalle", text)
        self.assertIn("Pushkanal", text)


if __name__ == "__main__":
    unittest.main()
