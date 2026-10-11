"""Tests der optionalen Händlersuche (ohne Netzwerk; Suchergebnisse sind KÜNSTLICHE TESTDATEN)."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import datetime as dt
import tomllib

from waechter.suche import suche, alle_anfragen, plane_anfragen


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

    def test_anfragenpool_reicht_fuer_eine_woche_und_hat_keine_doppelten(self):
        with open(Path(__file__).parent.parent / "config" / "suche.toml", "rb") as f:
            cfg = tomllib.load(f)
        liste = alle_anfragen(cfg)
        self.assertGreaterEqual(len(liste), 100)
        self.assertEqual(len(liste), len({(a["q"], a["land"]) for a in liste}))

    def test_wochenbudget_100_und_lauflimit(self):
        cfg = {"budget": {"pro_woche": 100, "pro_lauf": 15},
               "gruppen": [{"land": "DE", "produkte": [f"p{i}" for i in range(20)], "begriffe": ["a", "b", "c", "d", "e", "f"]}]}
        z, gesamt, tag = {}, 0, dt.date(2026, 10, 12)   # Montag KW42
        for i in range(8):
            anfragen, z = plane_anfragen(cfg, z, tag + dt.timedelta(days=i % 7 if i < 7 else 7))
            if i < 7:
                gesamt += len(anfragen)
                z["verbraucht"] += len(anfragen)
                z["cursor"] += len(anfragen)
        self.assertEqual(gesamt, 100)           # 6x15 + 10 = 100, siebter Tag bekommt den Rest
        anfragen, z = plane_anfragen(cfg, z, dt.date(2026, 10, 19))   # neue Woche: Budget zurückgesetzt
        self.assertEqual(len(anfragen), 15)
        self.assertEqual(z["verbraucht"], 0)

    def test_suche_zaehlt_verbrauch_und_bricht_bei_429_ab(self):
        import urllib.error
        def transport(url):
            raise urllib.error.HTTPError(url, 429, "limit", {}, None)
        with tempfile.TemporaryDirectory() as d:
            z = Path(d) / "z.json"
            (Path(d) / "k.csv").write_text("domain;name;land;quelle\n", encoding="utf-8")
            erg = suche(log=lambda s: None, transport=transport, kandidaten_datei=Path(d) / "k.csv", zustand_datei=z,
                        heute=dt.date(2026, 10, 12))
            self.assertEqual(erg["suchen"], 0)   # nach dem ersten 429 sofort Schluss, nichts verbraucht


if __name__ == "__main__":
    unittest.main()
