"""Tests: One-Piece-Händlerliste aus der Datenbank."""

import json
import tempfile
import unittest
from pathlib import Path

from waechter.konfig import lade_konfig
from waechter.onepiece_haendler import mit_datenbank


def eintrag(i, **extra):
    d = {"id": i, "domain": f"{i}.example", "basis_url": f"https://{i}.example", "name": i.title(), "land": "DE",
         "plattform": "shopify", "status": "geeignet", "vertrauen": "ungeprueft", "waehrung": "EUR"}
    d.update(extra)
    return d


class Datenbank(unittest.TestCase):
    def erweitert(self, haendler):
        with tempfile.TemporaryDirectory() as t:
            datei = Path(t) / "db.json"
            datei.write_text(json.dumps({"haendler": {h["id"]: h for h in haendler}}), encoding="utf-8")
            return lade_konfig(), mit_datenbank(lade_konfig(), datei)

    def test_nur_geeignete_shopify_haendler(self):
        _, k = self.erweitert([eintrag("gut"), eintrag("woo", plattform="woocommerce"), eintrag("kaputt", status="blockiert")])
        ids = [s.id for s in k.shops]
        self.assertIn("gut", ids)
        self.assertNotIn("woo", ids)
        self.assertNotIn("kaputt", ids)

    def test_alarm_nur_fuer_vorgepruefte(self):
        _, k = self.erweitert([eintrag("a"), eintrag("b", vertrauen="vorgeprueft")])
        frei = {s.id: s.kaufalarm_freigegeben for s in k.shops}
        self.assertFalse(frei["a"])
        self.assertTrue(frei["b"])

    def test_ausgeschlossene_und_doppelte_fehlen(self):
        basis, k = self.erweitert([eintrag("tcgdistro"), eintrag("zenith", name="TCG Zenith"),
                                   eintrag("cardcosmos2", domain="cardcosmos.de", basis_url="https://cardcosmos.de")])
        ids = [s.id for s in k.shops]
        self.assertNotIn("tcgdistro", ids)
        self.assertNotIn("zenith", ids)
        self.assertNotIn("cardcosmos2", ids)
        self.assertEqual(len(basis.shops), len(k.shops) - 0)

    def test_versand_bleibt_unbekannt(self):
        _, k = self.erweitert([eintrag("x")])
        self.assertEqual(next(s for s in k.shops if s.id == "x").versand_de.status, "unbekannt")

    def test_fehlende_datei_ist_kein_fehler(self):
        k = lade_konfig()
        self.assertIs(mit_datenbank(k, Path("/gibt/es/nicht.json")), k)


if __name__ == "__main__":
    unittest.main()
