"""Tests: Welche Angebote zählen als Ziel-Produkt – und welche ausdrücklich nicht."""

import unittest

from waechter import modelle as m
from waechter.klassifizierung import klassifiziere
from waechter.konfig import lade_konfig

PRODUKTE = lade_konfig().produkte


def zuordnen(titel, handle="", tags=(), variante=""):
    from waechter.zuordnung import ordne_zu
    k = klassifiziere(titel, variante, handle, list(tags), setnamen=PRODUKTE["displays"]["setnamen"])
    text = titel if not variante else f"{titel} {variante}"
    return ordne_zu(text, k, PRODUKTE)


class Displays(unittest.TestCase):
    def test_englisches_display_ist_sicher(self):
        t, _ = zuordnen("One Piece Card Game - OP13 Carrying On His Will Booster Display - EN")
        self.assertEqual((t.ziel_id, t.sicherheit, t.prioritaet), ("display-OP13", m.SICHER, True))

    def test_japanisches_display_ausgeschlossen(self):
        t, grund = zuordnen("One Piece Card Game - OP13 Booster Display - JPN")
        self.assertIsNone(t)
        self.assertIn("Sprache JP", grund)

    def test_chinesisch_und_asia_ausgeschlossen(self):
        self.assertIsNone(zuordnen("One Piece OP13 Booster Box Chinese")[0])
        self.assertIsNone(zuordnen("One Piece OP13 Booster Box Asia English")[0])

    def test_unklare_sprache_ist_unsicher(self):
        t, _ = zuordnen("One Piece OP13 Booster Display")
        self.assertEqual(t.sicherheit, m.UNSICHER)

    def test_case_variante_ausgeschlossen(self):
        t, grund = zuordnen("One Piece Card Game - OP13 Booster Display - EN", variante="Case (12 Displays)")
        self.assertIsNone(t)
        self.assertIn("CASE", grund)
        t, _ = zuordnen("One Piece Card Game - OP13 Booster Display - EN", variante="Display")
        self.assertEqual(t.ziel_id, "display-OP13")

    def test_booster_pack_und_einzelkarte_ausgeschlossen(self):
        self.assertIsNone(zuordnen("One Piece Card Game OP-13 Booster Pack - English")[0])
        self.assertIsNone(zuordnen("Monkey D. Luffy (OP13-118) English Alternate Art")[0])

    def test_geoeffnet_ausgeschlossen(self):
        t, grund = zuordnen("One Piece OP13 Booster Display EN (opened, 20 packs left)")
        self.assertIsNone(t)

    def test_extra_booster_ist_kein_op_display(self):
        self.assertIsNone(zuordnen("One Piece Card Game Extra Booster EB-05 Booster Box (24 Packs) - English")[0])

    def test_anderes_spiel_ignoriert(self):
        t, grund = zuordnen("Digimon Card Game – Timeless Bonds BT-26 Booster Display (Englisch)")
        self.assertIsNone(t)
        self.assertEqual(grund, "kein One-Piece-Produkt")


class Sleeved(unittest.TestCase):
    def test_op09_op13(self):
        self.assertEqual(zuordnen("One Piece OP09 Sleeved Booster - English")[0].ziel_id, "sleeved-OP09")
        self.assertEqual(zuordnen("One Piece OP-13 Sleeved Booster EN")[0].ziel_id, "sleeved-OP13")

    def test_anderes_set_nicht(self):
        self.assertIsNone(zuordnen("One Piece OP05 Sleeved Booster English")[0])

    def test_japanisch_nicht(self):
        self.assertIsNone(zuordnen("One Piece OP09 Sleeved Booster JPN")[0])


class Sonderprodukte(unittest.TestCase):
    def test_pcc_29th_englisch(self):
        t, _ = zuordnen("One Piece Card Game Premium Card Collection -29th Anniversary Edition- (English)")
        self.assertEqual((t.ziel_id, t.sicherheit), ("pcc-29th", m.SICHER))

    def test_pcc_verwechslungen(self):
        for titel in ["Premium Card Collection -25th Edition- English",
                      "Premium Card Collection - Best Selection Vol.5 - One Piece Products",
                      "One Piece Premium Card Collection -Live Action Edition vol.2- English"]:
            self.assertIsNone(zuordnen(titel)[0], titel)

    def test_pcc_29th_japanisch(self):
        self.assertIsNone(zuordnen("One Piece Premium Card Collection 29th Anniversary Edition (JPN)")[0])

    def test_2nd_anniversary_set_offizieller_name(self):
        t, _ = zuordnen("One Piece Card Game English Version 2nd Anniversary Set")
        self.assertEqual((t.ziel_id, t.sicherheit), ("2nd-anniversary-set-en", m.SICHER))

    def test_limited_collection_name_bleibt_unsicher(self):
        t, _ = zuordnen("One Piece Card Game 2nd Anniversary LIMITED COLLECTION (English)")
        self.assertEqual(t.sicherheit, m.UNSICHER)
        self.assertTrue(any("nicht belegt" in g for g in t.gruende))

    def test_anniversary_verwechslungen(self):
        for titel in ["One Piece Card Game Japanese 2nd Anniversary Set",
                      "One Piece Card Game 2nd Anniversary Complete Guide + 2 Card (JAP)",
                      "ONE PIECE Card Game BASE SHOP Limited Card Collection vol.1 Japanese",
                      "One Piece Card Game English Version 3rd Anniversary Set",
                      "One Piece 25th Anniversary Limited Collection Card Set English",
                      "One Piece Card Game Special Goods Set - Former Four Emperors (Playmat, Box & Promo)"]:
            t, _ = zuordnen(titel)
            self.assertTrue(t is None or t.ziel_id != "2nd-anniversary-set-en", titel)


if __name__ == "__main__":
    unittest.main()
