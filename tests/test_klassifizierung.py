"""Tests gegen Sprach- und Produkttyp-Verwechslungen.

Viele Titel stammen aus echten Händler-Abrufen vom 06.10.2026 (siehe tests/fixtures/README.md).
"""

import tomllib
import unittest

from waechter import modelle as m
from waechter.klassifizierung import erkenne_set, erkenne_sprache, erkenne_typ, erkenne_versiegelung, klassifiziere
from waechter.konfig import KONFIG_DIR

with open(KONFIG_DIR / "products.toml", "rb") as f:
    SETNAMEN = tomllib.load(f)["displays"]["setnamen"]


class Sprache(unittest.TestCase):
    def test_englisch_varianten(self):
        for titel in ["One Piece Card Game - OP13 Carrying On His Will Booster Display - EN",
                      "OP15 Adventure on Kami's Island EB04 – Booster Box da 24 Bustine – One Piece Card Game (ENG)",
                      "One Piece OP13 Carrying on his will Display - Englisch",
                      "One Piece Card Game OP15-EB04 Booster Box (24 Packs) – Adventure on Kami’s Island - English"]:
            self.assertEqual(erkenne_sprache(titel)[0], m.EN, titel)

    def test_japanisch_wird_erkannt(self):
        for titel in ["One Piece Card Game - OP13 Booster Display - JPN",
                      "OP15 Adventure on Kami's Island – Booster Box – One Piece Card Game (JAP)",
                      "One Piece OP09 Display Japanisch"]:
            self.assertEqual(erkenne_sprache(titel)[0], "JP", titel)

    def test_handle_verraet_sprache(self):
        self.assertEqual(erkenne_sprache("One Piece OP09 Display", handle="one-piece-op09-display-japanisch")[0], "JP")

    def test_suchwort_english_im_shop_macht_jpn_nicht_englisch(self):
        # Echter Fall: Suche nach "one piece display english" lieferte JPN-Displays
        self.assertEqual(erkenne_sprache("One Piece Card Game - OP17 Booster Display The World’s Strongest Warriors - JPN",
                                         handle="one-piece-card-game-op17-booster-display-the-worlds-strongest-warriors-japanisch")[0], "JP")

    def test_widerspruch(self):
        self.assertEqual(erkenne_sprache("One Piece OP13 Display - EN", handle="op13-display-japanisch")[0], m.WIDERSPRUCH)

    def test_ohne_angabe_unbekannt(self):
        self.assertEqual(erkenne_sprache("One Piece OP13 Booster Display")[0], m.UNBEKANNT)

    def test_asia_englisch_ist_nicht_englisch(self):
        self.assertEqual(erkenne_sprache("One Piece OP13 Booster Box Asia English Version")[0], m.EN_ASIA)

    def test_beschreibung_wird_fuer_sprache_ignoriert(self):
        k = klassifiziere("Megaevoluzione: Caos Nascente - Booster Box - Pokémon TCG (IT)",
                          beschreibung="36 boosters ... (English: Chaos Rising)")
        self.assertEqual(k.sprache, "IT")

    def test_woerter_wie_den_oder_de_sind_kein_marker(self):
        self.assertEqual(erkenne_sprache("Caja de sobres OP13 One Piece")[0], m.UNBEKANNT)
        self.assertEqual(erkenne_sprache("Get it now: OP13 Booster Box")[0], m.UNBEKANNT)

    def test_kurzcodes_in_klammern(self):
        self.assertEqual(erkenne_sprache("One Piece OP13 Booster Display (DE)")[0], "DE")
        self.assertEqual(erkenne_sprache("Scarlet and Violet Surging Sparks - Booster Display (ITA)")[0], "IT")
        self.assertEqual(erkenne_sprache("One Piece OP13 Booster Display - DE")[0], "DE")


