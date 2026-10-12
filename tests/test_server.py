"""Tests: Server-Modus (eigene Betriebswerte, Quelle im Dojo-Status, atomares Schreiben)."""

import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from waechter import dojo
from waechter.naruto_lauf import lade_betrieb


class Server(unittest.TestCase):
    def test_standard_ist_github_takt(self):
        with mock.patch.dict(os.environ, {"WAECHTER_BETRIEB": ""}):
            self.assertEqual(lade_betrieb()["intervalle"]["naruto_produktseite"], 120)

    def test_server_takt_ueber_umgebung(self):
        with mock.patch.dict(os.environ, {"WAECHTER_BETRIEB": "config/betrieb_server.toml"}):
            b = lade_betrieb()
        self.assertEqual(b["intervalle"]["naruto_produktseite"], 60)
        self.assertEqual(b["intervalle"]["onepiece"], 60)
        self.assertIn("Server", b["betrieb"]["ausfuehrung"])

    def test_status_nennt_quelle_und_ist_vollstaendig(self):
        zustand = {"aufgaben": {}, "naruto": {"angebote": {}}, "ereignisse_kurz": []}
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"WAECHTER_QUELLE": "server"}):
            datei = dojo.schreibe(zustand, Path(d), dt.datetime(2026, 10, 12, 8, 0, tzinfo=dt.timezone.utc))
            j = json.loads(datei.read_text(encoding="utf-8"))
            self.assertEqual(j["quelle"], "server")
            self.assertFalse(list(Path(d).glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
