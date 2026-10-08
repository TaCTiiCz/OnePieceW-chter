"""Tests: Bestandsstatus richtig unterscheiden (IN STOCK, PREORDER, WAITLIST, SOLD OUT, UNCLEAR)."""

import datetime as dt
import json
import unittest
from pathlib import Path

from waechter import modelle as m
from waechter.status import bestimme_status, finde_daten

HEUTE = dt.date(2026, 10, 6)
FIX = Path(__file__).parent / "fixtures" / "shopify"


def status(**kw):
    basis = dict(verfuegbar=True, bestand_verfolgt=True, titel="One Piece OP13 Booster Display EN", variante="",
                 tags=[], beschreibung="", heute=HEUTE)
    basis.update(kw)
    return bestimme_status(**basis)[0]


class Status(unittest.TestCase):
    def test_lieferbar(self):
        self.assertEqual(status(), m.IN_STOCK)

    def test_ausverkauft(self):
        self.assertEqual(status(verfuegbar=False), m.SOLD_OUT)

    def test_warteliste(self):
        self.assertEqual(status(verfuegbar=False, tags=["Warteliste"]), m.WAITLIST)

    def test_vorbestellung_aus_tag_titel_oder_verkaufsplan(self):
        self.assertEqual(status(tags=["Pre-Order"]), m.PREORDER)
        self.assertEqual(status(tags=["preordine"]), m.PREORDER)  # echter Otakura-Tag
        self.assertEqual(status(titel="[Vorbestellung] One Piece OP18 Display EN"), m.PREORDER)
        self.assertEqual(status(verkaufsplaene=["Pre-order deposit"]), m.PREORDER)
        self.assertEqual(status(schema_verfuegbarkeit="http://schema.org/PreOrder"), m.PREORDER)

    def test_erscheinungsdatum_in_zukunft_ist_vorbestellung(self):
        self.assertEqual(status(beschreibung="Erscheinungstermin: 20.11.2026"), m.PREORDER)

    def test_bestand_nicht_gefuehrt_ist_unklar(self):
        # Shopify meldet dann immer "verfügbar" – darf kein Restock werden
        self.assertEqual(status(bestand_verfolgt=False), m.UNCLEAR)

    def test_verfuegbarkeit_fehlt(self):
        self.assertEqual(status(verfuegbar=None), m.UNCLEAR)

    def test_widerspruch_mit_sichtbarer_seite(self):
        self.assertEqual(status(schema_verfuegbarkeit="http://schema.org/OutOfStock"), m.UNCLEAR)
        self.assertEqual(status(verfuegbar=False, schema_verfuegbarkeit="https://schema.org/InStock"), m.UNCLEAR)

    def test_echter_fall_veraltete_vorbestellung_universe(self):
        """Echtdaten 06.10.2026: 'available: true', Beschreibung 'Status: PRE-ORDER', Release 3. April 2026."""
        js = json.loads((FIX / "universetcg" / "op15-box-en.js.json").read_text(encoding="utf-8"))
        v = js["variants"][0]
        s, gruende = bestimme_status(verfuegbar=v["available"], bestand_verfolgt=True, titel=js["title"], variante="",
                                     tags=js["tags"], beschreibung=js["description"], heute=HEUTE)
        self.assertEqual(s, m.UNCLEAR)
        self.assertIn("Vergangenheit", gruende[0])

    def test_echter_fall_otakura_ausverkauft(self):
        js = json.loads((FIX / "otakura" / "op15-box-eng.js.json").read_text(encoding="utf-8"))
        v = js["variants"][0]
        s, _ = bestimme_status(verfuegbar=v["available"], bestand_verfolgt=True, titel=js["title"], variante="",
                               tags=js["tags"], beschreibung=js["description"], heute=HEUTE)
        self.assertEqual(s, m.SOLD_OUT)


class Datum(unittest.TestCase):
    def test_formate(self):
        self.assertIn(dt.date(2026, 4, 3), finde_daten("Release Date: April 3, 2026"))
        self.assertIn(dt.date(2026, 4, 3), finde_daten("disponibile dal 3 aprile 2026"))
        self.assertIn(dt.date(2026, 11, 20), finde_daten("Erscheint am 20.11.2026"))
        self.assertIn(dt.date(2026, 11, 20), finde_daten("release 2026-11-20"))
        self.assertIn(dt.date(2026, 11, 20), finde_daten("20 de noviembre de 2026"))


if __name__ == "__main__":
    unittest.main()
