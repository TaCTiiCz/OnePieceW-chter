"""Tests: Lauf-Protokoll bleibt klein (GitHub-Grenze 100 MB pro Datei)."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from waechter import speicher
from waechter.speicher import Speicher, kompakter_lauf


def voller_lauf(i):
    return {"zeit": f"2026-10-19T00:{i % 60:02d}:00+00:00", "testdaten": False, "beobachtungen": 400,
            "ereignisse": [{"typ": "RESTOCK"}], "telegram": "Telegram aktiv", "telegram_gesendet": 1, "telegram_fehler": [],
            "uebersprungen": ["a", "b"],
            "shops": {f"shop{j}": {"name": "x" * 200, "fehler": ["HTTP 429"] if j == 0 else []} for j in range(50)}}


class Laeufe(unittest.TestCase):
    def test_kompakt(self):
        k = kompakter_lauf(voller_lauf(1))
        self.assertEqual((k["shops"], k["ereignisse"], k["uebersprungen"]), (50, 1, 2))
        self.assertEqual(k["shops_mit_fehler"], {"shop0": "HTTP 429"})
        self.assertLess(len(json.dumps(k)), 600)
        self.assertEqual(kompakter_lauf(k), k, "schon kompakt bleibt unverändert")

    def test_datei_wird_gekuerzt(self):
        with tempfile.TemporaryDirectory() as t:
            sp = Speicher(Path(t))
            datei = Path(t) / "laeufe.jsonl"
            datei.write_text("".join(json.dumps(voller_lauf(i)) + "\n" for i in range(300)))   # altes, großes Format
            with mock.patch.object(speicher, "MAX_LAEUFE", 100), mock.patch.object(speicher, "KUERZEN_AB_BYTES", 1000):
                sp.lauf(voller_lauf(999))
            zeilen = datei.read_text().splitlines()
            self.assertEqual(len(zeilen), 100)
            self.assertTrue(all("shops_mit_fehler" in z for z in zeilen))


if __name__ == "__main__":
    unittest.main()
