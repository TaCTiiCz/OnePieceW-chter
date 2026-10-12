"""Tests: Telegram-Befehle /status, /lieferbar, /hilfe (künstliche Testdaten, kein Netz)."""

import datetime as dt
import json
import os
import unittest
import urllib.parse
from unittest import mock

from waechter import befehle
from waechter import modelle as m

JETZT = dt.datetime(2026, 10, 12, 12, 0, tzinfo=dt.timezone.utc)
ENV = {"TELEGRAM_AKTIV": "true", "TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "42"}


class FakeTelegram:
    def __init__(self, updates):
        self.updates, self.gesendet, self.offsets = updates, [], []

    def __call__(self, url, daten):
        methode = url.split("/bot123:abc/")[1].split("?")[0]
        if methode == "getUpdates":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            off = int(q["offset"][0]); self.offsets.append(off)
            return 200, json.dumps({"ok": True, "result": [u for u in self.updates if u["update_id"] >= off]})
        if methode == "sendMessage":
            self.gesendet.append(urllib.parse.parse_qs(daten.decode())["text"][0])
        return 200, json.dumps({"ok": True, "result": True})


def nachricht(uid, text, chat=42, alter_s=5):
    return {"update_id": uid, "message": {"chat": {"id": chat}, "text": text, "date": int(JETZT.timestamp()) - alter_s}}


def angebot(shop, ziel, preis, status=m.IN_STOCK, sicher=m.SICHER, alter_min=5):
    t = (JETZT - dt.timedelta(minutes=alter_min)).isoformat()
    return {"zuletzt_geprueft": t, "letzte": {"shop_id": shop, "shop_name": shop.title(), "ziel_id": ziel,
            "ziel_anzeige": f"{ziel[-4:]} Booster Display (EN, 24 Packs)", "status": status, "kategorie": "display",
            "sicherheit": sicher, "waehrung": "EUR", "preis_cent": preis, "url": f"https://{shop}.example/p",
            "zeitpunkt": t}}


OP = {"shops": {"a": {"zuletzt_geprueft": (JETZT - dt.timedelta(minutes=3)).isoformat()}},
      "angebote": {"1": angebot("a", "display-OP13", 11999), "2": angebot("b", "display-OP13", 10999),
                   "3": angebot("a", "display-OP09", 30000), "4": angebot("a", "display-OP15", 12999, m.PREORDER),
                   "5": angebot("x", "display-OP11", 9999), "6": angebot("a", "display-OP12", 1699),
                   "7": angebot("a", "display-OP16", 13999, sicher=m.UNSICHER),
                   "8": angebot("a", "display-OP14", 14999, alter_min=600)}}
NZ = {"aufgaben": {"t1": {"zuletzt_versuch": (JETZT - dt.timedelta(seconds=40)).isoformat(), "letzter_fehler": None}},
      "naruto": {"angebote": {"n1": {"letzte": {"passend": True, "status": "PREORDER"}},
                              "n2": {"letzte": {"passend": False, "status": "IN STOCK"}}}}}


class Befehle(unittest.TestCase):
    def lauf(self, updates, zustand=None):
        befehle._befehle_gemeldet = False
        fake = FakeTelegram(updates)
        z = zustand if zustand is not None else json.loads(json.dumps(NZ))
        with mock.patch.dict(os.environ, ENV):
            n = befehle.bearbeite(z, lambda: OP, lambda: {"a", "b"}, log=lambda s: None, transport=fake, jetzt=JETZT)
        return n, fake, z

    def test_status_wird_beantwortet_und_offset_gemerkt(self):
        n, fake, z = self.lauf([nachricht(10, "/status")])
        self.assertEqual(n, 1)
        self.assertEqual(z["telegram_befehle"]["offset"], 11)
        t = fake.gesendet[0]
        self.assertIn("läuft", t)
        self.assertIn("Vorbestellbar: 1", t)          # nur passende Naruto-Angebote
        self.assertIn("2 lieferbar, 1 vorbestellbar", t)
        self.assertLess(t.index("109,99"), t.index("119,99") if "119,99" in t else len(t))

    def test_fremde_chats_werden_ignoriert(self):
        n, fake, z = self.lauf([nachricht(5, "/status", chat=999)])
        self.assertEqual((n, fake.gesendet), (0, []))
        self.assertEqual(z["telegram_befehle"]["offset"], 6)   # trotzdem weiter, sonst kommt sie ewig wieder

    def test_alte_nachrichten_beim_ersten_abruf_nicht_beantworten(self):
        n, fake, _ = self.lauf([nachricht(1, "/status", alter_s=3600)])
        self.assertEqual(n, 0)

    def test_kein_doppeltes_beantworten(self):
        z = json.loads(json.dumps(NZ))
        self.lauf([nachricht(10, "/hilfe")], z)
        n, fake, _ = self.lauf([nachricht(10, "/hilfe")], z)
        self.assertEqual(n, 0)
        self.assertEqual(fake.offsets[-1], 11)

    def test_lieferbar_filtert_sauber(self):
        t = befehle.lieferbar_text(OP, {"a", "b"}, JETZT)
        self.assertIn("109,99", t)                     # günstigstes OP13 (Händler b)
        self.assertNotIn("119,99", t)                  # pro Set nur das günstigste
        self.assertNotIn("300,00", t)                  # über 250 €
        self.assertNotIn("99,99", t.replace("109,99", ""))   # ungeprüfter Händler x
        self.assertNotIn("16,99", t)                   # Einzelbooster-Preis
        self.assertNotIn("139,99", t)                  # unsicher erkannt
        self.assertNotIn("149,99", t)                  # zu lange nicht geprüft
        self.assertIn("129,99", t)                     # Vorbestellung OP15

    def test_unbekannter_befehl_bekommt_hilfe(self):
        n, fake, _ = self.lauf([nachricht(3, "/xyz")])
        self.assertIn("/lieferbar", fake.gesendet[0])

    def test_ohne_telegram_nichts(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_AKTIV": ""}):
            self.assertEqual(befehle.bearbeite({}, dict, set, transport=FakeTelegram([])), 0)


if __name__ == "__main__":
    unittest.main()
