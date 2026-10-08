"""Tests der Händlerdatenbank-Prüfung. Alle Shopseiten hier sind KÜNSTLICHE TESTDATEN."""

import json
import tempfile
import unittest
from pathlib import Path

from waechter.abruf import Abrufer
from waechter.haendlerdb import (ausschlussgrund, impressum_auswerten, kategorien_finden, links, pruefe_alle,
                                 suchformular, versand_auswerten)

SHOPIFY_START = """<html><head><script src="https://cdn.shopify.com/s/x.js"></script></head><body>
<a href="/collections/vorbestellungen">Vorbestellungen</a> <a href="/collections/neuheiten">Neuheiten</a>
<a href="/collections/naruto-card-game">Naruto Card Game</a> <a href="https://andere-seite.de/x">extern</a>
<p>Pokémon One Piece Lorcana Booster Display TCG</p></body></html>"""
WOO_START = """<html><body class="woocommerce"><form role="search" method="get" action="/">
<input type="search" name="s"><input type="hidden" name="post_type" value="product"></form>
<a href="/impressum/">Impressum</a><a href="/versand/">Versand &amp; Zahlung</a>
<p>Pokemon Magic One Piece Sammelkarten Booster</p></body></html>"""
IMPRESSUM = "<p>Muster TCG GmbH, Hauptstr. 1, 12345 Musterstadt. Registergericht: Amtsgericht X, HRB 12345. USt-IdNr.: DE123456789</p>"
VERSAND = "<p>Versand innerhalb Deutschlands: 4,95 €. Lieferung in die EU auf Anfrage.</p>"


def fake(antworten):
    def transport(url, kopf, timeout):
        if url in antworten:
            return 200, {"x-final-url": url}, antworten[url]
        return 404, {}, ""
    return Abrufer({}, schlafen=lambda s: None, transport=transport, pausen=(0.0,))


class Hilfen(unittest.TestCase):
    def test_ausschluss(self):
        self.assertIn("dauerhaft", ausschlussgrund("tcgdistronline.com"))
        self.assertIn("dauerhaft", ausschlussgrund("www.tcgdistro.com"))
        self.assertIn("Vertrauensprüfung", ausschlussgrund("tcgzenith.com"))
        self.assertIn("Vertrauensprüfung", ausschlussgrund("example.com", "TCG Zenith"))
        self.assertIsNone(ausschlussgrund("cardcosmos.de"))

    def test_links_nur_eigene_domain(self):
        l = links(SHOPIFY_START, "https://shop.example")
        self.assertTrue(all(u.startswith("https://shop.example/") for u, _ in l))
        self.assertEqual(len(l), 3)

    def test_kategorien(self):
        k = kategorien_finden(links(SHOPIFY_START, "https://shop.example"))
        self.assertEqual([x["art"] for x in k], ["naruto", "vorbestellung", "neuheiten"])

    def test_suchformular(self):
        url = suchformular(WOO_START, "https://shop.example", "naruto")
        self.assertIn("s=naruto", url)
        self.assertIn("post_type=product", url)

    def test_impressum_und_versand(self):
        i = impressum_auswerten(IMPRESSUM)
        self.assertEqual(i["ust_id"], "DE123456789")
        self.assertTrue(i["register"])
        self.assertEqual(i["rechtsform"], "GmbH")
        v = versand_auswerten(VERSAND)
        self.assertTrue(v["nennt_deutschland"])
        self.assertIn("4,95", v["betrag_hinweis"])


class Gesamtpruefung(unittest.TestCase):
    def test_pruefung_mit_testdaten(self):
        antworten = {
            "https://shopify.example/robots.txt": "User-agent: *\nDisallow: /search\nSitemap: https://shopify.example/sitemap.xml",
            "https://shopify.example/": SHOPIFY_START,
            "https://shopify.example/meta.json": json.dumps({"country": "DE", "currency": "EUR", "ships_to_countries": ["DE", "AT"]}),
            "https://shopify.example/policies/legal-notice": IMPRESSUM,
            "https://shopify.example/policies/shipping-policy": VERSAND,
            "https://woo.example/robots.txt": "",
            "https://woo.example/": WOO_START,
            "https://woo.example/impressum/": IMPRESSUM,
            "https://woo.example/versand/": VERSAND,
            "https://woo.example/wp-json/wc/store/v1/products?search=naruto&per_page=50": "[]",
        }
        kandidaten = [{"domain": "shopify.example", "name": "A", "land": "AT", "quelle": "Test"},
                      {"domain": "woo.example", "name": "B", "land": "DE", "quelle": "Test"},
                      {"domain": "tcgdistronline.com", "name": "C", "land": "DE", "quelle": "Test"},
                      {"domain": "weg.example", "name": "D", "land": "DE", "quelle": "Test"}]
        with tempfile.TemporaryDirectory() as d:
            ziel = Path(d) / "db.json"
            z = pruefe_alle(fake(antworten), ziel, kandidaten, parallel=2, log=lambda s: None)
            db = json.loads(ziel.read_text())
        h = {x["domain"]: x for x in db["haendler"].values()}
        self.assertEqual(h["shopify.example"]["plattform"], "shopify")
        self.assertEqual(h["shopify.example"]["versand_de"], "ja")
        self.assertEqual(h["shopify.example"]["status"], "geeignet")
        self.assertEqual(h["shopify.example"]["vertrauen"], "vorgeprueft")
        arten = {e["art"] for e in h["shopify.example"]["entdeckung"]}
        self.assertTrue({"shopify_neueste", "kategorie_naruto", "kategorie_vorbestellung", "sitemap"} <= arten)
        self.assertEqual(h["woo.example"]["plattform"], "woocommerce")
        self.assertIn("woo_api", {e["art"] for e in h["woo.example"]["entdeckung"]})
        self.assertIn("shopsuche", {e["art"] for e in h["woo.example"]["entdeckung"]})
        self.assertEqual(h["tcgdistronline.com"]["status"], "ausgeschlossen")
        self.assertEqual(h["weg.example"]["status"], "nicht_erreichbar")
        self.assertEqual(z["geeignet"], 2)


if __name__ == "__main__":
    unittest.main()
