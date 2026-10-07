"""Tests: Konfiguration, Händler-Ausschluss und Versandkosten."""

import tempfile
import unittest
from pathlib import Path

from waechter.konfig import KONFIG_DIR, KonfigFehler, Versand, ist_ausgeschlossen, lade_konfig

SHOP_VORLAGE = """
[shops.{sid}]
name = "{name}"
basis_url = "{url}"
plattform = "shopify"
waehrung = "EUR"
[shops.{sid}.versand_de]
status = "unbekannt"
"""


def lade_mit(text: str):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "shops.toml"
        p.write_text(text, encoding="utf-8")
        return lade_konfig(p, KONFIG_DIR / "products.toml")


class Ausschluss(unittest.TestCase):
    def test_echte_konfig_laedt(self):
        k = lade_konfig()
        self.assertGreaterEqual(len(k.shops), 3)
        for s in k.shops:
            self.assertFalse(ist_ausgeschlossen(s.basis_url, k.ausschluss_domains, k.ausschluss_namen))

    def test_tcg_distro_und_zenith_werden_abgelehnt(self):
        sperre = '[ausschluss]\nbis_vertrauenspruefung = ["tcgzenith", "tcg zenith"]\n'
        for sid, name, url in [("a", "TCG Distro", "https://tcgdistro.com"),
                               ("b", "Shop", "https://www.tcgdistronline.com"),
                               ("c", "TCG Zenith", "https://example.eu"),
                               ("d", "Irgendwas", "https://shop.tcgzenith.com"),
                               ("tcg_distro", "x", "https://example.org")]:
            with self.assertRaises(KonfigFehler, msg=url):
                lade_mit(sperre + SHOP_VORLAGE.format(sid=sid, name=name, url=url))

    def test_echte_konfig_sperrt_zenith_bis_pruefung(self):
        k = lade_konfig()
        self.assertTrue(ist_ausgeschlossen("TCG Zenith", k.ausschluss_domains, k.ausschluss_namen))

    def test_ausschluss_gilt_auch_ohne_eintrag_in_datei(self):
        # [ausschluss] fehlt komplett -> Pflicht-Ausschlüsse greifen trotzdem
        with self.assertRaises(KonfigFehler):
            lade_mit(SHOP_VORLAGE.format(sid="x", name="x", url="https://tcgdistronline.com"))

    def test_normaler_shop_erlaubt(self):
        k = lade_mit(SHOP_VORLAGE.format(sid="ok", name="Normaler Shop", url="https://example.de"))
        self.assertEqual(k.shops[0].id, "ok")


class VersandKosten(unittest.TestCase):
    def test_unbekannt_ist_nie_null(self):
        v = Versand("unbekannt", [], "", "", "")
        self.assertIsNone(v.kosten_cent(16999))

    def test_staffel(self):
        v = Versand("bekannt", [(0, 590), (20000, 0)], "", "", "")
        self.assertEqual(v.kosten_cent(16999), 590)
        self.assertEqual(v.kosten_cent(20000), 0)
        self.assertIsNone(v.kosten_cent(None))

    def test_bekannt_ohne_staffel_ist_fehler(self):
        text = SHOP_VORLAGE.format(sid="x", name="x", url="https://example.de").replace('"unbekannt"', '"bekannt"')
        with self.assertRaises(KonfigFehler):
            lade_mit(text)


if __name__ == "__main__":
    unittest.main()
