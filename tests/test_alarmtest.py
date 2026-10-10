"""Tests: Alarm-Test (Dojo + Telegram, markiert als TEST)."""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from waechter import alarmtest, dojo

JETZT = dt.datetime(2026, 10, 9, 12, 0, tzinfo=dt.timezone.utc)


class AlarmTest(unittest.TestCase):
    def lauf(self, **kw):
        with tempfile.TemporaryDirectory() as t:
            daten, ziel = Path(t) / "laufzeit", Path(t)
            nachrichten = []
            with mock.patch("waechter.telegram.konfiguration", return_value=(True, "aktiv")):
                ok = alarmtest.ausfuehren(daten, ziel, jetzt=JETZT, sender=lambda x: (nachrichten.append(x) or (True, "ok")),
                                          log=lambda s: None, **kw)
            status = json.loads((ziel / "status.json").read_text(encoding="utf-8"))
            return ok, nachrichten, status

    def test_beide_alarme_im_dojo_und_in_telegram(self):
        ok, msgs, st = self.lauf()
        self.assertTrue(ok)
        self.assertEqual(len(msgs), 2)
        self.assertTrue(all("TEST" in m for m in msgs))
        self.assertEqual(st["state"], "alert")
        stat = {s["id"]: s["status"] for s in st["sites"]}
        self.assertEqual(stat["produkt"], "restock")
        self.assertEqual(stat["op_restock"], "restock")

    def test_nur_one_piece(self):
        _, msgs, st = self.lauf(welche=("onepiece",))
        self.assertEqual(len(msgs), 1)
        stat = {s["id"]: s["status"] for s in st["sites"]}
        self.assertEqual(stat["op_restock"], "restock")
        self.assertNotEqual(stat.get("produkt"), "restock")

    def test_ohne_telegram_wird_nichts_gesendet(self):
        ok, msgs, st = self.lauf(senden=False)
        self.assertTrue(ok)
        self.assertEqual(msgs, [])
        self.assertEqual(st["state"], "alert")

    def test_testalarm_ist_nach_einer_viertelstunde_vorbei(self):
        with tempfile.TemporaryDirectory() as t:
            alarmtest.ausfuehren(Path(t) / "l", Path(t), jetzt=JETZT, senden=False, log=lambda s: None)
            z = json.loads((Path(t) / "l" / "zustand.json").read_text(encoding="utf-8"))
        spaeter = JETZT + dt.timedelta(minutes=20)
        self.assertNotEqual(dojo.erzeuge(z, spaeter)["state"], "alert")


if __name__ == "__main__":
    unittest.main()
