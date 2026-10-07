"""Tests: Händlerlimits respektieren, langsamer werden, keine Sperren umgehen."""

import unittest

from waechter.abruf import USER_AGENT, Abrufer, Robots

SHOPIFY_ROBOTS = """
User-agent: *
Disallow: /admin
Disallow: /cart
Disallow: /checkout
Disallow: /search
Disallow: /collections/*sort_by*
Disallow: /*/collections/*sort_by*
Allow: /search/special$
Crawl-delay: 6
"""


class FakeTransport:
    def __init__(self, antworten: dict):
        self.antworten = {k: list(v) for k, v in antworten.items()}
        self.aufrufe: list[tuple[str, dict]] = []

    def __call__(self, url, kopf, timeout):
        self.aufrufe.append((url, kopf))
        liste = self.antworten.get(url)
        if not liste:
            return 404, {}, ""
        a = liste.pop(0) if len(liste) > 1 else liste[0]
        if isinstance(a, Exception):
            raise a
        return a


def neuer_abrufer(antworten, zustand=None):
    pausen = []
    t = FakeTransport({"https://shop.example/robots.txt": [(200, {}, SHOPIFY_ROBOTS)], **antworten})
    a = Abrufer(zustand if zustand is not None else {}, schlafen=pausen.append, transport=t)
    a.setze_host_regeln("shop.example", 4, 20)
    return a, t, pausen


class RobotsTxt(unittest.TestCase):
    def test_shopify_regeln(self):
        r = Robots(SHOPIFY_ROBOTS)
        self.assertTrue(r.erlaubt("https://x/products/op13.js"))
        self.assertTrue(r.erlaubt("https://x/collections/one-piece/products.json?limit=250&page=1"))
        self.assertFalse(r.erlaubt("https://x/search/suggest.json?q=op13"))
        self.assertFalse(r.erlaubt("https://x/collections/all?sort_by=price"))
        self.assertTrue(r.erlaubt("https://x/search/special"))
        self.assertEqual(r.crawl_delay, 6)

    def test_eigene_gruppe_hat_vorrang(self):
        r = Robots("User-agent: *\nDisallow: /\n\nUser-agent: OnePieceWaechter\nDisallow: /private\n")
        self.assertTrue(r.erlaubt("https://x/products/a"))
        self.assertFalse(r.erlaubt("https://x/private/a"))

    def test_verbotener_abruf_wird_nicht_gesendet(self):
        a, t, _ = neuer_abrufer({})
        antwort = a.hole("https://shop.example/search/suggest.json?q=op13")
        self.assertFalse(antwort.ok)
        self.assertIn("robots.txt", antwort.fehler)
        self.assertEqual([u for u, _ in t.aufrufe], ["https://shop.example/robots.txt"])


class Hoeflichkeit(unittest.TestCase):
    def test_ehrlicher_user_agent(self):
        a, t, _ = neuer_abrufer({"https://shop.example/p.js": [(200, {}, "{}")]})
        a.hole("https://shop.example/p.js")
        ua = t.aufrufe[-1][1]["User-Agent"]
        self.assertEqual(ua, USER_AGENT)
        self.assertIn("OnePieceWaechter", ua)
        self.assertNotIn("Mozilla", ua)

    def test_crawl_delay_wird_eingehalten(self):
        a, t, pausen = neuer_abrufer({"https://shop.example/a.js": [(200, {}, "{}")],
                                      "https://shop.example/b.js": [(200, {}, "{}")]})
        a.hole("https://shop.example/a.js")
        a.hole("https://shop.example/b.js")
        self.assertTrue(any(p >= 5.5 for p in pausen), pausen)

    def test_429_mit_retry_after(self):
        a, t, pausen = neuer_abrufer({"https://shop.example/p.js": [(429, {"Retry-After": "45"}, ""), (200, {}, "{}")]})
        antwort = a.hole("https://shop.example/p.js")
        self.assertTrue(antwort.ok)
        self.assertIn(45.0, pausen)

    def test_wiederholtes_429_pausiert_host(self):
        zustand = {}
        a, t, _ = neuer_abrufer({"https://shop.example/p.js": [(429, {}, "")]}, zustand)
        self.assertFalse(a.hole("https://shop.example/p.js").ok)
        self.assertIn("shop.example", zustand)
        anzahl = len(t.aufrufe)
        self.assertFalse(a.hole("https://shop.example/q.js").ok)
        self.assertEqual(len(t.aufrufe), anzahl, "kein weiterer Abruf beim gedrosselten Host")

    def test_403_stoppt_sofort_und_wird_nicht_umgangen(self):
        zustand = {}
        a, t, pausen = neuer_abrufer({"https://shop.example/p.js": [(403, {}, "Forbidden")]}, zustand)
        antwort = a.hole("https://shop.example/p.js")
        self.assertFalse(antwort.ok)
        self.assertEqual(sum(1 for u, _ in t.aufrufe if u.endswith("p.js")), 1, "kein zweiter Versuch")
        self.assertIn("pause_bis", zustand["shop.example"])
        # Ein neuer Lauf mit demselben gespeicherten Zustand respektiert die Pause
        b, t2, _ = neuer_abrufer({"https://shop.example/p.js": [(200, {}, "{}")]}, zustand)
        self.assertFalse(b.hole("https://shop.example/p.js").ok)
        self.assertEqual(t2.aufrufe, [])

    def test_captcha_seite_wird_erkannt(self):
        html = "<html><head><title>Attention Required! | Cloudflare</title></head><script src='/cdn-cgi/challenge-platform/x'></script>"
        a, t, _ = neuer_abrufer({"https://shop.example/products/x": [(200, {}, html)]})
        antwort = a.hole("https://shop.example/products/x")
        self.assertFalse(antwort.ok)
        self.assertIn("Bot-Schutz", antwort.fehler)

    def test_recaptcha_im_kontaktformular_ist_kein_bot_schutz(self):
        html = "<html><script src='https://www.google.com/recaptcha/api.js'></script>ok</html>"
        a, _, _ = neuer_abrufer({"https://shop.example/products/x": [(200, {}, html)]})
        self.assertTrue(a.hole("https://shop.example/products/x").ok)

    def test_netzwerkfehler_mit_wachsenden_pausen(self):
        a, t, pausen = neuer_abrufer({"https://shop.example/p.js": [ConnectionError("weg")]})
        antwort = a.hole("https://shop.example/p.js")
        self.assertFalse(antwort.ok)
        self.assertEqual([p for p in pausen if p >= 10], [10.0, 30.0, 90.0])

    def test_obergrenze_pro_lauf(self):
        a, t, _ = neuer_abrufer({"https://shop.example/p.js": [(200, {}, "{}")]})
        a.setze_host_regeln("shop.example", 4, 3)
        ergebnisse = [a.hole("https://shop.example/p.js").ok for _ in range(4)]
        self.assertEqual(ergebnisse, [True, True, False, False])


if __name__ == "__main__":
    unittest.main()
