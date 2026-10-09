"""Tests: Dojo-Status (status.json) – richtige Zustände, keine Geheimnisse."""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from waechter import dojo

JETZT = dt.datetime(2026, 10, 9, 12, 0, tzinfo=dt.timezone.utc)


def iso(minuten_zurueck: float) -> str:
    return (JETZT - dt.timedelta(minutes=minuten_zurueck)).isoformat()


def zustand(**extra) -> dict:
    z = {
        "letzter_lauf": {"zeit": iso(3), "dauer_s": 42.0, "haendler": 5},
        "aufgaben": {
            "produkt|a": {"art": "produkt", "zuletzt_ok": iso(3), "fehlerserie": 0},
            "produkt|b": {"art": "produkt", "zuletzt_ok": iso(200), "fehlerserie": 0},
            "shopify_neueste|x": {"art": "shopify_neueste", "zuletzt_ok": iso(3), "fehlerserie": 0},
            "kategorie_bandai|y": {"art": "kategorie_bandai", "zuletzt_ok": iso(500), "fehlerserie": 4},
            "offiziell|o": {"art": "offiziell", "zuletzt_ok": None, "fehlerserie": 0},
        },
        "ereignisse_kurz": [],
        "push": {"aktiv": True, "letzter_erfolg": iso(60)},
    }
    z.update(extra)
    return z


def station(daten, sid):
    return next(s for s in daten["sites"] if s["id"] == sid)


class DojoStatus(unittest.TestCase):
    def test_laufender_betrieb(self):
        d = dojo.erzeuge(zustand(), JETZT)
        self.assertEqual(d["state"], "checking")
        self.assertEqual(station(d, "produkt")["status"], "ok")
        self.assertTrue(station(d, "produkt")["im_lauf"])
        self.assertFalse(station(d, "langsam")["im_lauf"])

    def test_station_mit_fehlern(self):
        d = dojo.erzeuge(zustand(), JETZT)
        self.assertEqual(station(d, "langsam")["status"], "error")

    def test_station_ohne_erfolg_ist_unbekannt(self):
        d = dojo.erzeuge(zustand(), JETZT)
        self.assertEqual(station(d, "offiziell")["status"], "unknown")

    def test_one_piece_ohne_aufgabe_hat_kein_pult(self):
        ids = [s["id"] for s in dojo.erzeuge(zustand(), JETZT)["sites"]]
        self.assertNotIn("onepiece", ids)

    def test_kaufalarm_loest_alarm_aus(self):
        z = zustand(ereignisse_kurz=[{"zeit": iso(20), "typ": "KAUFALARM", "text": "Produkt X jetzt vorbestellbar"}])
        d = dojo.erzeuge(z, JETZT)
        self.assertEqual(d["state"], "alert")
        self.assertEqual(station(d, "produkt")["status"], "restock")
        self.assertIn("vorbestellbar", d["events"][0]["text"])

    def test_alter_alarm_zaehlt_nicht(self):
        z = zustand(ereignisse_kurz=[{"zeit": iso(60 * 5), "typ": "KAUFALARM", "text": "alt"}])
        self.assertEqual(dojo.erzeuge(z, JETZT)["state"], "checking")

    def test_fruehhinweis_ist_kein_alarm(self):
        z = zustand(ereignisse_kurz=[{"zeit": iso(5), "typ": "FRUEHHINWEIS", "text": "bald"}])
        self.assertEqual(dojo.erzeuge(z, JETZT)["state"], "checking")

    def test_kein_aktueller_lauf_ist_schlafend(self):
        z = zustand(letzter_lauf={"zeit": iso(120), "dauer_s": 40, "haendler": 5})
        self.assertEqual(dojo.erzeuge(z, JETZT)["state"], "stale")
        self.assertEqual(dojo.erzeuge({}, JETZT)["state"], "stale")

    def test_push_problem_wird_gemeldet(self):
        z = zustand(push={"aktiv": True, "letzter_erfolg": iso(300), "letzter_fehler": f"{iso(10)}: HTTP 401"})
        d = dojo.erzeuge(z, JETZT)
        self.assertEqual(d["state"], "error")
        self.assertTrue(d["stats"]["push_problem"])

    def test_geschriebene_datei_ohne_geheimnisse(self):
        z = zustand(push={"aktiv": True, "beschreibung": "Telegram: aktiv", "token": "123:GEHEIM", "chat": "42"})
        with tempfile.TemporaryDirectory() as t:
            datei = dojo.schreibe(z, Path(t), JETZT)
            text = datei.read_text(encoding="utf-8")
            self.assertNotIn("GEHEIM", text)
            json.loads(text)  # gültiges JSON
            self.assertTrue((Path(t) / "index.html").exists())
            self.assertTrue((Path(t) / ".nojekyll").exists())


if __name__ == "__main__":
    unittest.main()
