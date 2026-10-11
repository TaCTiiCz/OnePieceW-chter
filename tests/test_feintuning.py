"""Tests: gestaffelte Prüfplanung, Schnellmodus-Auswahl, Shopify-Suchvorschläge, Hintergrundlauf."""

import datetime as dt
import unittest
from types import SimpleNamespace

from waechter import modelle as m
from waechter.abruf import Antwort
from waechter.haendler import shopify
from waechter.lauf import _beobachtenswert, plane_shops

JETZT = dt.datetime(2026, 10, 11, 12, 0, tzinfo=dt.timezone.utc)


def shop(id, alarm):
    return SimpleNamespace(id=id, kaufalarm_freigegeben=alarm)


def vor(minuten):
    return (JETZT - dt.timedelta(minutes=minuten)).isoformat()


class Planung(unittest.TestCase):
    def test_neue_shops_werden_voll_geprueft_alarmfaehige_zuerst(self):
        plan = plane_shops([shop("a", False), shop("b", True)], {"shops": {}}, JETZT, {})
        self.assertEqual([(s.id, mo) for s, mo in plan], [("b", "voll"), ("a", "voll")])

    def test_alarmshop_schnell_wenn_volle_suche_frisch(self):
        z = {"shops": {"b": {"letzte_vollsuche": vor(5), "zuletzt_geprueft": vor(3)}}}
        self.assertEqual([(s.id, mo) for s, mo in plane_shops([shop("b", True)], z, JETZT, {})], [("b", "schnell")])

    def test_alarmshop_voll_nach_30_minuten(self):
        z = {"shops": {"b": {"letzte_vollsuche": vor(31), "zuletzt_geprueft": vor(3)}}}
        self.assertEqual(plane_shops([shop("b", True)], z, JETZT, {})[0][1], "voll")

    def test_shop_ohne_alarmrecht_wird_uebersprungen_bis_fällig(self):
        z = {"shops": {"a": {"letzte_vollsuche": vor(60), "zuletzt_geprueft": vor(60)}}}
        self.assertEqual(plane_shops([shop("a", False)], z, JETZT, {}), [])
        z["shops"]["a"]["letzte_vollsuche"] = vor(121)
        self.assertEqual(plane_shops([shop("a", False)], z, JETZT, {})[0][1], "voll")


class Schnellmodus(unittest.TestCase):
    def test_ausverkauftes_immer_lieferbares_nur_alle_10_minuten(self):
        self.assertTrue(_beobachtenswert({"letzte": {"status": m.SOLD_OUT}, "zuletzt_geprueft": vor(1)}, JETZT))
        self.assertFalse(_beobachtenswert({"letzte": {"status": m.IN_STOCK}, "zuletzt_geprueft": vor(2)}, JETZT))
        self.assertTrue(_beobachtenswert({"letzte": {"status": m.IN_STOCK}, "zuletzt_geprueft": vor(11)}, JETZT))


class Suche(unittest.TestCase):
    def test_suche_vorschlaege_sammelt_handles_und_ignoriert_fehler(self):
        class A:
            def __init__(self): self.n = 0
            def hole(self, url):
                self.n += 1
                if self.n == 1:
                    return Antwort(True, 200, '{"resources":{"results":{"products":[{"handle":"op15-display"}]}}}')
                return Antwort(False, 500, "", "Fehler")
        erg = shopify.suche_vorschlaege(SimpleNamespace(basis_url="https://x.example"), A())
        self.assertEqual([p["handle"] for p in erg], ["op15-display"])


if __name__ == "__main__":
    unittest.main()
