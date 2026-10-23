"""Tests: Pokémon-„30 Jahre“-Erkennung und Normalpreis-Meldungen.

Alle Shopseiten in dieser Datei sind KÜNSTLICHE TESTDATEN (kein echter Shop, keine echten Preise).
"""

import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from waechter import dojo, modelle as m, pokemon, push
from waechter.naruto_lauf import KAUFALARM, POKEMON, Lauf, lade_betrieb, pokemon_wege
from tests.test_naruto import FakeAbrufer, Kanal, produktseite

CFG = pokemon.lade_pokemon()


class Erkennung(unittest.TestCase):
    def p(self, titel, url=""):
        return pokemon.pruefe(titel, url, cfg=CFG)

    def test_englische_etb(self):
        t = self.p("Pokémon TCG: 30th Celebration Elite Trainer Box (English)")
        self.assertTrue(t.passend)
        self.assertEqual((t.sicherheit, t.sprache, t.variante), (m.SICHER, "EN", "ETB"))

    def test_deutsche_top_trainer_box_ohne_sprachangabe(self):
        t = self.p("Pokémon Sammelkartenspiel 30 Jahre Top-Trainer-Box")
        self.assertTrue(t.passend)
        self.assertEqual((t.sprache, t.variante), ("DE", "ETB"))

    def test_ditto_und_upc(self):
        self.assertEqual(self.p("30th Celebration Ditto Premium Collection - EN").variante, "DITTO")
        self.assertEqual(self.p("Pokemon 30 Jahre Ultra-Premium-Kollektion Nacht (Deutsch)").variante, "UPC")
        self.assertEqual(self.p("Pokémon Center Elite Trainer Box 30th Celebration").variante, "PC_ETB")

    def test_ausschluesse(self):
        for titel in ["Mewtwo ex 151/128 30th Celebration", "30th Celebration Booster Box Japanese",
                      "PSA 10 Pikachu 30th Celebration", "Celebrations Elite Trainer Box", "30 Jahre Jubiläums-Tasse",
                      "30th Celebration Elite Trainer Box Case (10x)", "Pokémon 30th Celebration Booster Display 36"]:
            self.assertFalse(self.p(titel).passend, titel)

    def test_wege_ersetzen_naruto_suche(self):
        wege = pokemon_wege([{"art": "shopsuche", "url": "https://x.test/search?q=naruto"},
                             {"art": "kategorie_naruto", "url": "https://x.test/naruto"},
                             {"art": "shopify_neueste", "url": "https://x.test/products.json?limit=100"}], CFG)
        urls = [w["url"] for w in wege]
        self.assertIn("https://x.test/search?q=30th+celebration", urls)
        self.assertNotIn("https://x.test/naruto", urls)
        self.assertIn("https://x.test/products.json?limit=100", urls)


B = "https://shop.test"
KAT = B + "/neuheiten"
PROD = B + "/p/pokemon-30th-celebration-elite-trainer-box-en"


class Szenario:
    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp())
        shops = {"shop": {"id": "shop", "name": "Testshop", "domain": "shop.test", "basis_url": B, "land": "DE",
                          "plattform": "unbekannt", "status": "geeignet", "vertrauen": "vorgeprueft",
                          "entdeckung": [{"art": "kategorie_vorbestellung", "url": KAT}]}}
        (self.tmp / "db.json").write_text(json.dumps({"haendler": shops}))
        self.titel = "Pokémon 30th Celebration Elite Trainer Box (EN)"
        self.status, self.knopf, self.preis = "InStock", True, "54.99"
        self.zeit = dt.datetime(2026, 10, 23, 8, 0, tzinfo=dt.timezone.utc)
        self.kanal = Kanal()
        self.betrieb = copy.deepcopy(lade_betrieb())

    def lauf(self):
        seiten = {KAT: f'<a href="/p/pokemon-30th-celebration-elite-trainer-box-en">{self.titel}</a>',
                  PROD: lambda: produktseite(self.titel, self.status, self.preis, self.knopf)}
        l = Lauf(None, FakeAbrufer(seiten), self.tmp / "daten", db_datei=self.tmp / "db.json", ncfg=copy.deepcopy(CFG),
                 betrieb=self.betrieb, push_kanal=self.kanal, log=lambda s: None, onepiece=False, jetzt=self.zeit,
                 thema=POKEMON)
        l.ausfuehren(nur_faellige=False)
        l.speichern()
        self.zeit += dt.timedelta(minutes=10)
        return [e for e in l.ereignisse if not e["unterdrueckt"] and e["gesendet"]], l


class Meldungen(unittest.TestCase):
    def test_noch_nicht_ausverkauft_wird_sofort_gemeldet(self):
        s = Szenario()
        e, _ = s.lauf()
        self.assertEqual([x["typ"] for x in e], [KAUFALARM])
        self.assertIn("POKÉMON 30 JAHRE", s.kanal.nachrichten[-1])
        self.assertIn("Normalpreis", s.kanal.nachrichten[-1])
        self.assertEqual([x["typ"] for x in s.lauf()[0]], [], "keine Wiederholung, solange bestellbar")

    def test_scalperpreis_wird_nicht_gemeldet(self):
        s = Szenario()
        s.preis = "149.99"
        e, _ = s.lauf()
        self.assertEqual(e, [])
        self.assertEqual(s.kanal.nachrichten, [])

    def test_restock_nach_ausverkauft(self):
        s = Szenario()
        s.status, s.knopf = "OutOfStock", False
        self.assertEqual(s.lauf()[0], [])
        s.status, s.knopf = "InStock", True
        e, l = s.lauf()
        self.assertEqual([x["typ"] for x in e], [KAUFALARM])
        status = dojo.erzeuge({}, s.zeit, pokemon=l.zustand)
        self.assertEqual(status["pokemon"]["status"], "catch")
        self.assertEqual(status["state"], "alert")

    def test_push_text(self):
        t = push.formatiere({"typ": KAUFALARM, "thema": "pokemon", "text": "x", "titel": "ETB", "grenze_text": "bis 62 €"})
        self.assertNotIn("/gekauft", t)
        self.assertNotIn("Sommer 2027", t)


if __name__ == "__main__":
    unittest.main()