class SetCode(unittest.TestCase):
    def test_schreibweisen(self):
        for t in ["OP13", "OP-13", "OP 13", "OP-013", "[OP-13]"]:
            self.assertEqual(erkenne_set(f"One Piece {t} Booster Box")[0], "OP13", t)

    def test_kombiniertes_set(self):
        self.assertEqual(erkenne_set("OP15-EB04 Booster Box")[0], "OP15")

    def test_kartennummer_ist_kein_set(self):
        self.assertIsNone(erkenne_set("Electrical Luna (OP08-036) - Rare")[0])

    def test_setname_ohne_code(self):
        self.assertEqual(erkenne_set("One Piece Two Legends Booster Box English", SETNAMEN)[0], "OP08")

    def test_zwei_sets_mehrdeutig(self):
        self.assertIsNone(erkenne_set("Bundle OP13 + OP14 Booster Box")[0])

    def test_op1_nicht_op10(self):
        self.assertEqual(erkenne_set("OP-01 Romance Dawn Booster Box")[0], "OP01")
        self.assertEqual(erkenne_set("OP-10 Royal Blood Booster Display")[0], "OP10")


class Produkttyp(unittest.TestCase):
    def fall(self, titel, erwartet):
        self.assertEqual(erkenne_typ(titel)[0], erwartet, titel)

    def test_display_varianten(self):
        self.fall("One Piece Card Game - OP13 Carrying On His Will Booster Display - EN", m.DISPLAY)
        self.fall("One Piece Card Game OP15-EB04 Booster Box (24 Packs) - English", m.DISPLAY)
        self.fall("OP15 Adventure on Kami's Island EB04 – Booster Box da 24 Bustine (ENG)", m.DISPLAY)

    def test_case_ist_kein_display(self):
        self.fall("One Piece Card Game OP15-EB04 Booster Box Case (12 Boxes) - English", m.CASE)
        self.fall("One Piece OP09 Booster Display - JPN Case (12 Displays)", m.CASE)
        self.fall("Heroines Edition Booster Box Case (12x Booster Box)", m.CASE)

    def test_einzelner_booster_ist_kein_display(self):
        self.fall("One Piece Card Game OP-17 Booster Pack - English", m.BOOSTER_PACK)
        self.fall("One Piece Card Game - Adventure on Kami´s Island Booster Pack (OP15) - English", m.BOOSTER_PACK)

    def test_sleeved(self):
        self.fall("One Piece OP09 Sleeved Booster English", m.SLEEVED_BOOSTER)

    def test_einzelkarten(self):
        self.fall("Electrical Luna (OP08-036) - Two Legends (Rare) [OP08-036]", m.EINZELKARTE)
        self.fall("Boa Hancock Manga OP07-051 - BGS 10 - One Piece Card Game (ENG)", m.EINZELKARTE)
        self.fall("One Piece - Nami Ill. Alt. Art OP01-016 (The Best) – AOG 10 Gem Mint", m.EINZELKARTE)

    def test_zubehoer(self):
        self.fall("One Piece Card Game Special Goods Set - Former Four Emperors (Playmat, Box & Promo)", m.ZUBEHOER)
        self.fall("Ultimate Guard Squaroes – One Piece Edition – Deck Boxen & Collectors Case", m.ZUBEHOER)

    def test_sonstige(self):
        self.fall("Double Pack Set Vol.10 - Adventure on Kami’s Island", m.DOUBLE_PACK)
        self.fall("One Piece Card Game Starter Deck [ST-21] - English", m.STARTER_DECK)
        self.fall("Premium Card Collection -29th Anniversary Edition- English", m.PREMIUM_CARD_COLLECTION)
        self.fall("One Piece Card Game English Version 2nd Anniversary Set", m.ANNIVERSARY_SET)


class Versiegelung(unittest.TestCase):
    def test_werte(self):
        self.assertEqual(erkenne_versiegelung("OP13 Display EN", ["OVP"], "")[0], m.JA)
        self.assertEqual(erkenne_versiegelung("OP13 Display EN - opened", [], "")[0], m.NEIN)
        self.assertEqual(erkenne_versiegelung("OP13 Display EN (unopened)", [], "")[0], m.JA)
        self.assertEqual(erkenne_versiegelung("OP13 Display EN", [], "")[0], m.UNBEKANNT)
        self.assertEqual(erkenne_versiegelung("OP13 Display EN repack", ["sealed"], "")[0], m.NEIN)


if __name__ == "__main__":
    unittest.main()
