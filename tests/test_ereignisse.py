"""Tests gegen falsche Restock-Meldungen und doppelte Benachrichtigungen."""

import datetime as dt
import unittest

from waechter import modelle as m
from waechter.ereignisse import verarbeite

T0 = dt.datetime(2026, 10, 6, 8, 0, tzinfo=dt.timezone.utc)
EINST = {"preisrueckgang_min_prozent": 3.0, "preisrueckgang_min_euro": 2.0, "wiederholsperre_stunden": 24}


def beob(status=m.SOLD_OUT, preis=16999, ok=True, sicherheit=m.SICHER, waehrung="EUR", bestaetigt=True, aid="shop:op13:1"):
    return m.Beobachtung(
        angebot_id=aid, shop_id="shop", shop_name="Testshop", ziel_id="display-OP13",
        ziel_anzeige="OP13 Booster Display (EN, 24 Packs)", kategorie="display", sicherheit=sicherheit,
        prioritaet=True, titel="One Piece OP13 Booster Display EN", variante="", url="https://example.invalid/op13",
        zeitpunkt=T0.isoformat(), abruf_ok=ok, status=status if ok else m.UNCLEAR, status_gruende=[],
        sprache=m.EN, typ=m.DISPLAY, set_code="OP13", versiegelt=m.UNBEKANNT, vollstaendig=m.UNBEKANNT,
        preis_cent=preis if ok else None, waehrung=waehrung if ok else None, waehrung_bestaetigt=bestaetigt and ok,
        versand_cent=499 if ok else None, versand_hinweis="", gesamt_cent=(preis + 499) if ok and preis else None,
        fehler=None if ok else "HTTP 503")


class Szenario:
    """Spielt mehrere Prüfläufe nacheinander durch."""

    def __init__(self, freigegeben=True):
        self.zustand = {"angebote": {}, "meldungen": {}}
        self.basis = False
        self.freigegeben = freigegeben
        self.zeit = T0

    def lauf(self, b, stunden=2):
        e, _ = verarbeite(b, self.zustand, shop_basis_erfasst=self.basis, shop_freigegeben=self.freigegeben,
                          einstellungen=EINST, jetzt=self.zeit)
        self.basis = True  # nach dem ersten Lauf ist die Ausgangsbasis erfasst
        self.zeit += dt.timedelta(hours=stunden)
        return [x for x in e if not x.unterdrueckt]


class Ausgangsbasis(unittest.TestCase):
    def test_erster_lauf_meldet_nichts_auch_wenn_lieferbar(self):
        s = Szenario()
        self.assertEqual(s.lauf(beob(m.IN_STOCK)), [])

    def test_erster_lauf_mit_fehler_dann_lieferbar_meldet_nichts(self):
        s = Szenario()
        s.lauf(beob(ok=False))
        self.assertEqual(s.lauf(beob(m.IN_STOCK)), [])


class Restock(unittest.TestCase):
    def test_ausverkauft_dann_lieferbar(self):
        s = Szenario()
        s.lauf(beob(m.SOLD_OUT))
        e = s.lauf(beob(m.IN_STOCK))
        self.assertEqual([x.typ for x in e], [m.RESTOCK])
        self.assertTrue(e[0].alarm)

    def test_warteliste_dann_lieferbar(self):
        s = Szenario()
        s.lauf(beob(m.WAITLIST))
        self.assertEqual([x.typ for x in s.lauf(beob(m.IN_STOCK))], [m.RESTOCK])

    def test_abruffehler_loest_keinen_restock_aus(self):
        s = Szenario()
        s.lauf(beob(m.IN_STOCK))
        self.assertEqual(s.lauf(beob(ok=False)), [])
        self.assertEqual(s.lauf(beob(m.IN_STOCK)), [], "lieferbar -> Fehler -> lieferbar ist kein Restock")

    def test_ausverkauft_fehler_lieferbar_ist_restock(self):
        s = Szenario()
        s.lauf(beob(m.SOLD_OUT))
        s.lauf(beob(ok=False))
        self.assertEqual([x.typ for x in s.lauf(beob(m.IN_STOCK))], [m.RESTOCK])

    def test_unclear_ueberschreibt_letzten_sicheren_status_nicht(self):
        s = Szenario()
        s.lauf(beob(m.SOLD_OUT))
        self.assertEqual(s.lauf(beob(m.UNCLEAR)), [])
        self.assertEqual(s.zustand["angebote"]["shop:op13:1"]["letzter_sicherer_status"], m.SOLD_OUT)

    def test_lieferbar_bleibt_lieferbar_keine_wiederholung(self):
        s = Szenario()
        s.lauf(beob(m.SOLD_OUT))
        self.assertEqual(len(s.lauf(beob(m.IN_STOCK))), 1)
        for _ in range(5):
            self.assertEqual(s.lauf(beob(m.IN_STOCK)), [])

    def test_flattern_innerhalb_sperre_wird_unterdrueckt(self):
        s = Szenario()
        s.lauf(beob(m.SOLD_OUT))
        self.assertEqual(len(s.lauf(beob(m.IN_STOCK), stunden=1)), 1)
        s.lauf(beob(m.SOLD_OUT), stunden=1)
        self.assertEqual(s.lauf(beob(m.IN_STOCK)), [], "gleiche Meldung innerhalb 24 h")

    def test_nach_sperre_wieder_meldung(self):
        s = Szenario()
        s.lauf(beob(m.SOLD_OUT))
        s.lauf(beob(m.IN_STOCK), stunden=13)
        s.lauf(beob(m.SOLD_OUT), stunden=13)
        self.assertEqual(len(s.lauf(beob(m.IN_STOCK))), 1)


