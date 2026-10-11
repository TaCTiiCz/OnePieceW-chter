"""Tests: saubere Meldungen – nur echte Neuzugänge, Preisgrenzen, Varianten, spekulative Sets (KÜNSTLICHE TESTDATEN)."""

import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from waechter import modelle as m
from waechter.klassifizierung import klassifiziere
from waechter.konfig import lade_konfig
from waechter.lauf import preisbewertung
from waechter.zuordnung import ordne_zu
from tests import test_onepiece_generisch as tg
from tests.test_onepiece_generisch import BASIS, DISPLAY_URL, LISTE, Fake, produktseite

URL_B = BASIS + "/produkt/one-piece-op13-carrying-on-his-will-booster-display-24-packs-english/"
URL_C = BASIS + "/produkt/one-piece-op14-the-azure-seas-seven-booster-display-24-packs-english/"


def liste(*urls):
    namen = {DISPLAY_URL: "One Piece OP15 Booster Display (24 Packs) English",
             URL_B: "One Piece OP13 Carrying on His Will Booster Display (24 Packs) English",
             URL_C: "One Piece OP14 The Azure Sea's Seven Booster Display (24 Packs) English"}
    return "<html>" + "".join(f'<a href="{u}">{namen[u]}</a>' for u in urls) + "</html>"


class NeuGelistet(unittest.TestCase):
    lauf = tg.Lauf.lauf

    def test_nur_echte_neuzugaenge_werden_als_neu_gemeldet(self):
        with tempfile.TemporaryDirectory() as t, mock.patch("waechter.onepiece_generisch.MAX_PRODUKTSEITEN", 1):
            seiten = {LISTE: liste(DISPLAY_URL, URL_B), DISPLAY_URL: produktseite(False),
                      URL_B: produktseite(True), URL_C: produktseite(True)}
            self.lauf(t, Fake(seiten))                       # Lauf 1: Ausgangsbasis, B steht schon in der Liste
            z2 = self.lauf(t, Fake(seiten))                  # Lauf 2: B wird erst jetzt besucht -> NICHT "neu"
            self.assertEqual([e for e in z2["ereignisse"] if e["alarm"]], [], z2["ereignisse"])
            seiten[LISTE] = liste(DISPLAY_URL, URL_B, URL_C)
            z3 = self.lauf(t, Fake(seiten))                  # Lauf 3: C taucht neu in der Liste auf -> "neu"
            neu = [e for e in z3["ereignisse"] if e["alarm"] and e["typ"] == m.NEU_LIEFERBAR]
            self.assertEqual(len(neu), 1, z3["ereignisse"])


def beob(preis, set_code="OP13", shop="neu", waehrung="EUR"):
    return SimpleNamespace(kategorie="display", preis_cent=preis, waehrung=waehrung, ziel_id=f"display-{set_code}",
                           shop_id=shop, set_code=set_code)


def zustand(*preise, set_code="OP13"):
    return {"angebote": {f"s{i}:x:1": {"letzte": {"ziel_id": f"display-{set_code}", "shop_id": f"s{i}", "abruf_ok": True,
                                                  "status": m.SOLD_OUT, "waehrung": "EUR", "preis_cent": p}}
                         for i, p in enumerate(preise)}}


class Preisgrenzen(unittest.TestCase):
    # Markt-Logik ohne Höchstpreis testen; der Höchstpreis hat eigene Tests
    P = dict(lade_konfig().produkte, preisgrenzen={**lade_konfig().produkte["preisgrenzen"], "max_kaufpreis_eur": 0})

    def test_hoechstpreis_250(self):
        p = lade_konfig().produkte
        self.assertEqual(p["preisgrenzen"]["max_kaufpreis_eur"], 250)
        self.assertIsNone(preisbewertung(zustand(11000, 12000, 13000), beob(24900), p, m.RESTOCK)["sperre"])
        self.assertIn("Höchstpreis", preisbewertung(zustand(30000, 32000, 35000), beob(25100), p, m.RESTOCK)["sperre"])
        r = preisbewertung(zustand(), beob(30000), p, m.NEUE_VORBESTELLUNG)
        self.assertIsNone(r["sperre"])
        self.assertIn("💸", r["zusatz"])

    def test_restock_ueber_marktpreis_kein_alarm(self):
        r = preisbewertung(zustand(11000, 12000, 13000), beob(43000), self.P, m.RESTOCK)
        self.assertIn("über dem Marktpreis", r["sperre"])
        self.assertIn("Median", r["zusatz"])

    def test_restock_zum_marktpreis_ok(self):
        self.assertIsNone(preisbewertung(zustand(11000, 12000, 13000), beob(12000), self.P, m.RESTOCK)["sperre"])
        self.assertIn("💰", preisbewertung(zustand(11000, 12000, 13000), beob(9900), self.P, m.RESTOCK)["zusatz"])

    def test_vorbestellung_und_neuheit_immer_melden_aber_kennzeichnen(self):
        for typ in (m.NEUE_VORBESTELLUNG, m.NEU_LIEFERBAR):
            r = preisbewertung(zustand(11000, 12000, 13000), beob(43000), self.P, typ)
            self.assertIsNone(r["sperre"], typ)
            self.assertIn("💸", r["zusatz"])
        self.assertIn("unplausibel", preisbewertung(zustand(), beob(1699), self.P, m.NEUE_VORBESTELLUNG)["sperre"])

    def test_einzelbooster_preis_ist_kein_display(self):
        self.assertIn("unplausibel", preisbewertung(zustand(), beob(1699), self.P)["sperre"])

    def test_ohne_vergleich_standardgrenze(self):
        self.assertIsNone(preisbewertung(zustand(), beob(18000), self.P)["sperre"])
        self.assertIn("Standardgrenze", preisbewertung(zustand(), beob(150000), self.P)["sperre"])

    def test_eigene_grenze_pro_set(self):
        p = dict(self.P, preisgrenzen={**self.P["preisgrenzen"], "OP09": 350})
        self.assertIsNone(preisbewertung(zustand(50000, 52000, 58000, set_code="OP09"), beob(34000, "OP09"), p)["sperre"])
        self.assertIn("Limit für OP09", preisbewertung(zustand(set_code="OP09"), beob(36000, "OP09"), p)["sperre"])


class Erkennung(unittest.TestCase):
    P = lade_konfig().produkte

    def test_booster_variante_eines_displayprodukts_ist_kein_display(self):
        titel = "🟢LIVESTREAM - One Piece Card Game - The Worlds Strongest Warriors OP17 Display/Booster [EN]"
        self.assertEqual(klassifiziere(titel, "Booster").typ, m.BOOSTER_PACK)
        self.assertEqual(klassifiziere(titel, "Display").typ, m.DISPLAY)

    def test_spekulative_sets_ohne_kaufalarm(self):
        for code, erwartet in (("OP19", m.SICHER), ("OP20", m.UNSICHER), ("OP24", m.UNSICHER)):
            titel = f"One Piece Card Game Booster Display {code} (24 Packs) - EN - *VORBESTELLUNG*"
            t, _ = ordne_zu(titel, klassifiziere(titel), self.P)
            self.assertEqual(t.sicherheit, erwartet, code)


if __name__ == "__main__":
    unittest.main()
