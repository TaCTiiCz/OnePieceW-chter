"""Findet neue Produktseiten über öffentliche Quellen eines Shops.

Alle Treffer sind nur KANDIDATEN. Erst der Abruf der konkreten Produktseite entscheidet
über Verfügbarkeit, Sprache und Preis.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from .haendlerdb import links

SUCHWORT = re.compile(r"naruto", re.I)
_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


@dataclass
class Kandidat:
    url: str
    titel: str
    quelle: str
    hersteller: str = ""
    tags: tuple = ()


def _seite_setzen(url: str, seite: int) -> str:
    p = urlparse(url)
    q = parse_qs(p.query)
    q["page"] = [str(seite)]
    return urlunparse(p._replace(query=urlencode({k: v[0] for k, v in q.items()})))


def aus_shopify_json(text: str, basis: str, quelle: str) -> tuple[list[Kandidat], int]:
    daten = json.loads(text)
    produkte = daten.get("products", []) if isinstance(daten, dict) else []
    erg = []
    for p in produkte:
        titel = p.get("title", "")
        tags = p.get("tags", [])
        tags = tuple(tags if isinstance(tags, list) else str(tags).split(","))
        if SUCHWORT.search(titel) or SUCHWORT.search(p.get("handle", "")) or any(SUCHWORT.search(t) for t in tags):
            erg.append(Kandidat(f"{basis}/products/{p.get('handle')}", titel, quelle, p.get("vendor", ""), tags))
    return erg, len(produkte)


def aus_woo_json(text: str, quelle: str) -> list[Kandidat]:
    daten = json.loads(text)
    erg = []
    for p in daten if isinstance(daten, list) else []:
        titel = re.sub(r"<[^>]+>", "", str(p.get("name", "")))
        url = p.get("permalink", "")
        if url and (SUCHWORT.search(titel) or SUCHWORT.search(url)):
            erg.append(Kandidat(url, titel, quelle))
    return erg


def aus_html(text: str, basis: str, quelle: str) -> list[Kandidat]:
    gesehen: dict[str, Kandidat] = {}
    for url, linktext in links(text, basis):
        if not (SUCHWORT.search(linktext) or SUCHWORT.search(urlparse(url).path)):
            continue
        pfad = urlparse(url).path.lower()
        if any(x in pfad for x in ("/blog", "/news", "/pages/", "/collections/", "/category/", "/kategorie/", "/tag/",
                                   "/search", "/suche", "/cart", "/account", "/login")):
            continue
        u = url.split("#")[0]
        if u not in gesehen or len(linktext) > len(gesehen[u].titel):
            gesehen[u] = Kandidat(u, linktext or pfad.rsplit("/", 1)[-1].replace("-", " "), quelle)
    return list(gesehen.values())


def aus_sitemap(text: str, quelle: str) -> tuple[list[Kandidat], list[str]]:
    """Gibt (Produkt-Kandidaten, Unter-Sitemaps) zurück."""
    locs = _LOC.findall(text[:8_000_000])
    if "<sitemapindex" in text[:2000].lower():
        unter = [u for u in locs if "product" in u.lower() or "produkt" in u.lower() or "artikel" in u.lower()] or locs
        return [], unter[:50]
    erg = [Kandidat(u, urlparse(u).path.rsplit("/", 1)[-1].replace("-", " ").replace(".html", ""), quelle)
           for u in locs if SUCHWORT.search(u)]
    return erg, []


def fuehre_aus(aufgabe: dict, abrufer, basis: str) -> tuple[bool, list[Kandidat], Optional[str], dict]:
    """Führt eine Entdeckungsaufgabe aus. Rückgabe: (ok, Kandidaten, Fehler, neuer_Cursor)."""
    art = aufgabe["art"]
    cursor = dict(aufgabe.get("cursor") or {})
    quelle = f"{art}: {aufgabe['url']}"
    try:
        if art == "shopify_katalog":
            seite = int(cursor.get("seite", 1))
            kandidaten: list[Kandidat] = []
            for _ in range(3):  # pro Ausführung höchstens 3 Seiten
                a = abrufer.hole(_seite_setzen(aufgabe["url"], seite))
                if not a.ok:
                    return False, kandidaten, a.fehler, cursor
                k, anzahl = aus_shopify_json(a.text, basis, quelle)
                kandidaten += k
                if anzahl < 250 or seite >= 40:
                    seite = 1
                    break
                seite += 1
            cursor["seite"] = seite
            return True, kandidaten, None, cursor
        if art == "sitemap" and cursor.get("unter"):
            unter = cursor["unter"]
            pos = int(cursor.get("pos", 0))
            kandidaten = []
            for url in unter[pos:pos + 2]:
                a = abrufer.hole(url)
                if not a.ok:
                    return False, kandidaten, a.fehler, cursor
                k, _ = aus_sitemap(a.text, quelle)
                kandidaten += k
            pos += 2
            cursor = {} if pos >= len(unter) else {"unter": unter, "pos": pos}
            return True, kandidaten, None, cursor
        a = abrufer.hole(aufgabe["url"])
        if not a.ok:
            return False, [], a.fehler, cursor
        if art == "shopify_neueste":
            return True, aus_shopify_json(a.text, basis, quelle)[0], None, cursor
        if art in ("woo_api", "woo_neueste"):
            return True, aus_woo_json(a.text, quelle), None, cursor
        if art == "sitemap":
            k, unter = aus_sitemap(a.text, quelle)
            return True, k, None, ({"unter": unter, "pos": 0} if unter else {})
        return True, aus_html(a.text, basis, quelle), None, cursor
    except (json.JSONDecodeError, ValueError) as e:
        return False, [], f"Antwort nicht lesbar ({type(e).__name__})", cursor
