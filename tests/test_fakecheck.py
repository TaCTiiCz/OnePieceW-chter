"""Tests: Fake-Shop-Überwachung (künstliche Testdaten)."""

import unittest

from waechter import modelle as m
from waechter.abruf import Antwort
from waechter.fakecheck import anwenden, bewerte_shop, preis_verdacht

SEITE_GUT = ("<html><body>One Piece Display. Zahlung: PayPal, Klarna, Kreditkarte. Kontakt: info@shop-gut.de Tel 0911 123456 "
             "Trusted Shops Käuferschutz</body></html>")
LINKS_GUT = [("https://shop-gut.de/agb", "AGB"), ("https://shop-gut.de/widerruf", "Widerruf"),
             ("https://shop-gut.de/datenschutz", "Datenschutz")]
IMP_GUT = {"ust_id": "DE123456789", "register": True, "rechtsform": "GmbH", "beleg": "info@shop-gut.de"}


class RDAP:
    def __init__(self, tage):
        self.tage = tage

    def hole(self, url):
        import datetime as dt
        t = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=self.tage)).isoformat()
        return Antwort(True, 200, '{"events":[{"eventAction":"registration","eventDate":"%s"}]}' % t)


class Shop(unittest.TestCase):
    def test_serioeser_shop_gering(self):
        b = bewerte_shop("shop-gut.de", "DE", SEITE_GUT, LINKS_GUT, IMP_GUT, RDAP(2000))
        self.assertEqual(b["stufe"], "gering")

    def test_fake_shop_hoch_und_alarmrecht_weg(self):
        seite = "<html>Räumungsverkauf! bis zu 90% Rabatt. Zahlung nur Vorkasse oder Bitcoin.</html>"
        b = bewerte_shop("onepiece-sale24.top", "DE", seite, [], None, RDAP(20))
        self.assertEqual(b["stufe"], "hoch")
        e = {"vertrauen": "vorgeprueft", "gruende": []}
        anwenden(e, b)
        self.assertEqual(e["vertrauen"], "ungeprueft")
        self.assertTrue(any("Fake-Shop-Verdacht" in g for g in e["gruende"]))

    def test_rdap_nicht_erreichbar_gibt_keine_punkte(self):
        class Aus:
            def hole(self, url):
                return Antwort(False, 500, "", "Fehler")
        b = bewerte_shop("shop-gut.de", "DE", SEITE_GUT, LINKS_GUT, IMP_GUT, Aus())
        self.assertIsNone(b["domain_alter_tage"])
        self.assertEqual(b["stufe"], "gering")

    def test_mittleres_risiko_nimmt_vorpruefung_zurueck(self):
        b = {"stufe": "mittel", "punkte": 3, "signale": ["x"]}
        e = {"vertrauen": "vorgeprueft", "gruende": []}
        anwenden(e, b)
        self.assertEqual(e["vertrauen"], "ungeprueft")


def angebot(shop, preis, ziel="display-OP15", status=m.IN_STOCK):
    return {"letzte": {"ziel_id": ziel, "shop_id": shop, "abruf_ok": True, "status": status, "waehrung": "EUR", "preis_cent": preis}}


class Preis(unittest.TestCase):
    Z = {"angebote": {f"a{i}": angebot(f"s{i}", p) for i, p in enumerate([11000, 11500, 12000, 10500])}}

    def test_billig_wird_gewarnt(self):
        self.assertIn("VERDÄCHTIG", preis_verdacht(self.Z, "display-OP15", "neu", 4500, "EUR"))

    def test_normaler_preis_keine_warnung(self):
        self.assertIsNone(preis_verdacht(self.Z, "display-OP15", "neu", 10000, "EUR"))

    def test_zu_wenige_vergleiche_keine_warnung(self):
        z = {"angebote": {"a": angebot("s1", 11000)}}
        self.assertIsNone(preis_verdacht(z, "display-OP15", "neu", 1000, "EUR"))


if __name__ == "__main__":
    unittest.main()
