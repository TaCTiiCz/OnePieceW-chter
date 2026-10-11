"""Tests: One-Piece-Prüfung für Shops ohne Shopify (HTML-Auswertung)."""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from waechter import modelle as m
from waechter.abruf import Antwort
from waechter.konfig import lade_konfig
from waechter.lauf import fuehre_aus
from waechter.onepiece_generisch import _kandidaten, listen_urls_aus_db
from waechter.onepiece_haendler import mit_datenbank
from waechter.speicher import Speicher

BASIS = "https://op-woo.example"
LISTE = BASIS + "/product-category/one-piece/"
DISPLAY_URL = BASIS + "/produkt/one-piece-op15-adventure-on-kamis-island-booster-display-24-packs-english/"

LISTE_HTML = f"""<html><body>
<a href="{DISPLAY_URL}">One Piece OP15 Adventure on Kami's Island Booster Display (24 Packs) English</a>
<a href="{BASIS}/produkt/pokemon-display/">Pokemon Display</a>
<a href="{BASIS}/product-category/one-piece/page/2/">One Piece Seite 2</a>
<a href="{BASIS}/blog/one-piece-news/">One Piece News</a>
</body></html>"""


def produktseite(verfuegbar: bool, preis="109.90"):
    av = "https://schema.org/InStock" if verfuegbar else "https://schema.org/OutOfStock"
    knopf = '<button class="single_add_to_cart_button">In den Warenkorb</button>' if verfuegbar else "<p>Ausverkauft</p>"
    return f"""<html><head><title>OP15 Display</title>
<script type="application/ld+json">{{"@type":"Product","name":"One Piece Card Game OP15 Adventure on Kami's Island Booster Display (24 Packs) English",
"offers":{{"@type":"Offer","price":"{preis}","priceCurrency":"EUR","availability":"{av}"}}}}</script></head>
<body><h1>One Piece Card Game OP15 Adventure on Kami's Island Booster Display (24 Packs) English</h1>{knopf}</body></html>"""


class Fake:
    def __init__(self, seiten):
        self.seiten = seiten
        self.angefragt = []

    def host_pausiert(self, host): return None
    def setze_host_regeln(self, *a, **k): pass

    def hole(self, url):
        self.angefragt.append(url)
        if url in self.seiten:
            return Antwort(True, 200, text=self.seiten[url], url=url)
        return Antwort(False, 404, fehler="404", url=url)


def db_datei(tmp, vertrauen="vorgeprueft"):
    h = {"id": "opwoo", "domain": "op-woo.example", "basis_url": BASIS, "name": "OP Woo", "land": "DE",
         "plattform": "woocommerce", "status": "geeignet", "vertrauen": vertrauen, "waehrung": "EUR",
         "entdeckung": [{"art": "kategorie_bandai", "url": LISTE},
                        {"art": "shopsuche", "url": BASIS + "/?post_type=product&s=naruto"},
                        {"art": "kategorie_naruto", "url": BASIS + "/category/naruto/"},
                        {"art": "sitemap", "url": BASIS + "/sitemap.xml"}]}
    p = Path(tmp) / "db.json"
    p.write_text(json.dumps({"haendler": {"opwoo": h}}), encoding="utf-8")
    return p


