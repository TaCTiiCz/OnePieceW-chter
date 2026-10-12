"""Tests: Naruto-Vorbestellschiene – Kassen-Link, Preisstufen, Erinnerungen, Fokus, Suchanteil.

Alle Shopseiten sind KÜNSTLICHE TESTDATEN.
"""

import datetime as dt
import json
import unittest
import urllib.parse

from waechter import befehle, push, seite, suche, telegram
from waechter import modelle as m
from waechter.naruto_lauf import (ERINNERUNG, KAUFALARM, Haendler, NBeob, fokus_shops, intervall_fuer, lade_betrieb,
                                  preis_stufe, pruefe_produktseite)

from tests.test_naruto import NCFG, FakeAbrufer, Szenario


def beob(preis_cent, variante=m.DISPLAY, waehrung="EUR"):
    return NBeob(angebot_id="a", shop="s", shop_name="S", url="u", titel="t", zeit="", abruf_ok=True,
                 preis_cent=preis_cent, variante=variante, waehrung=waehrung)


class Seite(unittest.TestCase):
    def test_storno_wird_erkannt(self):
        self.assertIn("cannot be cancelled", seite.storno_hinweis("Please note: pre-orders cannot be cancelled after 24h."))
        self.assertIsNotNone(seite.storno_hinweis("Vorbestellungen sind nicht stornierbar."))
        self.assertIsNone(seite.storno_hinweis("Kostenlose Stornierung bis zum Versand."))

    def test_woocommerce_kassenlink(self):
        html = '<body class="woocommerce"><form><button name="add-to-cart" value="4711">Vorbestellen</button></form></body>'
        self.assertEqual(seite.warenkorb_link(html, "https://shop.test/p/naruto"),
                         "https://shop.test/checkout/?add-to-cart=4711")
        self.assertIsNone(seite.warenkorb_link("<button>Kaufen</button>", "https://shop.test/p"))

    def test_shopify_kassenlink_und_storno(self):
        js = {"title": "NARUTO CARD GAME Booster Display English Bandai", "vendor": "Bandai", "tags": [],
              "description": "<p>Pre-order. No cancellations possible.</p>",
              "variants": [{"id": 999, "title": "Default Title", "available": False, "price": 12999}]}
        h = Haendler(id="s", name="S", domain="shop.test", basis_url="https://shop.test", land="DE",
                     plattform="shopify", vertrauen="vorgeprueft")
        ab = FakeAbrufer({"https://shop.test/products/naruto-display.js": json.dumps(js)})
        b = pruefe_produktseite(h, "https://shop.test/products/naruto-display", ab, NCFG, dt.date(2026, 10, 12))[0]
        self.assertEqual(b.warenkorb_url, "https://shop.test/cart/999:1")
        self.assertIn("No cancellations", b.storno)


class Preisstufen(unittest.TestCase):
    def test_stufen(self):
        self.assertEqual(preis_stufe(beob(11999), NCFG)[0], "fair")
        self.assertEqual(preis_stufe(beob(19999), NCFG)[0], "ok")
        self.assertEqual(preis_stufe(beob(35000), NCFG)[0], "ueber")
        self.assertEqual(preis_stufe(beob(35000, waehrung="USD"), NCFG)[0], None)
        self.assertEqual(preis_stufe(beob(500, variante=m.BOOSTER_PACK), NCFG)[0], "fair")

    def test_formatierung(self):
        e = {"typ": KAUFALARM, "text": "x", "titel": "t", "url": "https://shop.test/p",
             "warenkorb_url": "https://shop.test/cart/1:1", "preisstufe": "fair", "preisstufe_text": "fairer Preis",
             "storno": "pre-orders cannot be cancelled"}
        t = push.formatiere(e, NCFG)
        self.assertTrue(t.startswith("🔥"))
        self.assertIn("DIREKT ZUR KASSE", t)
        self.assertIn("Stornierung evtl. ausgeschlossen", t)
        self.assertIn("/gekauft", t)

    def test_telegram_leise(self):
        gesendet = {}

        def transport(url, daten):
            gesendet.update(urllib.parse.parse_qs(daten.decode()))
            return 200, '{"ok": true}'
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "x", "TELEGRAM_CHAT_ID": "1"}):
            telegram.sende("hi", transport, leise=True)
        self.assertEqual(gesendet["disable_notification"], ["true"])


class LeiserKanal(push.Kanal):
    def __init__(self):
        super().__init__("Test", True, self._senden, "Test")
        self.nachrichten = []

    def _senden(self, text, leise=False):
        self.nachrichten.append((text, leise))
        return True, "ok"


