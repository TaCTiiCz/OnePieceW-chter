"""Tests der optionalen Händlersuche (ohne Netzwerk; Suchergebnisse sind KÜNSTLICHE TESTDATEN)."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from waechter.suche import suche


class Suche(unittest.TestCase):
    def test_ohne_schluessel_passiert_nichts(self):
        with mock.patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": ""}):
            self.assertFalse(suche(log=lambda s: None)["aktiv"])

    def test_neue_domains_werden_gefiltert_und_angehaengt(self):
        ergebnisse = {"web": {"results": [
            {"url": "https://www.neuer-tcg-shop.de/naruto"}, {"url": "https://www.amazon.de/x"},
            {"url": "https://cardcosmos.de/products/x"}, {"url": "https://tcgdistronline.com/x"},
            {"url": "https://shop.example.jp/x"}, {"url": "https://tcgzenith.com/x"}]}}
        with tempfile.TemporaryDirectory() as d:
            datei = Path(d) / "k.csv"
            datei.write_text("domain;name;land;quelle\ncardcosmos.de;cardcosmos;DE;x\n", encoding="utf-8")
            z = suche(log=lambda s: None, transport=lambda url: ergebnisse, kandidaten_datei=datei)
            inhalt = datei.read_text(encoding="utf-8")
        self.assertEqual(z["neu"], ["neuer-tcg-shop.de"])
        self.assertIn("neuer-tcg-shop.de;", inhalt)
        self.assertNotIn("amazon", inhalt)
        self.assertNotIn("tcgdistro", inhalt)
        self.assertNotIn("tcgzenith", inhalt)


if __name__ == "__main__":
    unittest.main()