class Listen(unittest.TestCase):
    def test_listen_urls_aus_db(self):
        h = json.loads(db_datei(tempfile.mkdtemp()).read_text())["haendler"]["opwoo"]
        u = listen_urls_aus_db(h)
        self.assertIn(LISTE, u)
        self.assertTrue(any("one+piece+display" in x for x in u))
        self.assertFalse(any("naruto" in x.lower() for x in u))
        self.assertFalse(any("sitemap" in x for x in u))

    def test_kandidaten_filtern_rauschen(self):
        k = dict(_kandidaten(LISTE_HTML, LISTE, BASIS))
        self.assertIn(DISPLAY_URL, k)
        self.assertNotIn(BASIS + "/produkt/pokemon-display/", k)
        self.assertFalse(any("/blog/" in u for u in k))

    def test_woo_api(self):
        api = BASIS + "/wp-json/wc/store/v1/products?search=one+piece"
        text = json.dumps([{"name": "One Piece OP13 Display", "permalink": BASIS + "/p/op13/"}])
        self.assertEqual(_kandidaten(text, api, BASIS), [(BASIS + "/p/op13/", "One Piece OP13 Display")])

    def test_ohne_listen_kein_shop(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "db.json"
            p.write_text(json.dumps({"haendler": {"x": {"id": "x", "domain": "x.example", "basis_url": "https://x.example",
                "name": "X", "plattform": "woocommerce", "status": "geeignet", "entdeckung": [{"art": "sitemap", "url": "https://x.example/s.xml"}]}}}))
            self.assertNotIn("x", [s.id for s in mit_datenbank(lade_konfig(), p).shops])


class Lauf(unittest.TestCase):
    def lauf(self, tmp, abrufer, vertrauen="vorgeprueft"):
        konfig = mit_datenbank(lade_konfig(), db_datei(tmp, vertrauen))
        konfig.shops[:] = [s for s in konfig.shops if s.id == "opwoo"]
        sp = Speicher(Path(tmp) / "z")
        return fuehre_aus(konfig, abrufer, sp, telegram_senden=False, log=lambda s: None)

    def test_restock_wird_gemeldet(self):
        with tempfile.TemporaryDirectory() as t:
            seiten = {LISTE: LISTE_HTML, DISPLAY_URL: produktseite(False)}
            z1 = self.lauf(t, Fake(seiten))
            self.assertEqual([e for e in z1["ereignisse"] if e["alarm"]], [])
            seiten[DISPLAY_URL] = produktseite(True)
            z2 = self.lauf(t, Fake(seiten))
            alarme = [e for e in z2["ereignisse"] if e["alarm"] and e["typ"] == m.RESTOCK]
            self.assertEqual(len(alarme), 1, z2["ereignisse"])
            self.assertIn("OP15", alarme[0]["text"])

    def test_ohne_vertrauen_kein_alarm(self):
        with tempfile.TemporaryDirectory() as t:
            seiten = {LISTE: LISTE_HTML, DISPLAY_URL: produktseite(False)}
            self.lauf(t, Fake(seiten), vertrauen="ungeprueft")
            seiten[DISPLAY_URL] = produktseite(True)
            z = self.lauf(t, Fake(seiten), vertrauen="ungeprueft")
            self.assertEqual([e for e in z["ereignisse"] if e["alarm"]], [])

    def test_bekanntes_angebot_wird_auch_ohne_liste_geprueft(self):
        with tempfile.TemporaryDirectory() as t:
            self.lauf(t, Fake({LISTE: LISTE_HTML, DISPLAY_URL: produktseite(False)}))
            f = Fake({DISPLAY_URL: produktseite(True)})   # Liste fehlt jetzt (404)
            z = self.lauf(t, f)
            self.assertIn(DISPLAY_URL, f.angefragt)
            self.assertTrue([e for e in z["ereignisse"] if e["alarm"]])

    def test_abruffehler_loest_nichts_aus(self):
        with tempfile.TemporaryDirectory() as t:
            self.lauf(t, Fake({LISTE: LISTE_HTML, DISPLAY_URL: produktseite(False)}))
            z = self.lauf(t, Fake({LISTE: LISTE_HTML}))   # Produktseite 404
            self.assertEqual([e for e in z["ereignisse"] if e["alarm"]], [])

    def test_preis_fehlt_ist_unklar(self):
        with tempfile.TemporaryDirectory() as t:
            self.lauf(t, Fake({LISTE: LISTE_HTML, DISPLAY_URL: produktseite(False)}))
            seite_ohne_preis = produktseite(True, preis="0")
            z = self.lauf(t, Fake({LISTE: LISTE_HTML, DISPLAY_URL: seite_ohne_preis}))
            self.assertEqual([e for e in z["ereignisse"] if e["alarm"]], [])


if __name__ == "__main__":
    unittest.main()