class Alarmablauf(unittest.TestCase):
    def szenario(self, preis="149.99"):
        s = Szenario()
        s.kanal = LeiserKanal()
        s.preis = preis
        s.ncfg["vorbestellung"] = {**s.ncfg["vorbestellung"], "erinnerung_minuten": 0, "erinnerungen_max": 2}
        s.lauf()
        s.bestellbar()
        return s

    def test_fairer_preis_laut_mit_erinnerungen(self):
        s = self.szenario()
        e, l = s.lauf()
        self.assertEqual([x["typ"] for x in e], [KAUFALARM])
        self.assertEqual(e[0]["preisstufe"], "fair")
        self.assertFalse(s.kanal.nachrichten[-1][1], "fairer Preis kommt mit Ton")
        self.assertIn(e[0]["angebot"], l.zustand["naruto"]["offene_alarme"])
        e2, _ = s.lauf()
        self.assertEqual([x["typ"] for x in e2], [ERINNERUNG])
        e3, l3 = s.lauf()
        self.assertEqual([x["typ"] for x in e3], [ERINNERUNG])
        self.assertEqual(l3.zustand["naruto"]["offene_alarme"], {}, "nach max. Erinnerungen ist Schluss")
        self.assertEqual([x["typ"] for x in s.lauf()[0]], [])

    def test_gekauft_stoppt_erinnerungen(self):
        s = self.szenario()
        _, l = s.lauf()
        antwort = befehle.gekauft_text(l.zustand)
        self.assertIn("gestoppt", antwort)
        l.speichern()
        self.assertEqual([x["typ"] for x in s.lauf()[0]], [])

    def test_ueber_grenze_leise_ohne_erinnerung(self):
        s = self.szenario(preis="350.00")
        e, l = s.lauf()
        self.assertEqual([x["typ"] for x in e], [KAUFALARM])
        self.assertTrue(s.kanal.nachrichten[-1][1], "über der Grenze: ohne Ton")
        self.assertIn("über deiner Grenze", s.kanal.nachrichten[-1][0])
        self.assertEqual(l.zustand["naruto"].get("offene_alarme", {}), {})


class Fokus(unittest.TestCase):
    def test_naruto_wege_schneller(self):
        b = lade_betrieb()
        self.assertEqual(intervall_fuer("kategorie_naruto", b), 300)
        self.assertEqual(intervall_fuer("shopsuche", b), 300)
        self.assertEqual(intervall_fuer("shopify_neueste", b), 900)
        self.assertEqual(intervall_fuer("shopify_neueste", b, fokus=True), 180)
        self.assertEqual(intervall_fuer("produkt", b), 60)

    def test_jump_festa_und_auto_fokus(self):
        b = lade_betrieb()
        z = {"naruto": {"termine": {}}}
        self.assertEqual(fokus_shops(z, NCFG, b, dt.datetime(2026, 12, 19, 12, tzinfo=dt.timezone.utc)), {"*"})
        self.assertEqual(fokus_shops(z, NCFG, b, dt.datetime(2026, 12, 10, 12, tzinfo=dt.timezone.utc)), set())
        z["naruto"]["termine"]["offiziell|x"] = {"shop": "*", "zeitpunkt": "2026-11-01T10:00:00+00:00", "stunden_nachher": 48}
        self.assertEqual(fokus_shops(z, NCFG, b, dt.datetime(2026, 11, 2, 20, tzinfo=dt.timezone.utc)), {"*"})
        self.assertEqual(fokus_shops(z, NCFG, b, dt.datetime(2026, 11, 3, 11, tzinfo=dt.timezone.utc)), set())


class Suchanteil(unittest.TestCase):
    def test_haelfte_naruto(self):
        cfg = {"budget": {"pro_woche": 100, "pro_lauf": 10, "naruto_anteil": 0.5},
               "anfragen": [{"q": f"Naruto Card Game {i}", "land": "DE"} for i in range(4)] +
                           [{"q": f"One Piece {i}", "land": "DE"} for i in range(20)]}
        gewaehlt, _ = suche.plane_anfragen(cfg, {}, dt.date(2026, 10, 12))
        self.assertEqual(len(gewaehlt), 10)
        self.assertEqual(sum("Naruto" in a["q"] for a in gewaehlt), 4, "nur 4 Naruto-Anfragen vorhanden")
        cfg["anfragen"] = [{"q": f"Naruto Card Game {i}", "land": "DE"} for i in range(20)] + cfg["anfragen"][4:]
        gewaehlt, _ = suche.plane_anfragen(cfg, {}, dt.date(2026, 10, 12))
        self.assertEqual(sum("Naruto" in a["q"] for a in gewaehlt), 5)


if __name__ == "__main__":
    unittest.main()