class Vorbestellung(unittest.TestCase):
    def test_neues_angebot_nach_basis(self):
        s = Szenario()
        s.lauf(beob(m.SOLD_OUT))  # Basis
        e = s.lauf(beob(m.PREORDER, aid="shop:op18:1"))
        self.assertEqual([x.typ for x in e], [m.NEUE_VORBESTELLUNG])

    def test_ausverkauft_dann_vorbestellbar(self):
        s = Szenario()
        s.lauf(beob(m.SOLD_OUT))
        self.assertEqual([x.typ for x in s.lauf(beob(m.PREORDER))], [m.NEUE_VORBESTELLUNG])

    def test_neues_ausverkauftes_angebot_meldet_nichts(self):
        s = Szenario()
        s.lauf(beob(m.SOLD_OUT))
        self.assertEqual(s.lauf(beob(m.SOLD_OUT, aid="shop:op18:1")), [])

    def test_vorbestellung_wird_lieferbar_kein_alarm(self):
        s = Szenario()
        s.lauf(beob(m.PREORDER))
        self.assertEqual(s.lauf(beob(m.IN_STOCK)), [])


class Preis(unittest.TestCase):
    def test_kleiner_rueckgang_ignoriert(self):
        s = Szenario()
        s.lauf(beob(m.IN_STOCK, 16999))
        self.assertEqual(s.lauf(beob(m.IN_STOCK, 16899)), [])

    def test_deutlicher_rueckgang(self):
        s = Szenario()
        s.lauf(beob(m.IN_STOCK, 16999))
        e = s.lauf(beob(m.IN_STOCK, 14999))
        self.assertEqual([x.typ for x in e], [m.PREISRUECKGANG])

    def test_andere_waehrung_kein_vergleich(self):
        s = Szenario()
        s.lauf(beob(m.IN_STOCK, 16999))
        self.assertEqual(s.lauf(beob(m.IN_STOCK, 9999, waehrung="USD")), [])

    def test_unbestaetigte_waehrung_kein_vergleich(self):
        s = Szenario()
        s.lauf(beob(m.IN_STOCK, 16999))
        self.assertEqual(s.lauf(beob(m.IN_STOCK, 9999, bestaetigt=False)), [])

    def test_ausverkauft_mit_niedrigerem_preis_kein_alarm(self):
        s = Szenario()
        s.lauf(beob(m.IN_STOCK, 16999))
        self.assertEqual(s.lauf(beob(m.SOLD_OUT, 9999)), [])


class Freigabe(unittest.TestCase):
    def test_nicht_freigegebener_haendler_kein_kaufalarm(self):
        s = Szenario(freigegeben=False)
        s.lauf(beob(m.SOLD_OUT))
        e = s.lauf(beob(m.IN_STOCK))
        self.assertEqual(len(e), 1)
        self.assertFalse(e[0].alarm)
        self.assertIn("nicht", e[0].alarm_grund)

    def test_unsicherer_treffer_kein_kaufalarm(self):
        s = Szenario()
        s.lauf(beob(m.SOLD_OUT, sicherheit=m.UNSICHER))
        e = s.lauf(beob(m.IN_STOCK, sicherheit=m.UNSICHER))
        self.assertFalse(e[0].alarm)


if __name__ == "__main__":
    unittest.main()
