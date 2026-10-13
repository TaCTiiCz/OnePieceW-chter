"""Tests: alle Anniversary-Sets (bekannte + künftige), Preisgrenzen, Display-Erkennung aus der Beschreibung,
Hinweise bei ungeprüften Shops, keine Neu-Flut nach neuer Produktliste. KÜNSTLICHE TESTDATEN."""

import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from waechter import modelle as m
from waechter.klassifizierung import klassifiziere
from waechter.lauf import _sonder_grenze, preisbewertung
from tests.test_zuordnung import PRODUKTE, zuordnen
from tests import test_onepiece_generisch as tg
from tests.test_onepiece_generisch import BASIS, LISTE, Fake


class Erkennung(unittest.TestCase):
    def ziel(self, titel):
        t, grund = zuordnen(titel)
        return (t.ziel_id, t.sicherheit) if t else (None, grund)

    def test_bekannte_sets(self):
        faelle = {
            "One Piece Card Game English Version 1st Anniversary Set": ("1st-anniversary-set-en", m.SICHER),
            "One Piece Card Game English Version 2nd Anniversary Set": ("2nd-anniversary-set-en", m.SICHER),
            "One Piece TCG 3rd Anniversary Set EN Premium Bandai": ("3rd-anniversary-set-en", m.SICHER),
            "PREMIUM BANDAI One Piece Card Game Japanese 1st Anniversary Set": ("1st-anniversary-set-jp", m.SICHER),
            "ONE PIECE CARD GAME Japanese 2nd Anniversary Set (English Version)": ("2nd-anniversary-set-jp", m.SICHER),
            "One Piece Card Game Japanisches 3. Anniversary Set": ("3rd-anniversary-set-jp", m.SICHER),
            "One Piece Card Game 4th Anniversary Set": ("4th-anniversary-set", m.SICHER),
        }
        for titel, erwartet in faelle.items():
            self.assertEqual(self.ziel(titel), erwartet, titel)

    def test_kuenftige_sets_automatisch(self):
        self.assertEqual(self.ziel("One Piece Card Game 5th Anniversary Set English"),
                         ("5th-anniversary-set-en-auto", m.SICHER))
        self.assertEqual(self.ziel("One Piece Card Game Japanese 6th Anniversary Set")[0], "6th-anniversary-set-jp-auto")

    def test_unsicher_und_ausschluesse(self):
        self.assertEqual(self.ziel("One Piece Card Game 2nd Anniversary Set")[1], m.UNSICHER, "Sprache offen")
        self.assertEqual(self.ziel("One Piece Card Game 2nd Anniversary LIMITED COLLECTION (English)")[1], m.UNSICHER)
        self.assertIsNone(self.ziel("One Piece 25th Anniversary Limited Collection Card Set English")[0])
        self.assertIsNone(self.ziel("One Piece Card Game 3rd Anniversary Set Chinese")[0])

    def test_display_mit_anniversary_beiname(self):
        # "4th Anniversary" ist hier nur der Beiname von OP-17 – kein Anniversary-Set
        k = klassifiziere("One Piece OP-17 4th Anniversary", beschreibung="Cada caja contiene 24 sobres, con 6 cartas por sobre.",
                          setnamen=PRODUKTE["displays"]["setnamen"])
        self.assertEqual((k.typ, k.set_code), (m.DISPLAY, "OP17"))
        k2 = klassifiziere("One Piece OP-17 4th Anniversary", setnamen=PRODUKTE["displays"]["setnamen"])
        self.assertEqual(k2.typ, m.TYP_UNBEKANNT, "ohne Beschreibung bleibt der Typ offen")


class Preise(unittest.TestCase):
    def beob(self, ziel, preis):
        return SimpleNamespace(kategorie="sonder", preis_cent=preis, waehrung="EUR", ziel_id=ziel, shop_id="x",
                               set_code=None, ziel_anzeige=ziel)

    def test_grenzen(self):
        self.assertEqual(_sonder_grenze("3rd-anniversary-set-en", PRODUKTE), 250)
        self.assertEqual(_sonder_grenze("5th-anniversary-set-en-auto", PRODUKTE), 250)
        self.assertEqual(_sonder_grenze("pcc-29th", PRODUKTE), 40)

    def test_restock_ueber_grenze_still_vorbestellung_mit_hinweis(self):
        z = {"angebote": {}}
        self.assertIn("Limit", preisbewertung(z, self.beob("2nd-anniversary-set-en", 207395), PRODUKTE, m.RESTOCK)["sperre"])
        self.assertIsNone(preisbewertung(z, self.beob("2nd-anniversary-set-en", 17999), PRODUKTE, m.RESTOCK)["sperre"])
        r = preisbewertung(z, self.beob("3rd-anniversary-set-en", 30000), PRODUKTE, m.NEUE_VORBESTELLUNG)
        self.assertIsNone(r["sperre"])
        self.assertIn("💸", r["zusatz"])


class Migration(unittest.TestCase):
    def lauf(self, tmp, abrufer, produkte):
        from dataclasses import replace
        from pathlib import Path
        from waechter.konfig import lade_konfig
        from waechter.lauf import fuehre_aus
        from waechter.onepiece_haendler import mit_datenbank
        from waechter.speicher import Speicher
        konfig = replace(mit_datenbank(lade_konfig(), tg.db_datei(tmp, "vorgeprueft")), produkte=produkte)
        konfig.shops[:] = [s for s in konfig.shops if s.id == "opwoo"]
        return fuehre_aus(konfig, abrufer, Speicher(Path(tmp) / "z"), telegram_senden=False, log=lambda s: None)

    def szenario(self, version_neu):
        url = BASIS + "/produkt/one-piece-card-game-english-version-3rd-anniversary-set/"
        liste = f'<html><a href="{url}">One Piece Card Game English Version 3rd Anniversary Set</a></html>'
        seite = tg.produktseite(True).replace("One Piece OP15 Booster Display (24 Packs) English",
                                              "One Piece Card Game English Version 3rd Anniversary Set")
        alt = {**PRODUKTE, "anniversary": {**PRODUKTE["anniversary"], "sets": [], "automatisch_kuenftige": False},
               "allgemein": {**PRODUKTE["allgemein"], "produkt_version": 1}}
        neu = {**PRODUKTE, "allgemein": {**PRODUKTE["allgemein"], "produkt_version": 2 if version_neu else 1}}
        with tempfile.TemporaryDirectory() as t:
            seiten = {LISTE: liste, url: seite}
            self.lauf(t, Fake(seiten), alt)                     # altes Produktwissen: Set unbekannt
            self.lauf(t, Fake(seiten), alt)
            z = self.lauf(t, Fake(seiten), neu)                 # neue Liste: Set wird erkannt, ist aber schon lange gelistet
            return [e for e in z["ereignisse"] if e["alarm"]]

    def test_neue_produktliste_meldet_alte_angebote_nicht_als_neu(self):
        self.assertEqual(self.szenario(version_neu=True), [])

    def test_ohne_versionswechsel_waere_es_eine_flut(self):
        self.assertEqual(len(self.szenario(version_neu=False)), 1, "Gegenprobe: ohne Version käme ein Neu-Alarm")


if __name__ == "__main__":
    unittest.main()
