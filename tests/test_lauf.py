"""Ende-zu-Ende-Tests mit TESTDATEN: mehrere Prüfläufe hintereinander."""

import datetime as dt
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from waechter import modelle as m
from waechter.abruf import TestdatenAbrufer
from waechter.bericht import erzeuge_bericht
from waechter.konfig import lade_konfig
from waechter.lauf import fuehre_aus
from waechter.speicher import Speicher

FIX = Path(__file__).parent / "fixtures"
OP13_JS = "shopify/cardcosmos/op13-en.js.json"
OP13_URL = "https://cardcosmos.de/products/one-piece-op13-display-englisch.js"
T0 = dt.datetime(2026, 10, 6, 8, 0, tzinfo=dt.timezone.utc)


class Lauf(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fix = self.tmp / "fixtures"
        shutil.copytree(FIX, self.fix)
        self.daten = Speicher(self.tmp / "data")
        self.konfig = lade_konfig()
        self.zeit = T0

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def setze_op13(self, verfuegbar: bool, preis: int = 16999):
        p = self.fix / OP13_JS
        js = json.loads(p.read_text(encoding="utf-8"))
        js["available"] = verfuegbar
        js["variants"][0].update(available=verfuegbar, price=preis)
        p.write_text(json.dumps(js), encoding="utf-8")
        # Die sichtbare Seite muss dazu passen, sonst gilt der Status (richtigerweise) als widersprüchlich
        h = self.fix / "shopify/cardcosmos/op13-en.html"
        alt, neu = ("OutOfStock", "InStock") if verfuegbar else ("InStock", "OutOfStock")
        h.write_text(h.read_text(encoding="utf-8").replace(alt, neu), encoding="utf-8")

    def test_widerspruch_seite_und_daten_ist_unklar(self):
        self.lauf()
        p = self.fix / OP13_JS
        js = json.loads(p.read_text(encoding="utf-8"))
        js["variants"][0]["available"] = True
        p.write_text(json.dumps(js), encoding="utf-8")  # Seite sagt weiter "OutOfStock"
        z = self.lauf()
        self.assertEqual(self.ereignisse(z), [])
        b = self.daten.lade_zustand()["angebote"]["cardcosmos:one-piece-op13-display-englisch:2001"]["letzte"]
        self.assertEqual(b["status"], m.UNCLEAR)

    def setze_fehler(self, url: str, status: int | None):
        p = self.fix / "manifest.json"
        man = json.loads(p.read_text(encoding="utf-8"))
        if status is None:
            man["urls"][url] = {"datei": OP13_JS}
        else:
            man["urls"][url] = {"status": status, "fehler": f"HTTP {status} (Test)"}
        p.write_text(json.dumps(man), encoding="utf-8")

    def lauf(self, testdaten=True, transport=None):
        z = fuehre_aus(self.konfig, TestdatenAbrufer(self.fix), self.daten, testdaten=testdaten, jetzt=self.zeit,
                       telegram_transport=transport, log=lambda s: None)
        self.zeit += dt.timedelta(hours=2)
        return z

    def ereignisse(self, z, typ=None):
        return [e for e in z["ereignisse"] if not e["unterdrueckt"] and (typ is None or e["typ"] == typ)]

    def test_parallel_liefert_dasselbe_wie_nacheinander(self):
        z = fuehre_aus(self.konfig, TestdatenAbrufer(self.fix), self.daten, testdaten=True, jetzt=self.zeit,
                       log=lambda s: None, zeitbudget=600, parallel=4)
        self.assertEqual(z["uebersprungen"], [])
        self.assertTrue(all(s["basis_erfasst"] for s in self.daten.lade_zustand()["shops"].values()))
        self.setze_op13(True)
        self.zeit += dt.timedelta(hours=2)
        z = fuehre_aus(self.konfig, TestdatenAbrufer(self.fix), self.daten, testdaten=True, jetzt=self.zeit,
                       log=lambda s: None, zeitbudget=600, parallel=4)
        self.assertEqual(len(self.ereignisse(z, m.RESTOCK)), 1)

    def test_zeitbudget_verschiebt_shops_auf_den_naechsten_lauf(self):
        z = fuehre_aus(self.konfig, TestdatenAbrufer(self.fix), self.daten, testdaten=True, jetzt=self.zeit,
                       log=lambda s: None, zeitbudget=1e-9, parallel=2)
        self.assertEqual(sorted(z["uebersprungen"]), sorted(s.id for s in self.konfig.shops))
        self.assertEqual(self.daten.lade_zustand()["shops"], {})

    def test_erster_lauf_ist_nur_ausgangsbasis(self):
        self.setze_op13(True)  # sogar lieferbar -> trotzdem kein Restock beim ersten Lauf
        z = self.lauf()
        self.assertEqual(self.ereignisse(z), [])
        self.assertTrue(all(s["basis_erfasst"] for s in self.daten.lade_zustand()["shops"].values()))

    def test_restock_wird_einmal_erkannt(self):
        self.lauf()
        self.setze_op13(True)
        z = self.lauf()
        r = self.ereignisse(z, m.RESTOCK)
        self.assertEqual(len(r), 1)
        self.assertTrue(r[0]["alarm"])  # cardcosmos ist freigegeben
        self.assertEqual(self.ereignisse(self.lauf()), [], "keine Wiederholung im nächsten Lauf")

    def test_abruffehler_dazwischen(self):
        self.lauf()                                   # SOLD OUT
        self.setze_fehler(OP13_URL, 503)
        self.assertEqual(self.ereignisse(self.lauf()), [])  # Fehler -> nichts
        self.setze_fehler(OP13_URL, None)
        self.setze_op13(False)
        self.assertEqual(self.ereignisse(self.lauf()), [])  # wieder SOLD OUT -> nichts
        verlauf = self.daten.lies_jsonl(f"verlauf/{T0.strftime('%Y-%m')}.jsonl")
        fehler = [v for v in verlauf if v["angebot"].startswith("cardcosmos:one-piece-op13") and not v["abruf_ok"]]
        self.assertEqual(len(fehler), 1)
        self.assertTrue(all(v["quelle"].startswith("https://") and v["zeit"] for v in verlauf))

    def test_preisrueckgang(self):
        self.setze_op13(True, 16999)
        self.lauf()
        self.setze_op13(True, 14999)
        z = self.lauf()
        self.assertEqual([e["typ"] for e in self.ereignisse(z)], [m.PREISRUECKGANG])

    def test_versand_unbekannt_bleibt_unbekannt(self):
        self.lauf()
        angebote = self.daten.lade_zustand()["angebote"]
        universe = [a["letzte"] for k, a in angebote.items() if k.startswith("universetcg:")]
        self.assertTrue(universe)
        for b in universe:
            self.assertIsNone(b["versand_cent"])
            self.assertIsNone(b["gesamt_cent"])
        op19 = angebote["cardcosmos:one-piece-card-game-op19-booster-display-englisch:2004"]["letzte"]
        self.assertIsNone(op19["preis_cent"], "Preis 0,00 ist unbekannt, nicht kostenlos")

    def test_bericht_kennzeichnet_testdaten(self):
        self.lauf()
        text = erzeuge_bericht(self.konfig, self.daten.lade_zustand())
        self.assertIn("TESTDATEN – KEINE LIVE-PRÜFUNG", text)
        self.assertIn("https://cardcosmos.de/products/one-piece-op13-display-englisch", text)

    def test_testdaten_lauf_sendet_nie_telegram(self):
        gesendet = []
        with mock.patch.dict(os.environ, {"TELEGRAM_AKTIV": "1", "TELEGRAM_BOT_TOKEN": "123:GEHEIM",
                                          "TELEGRAM_CHAT_ID": "42"}):
            self.lauf(transport=lambda u, d: gesendet.append(u) or (200, '{"ok":true}'))
            self.setze_op13(True)
            self.lauf(transport=lambda u, d: gesendet.append(u) or (200, '{"ok":true}'))
        self.assertEqual(gesendet, [])

    def test_telegram_einmal_und_ohne_token_in_dateien(self):
        gesendet = []

        def transport(url, daten):
            gesendet.append(daten.decode())
            return 200, '{"ok": true}'

        with mock.patch.dict(os.environ, {"TELEGRAM_AKTIV": "1", "TELEGRAM_BOT_TOKEN": "123:GEHEIM",
                                          "TELEGRAM_CHAT_ID": "42"}):
            self.lauf(testdaten=False, transport=transport)
            self.setze_op13(True)
            self.lauf(testdaten=False, transport=transport)
            self.lauf(testdaten=False, transport=transport)
        self.assertEqual(len(gesendet), 1)
        self.assertIn("Restock", gesendet[0])
        for datei in (self.tmp / "data").rglob("*"):
            if datei.is_file():
                self.assertNotIn("GEHEIM", datei.read_text(encoding="utf-8"), datei)

    def test_nicht_freigegebener_haendler_kein_telegram(self):
        # Otakura ist nicht freigegeben: Restock erscheint im Bericht, aber nicht per Telegram
        gesendet = []
        p = self.fix / "shopify/otakura/op15-box-eng.js.json"
        with mock.patch.dict(os.environ, {"TELEGRAM_AKTIV": "1", "TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"}):
            self.lauf(testdaten=False, transport=lambda u, d: gesendet.append(d) or (200, '{"ok":true}'))
            js = json.loads(p.read_text(encoding="utf-8"))
            js["variants"][0]["available"] = True
            p.write_text(json.dumps(js), encoding="utf-8")
            z = self.lauf(testdaten=False, transport=lambda u, d: gesendet.append(d) or (200, '{"ok":true}'))
        r = self.ereignisse(z, m.RESTOCK)
        self.assertEqual(len(r), 1)
        self.assertFalse(r[0]["alarm"])
        self.assertEqual(gesendet, [])


if __name__ == "__main__":
    unittest.main()
