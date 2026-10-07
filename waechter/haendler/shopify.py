"""Adapter für Shopify-Shops.

Ablauf:
1. Produktliste der konfigurierten Kollektion lesen (/collections/<x>/products.json).
   Das dient NUR zum Finden von Kandidaten – ein Listeneintrag ist kein Verfügbarkeitsnachweis.
2. Für jeden Kandidaten die konkrete Produktseite abrufen:
   - /products/<handle>.js  (strukturierte Daten: Varianten, Verfügbarkeit, Preis in Cent, Bestandsführung)
   - /products/<handle>     (sichtbare Seite: Währung, schema.org-Verfügbarkeit)
"""

from __future__ import annotations

import json
import re
from typing import Optional

from ..abruf import Antwort


def kollektion_url(basis: str, kollektion: str, seite: int) -> str:
    return f"{basis}/collections/{kollektion}/products.json?limit=250&page={seite}"


def produkt_js_url(basis: str, handle: str) -> str:
    return f"{basis}/products/{handle}.js"


def produkt_url(basis: str, handle: str) -> str:
    return f"{basis}/products/{handle}"


def liste_produkte(shop, abrufer) -> tuple[list[dict], list[str], bool]:
    """Liest alle Produkte der konfigurierten Kollektionen. Rückgabe: (Produkte, Fehler, vollständig_ok)."""
    produkte: dict[int, dict] = {}
    fehler: list[str] = []
    ok = True
    for kollektion in shop.kollektionen:
        for seite in range(1, shop.max_seiten + 1):
            url = kollektion_url(shop.basis_url, kollektion, seite)
            a = abrufer.hole(url)
            if not a.ok:
                fehler.append(f"Produktliste {kollektion} Seite {seite}: {a.fehler}")
                ok = False
                break
            try:
                daten = a.json()
                liste = daten.get("products", [])
            except (json.JSONDecodeError, AttributeError) as e:
                fehler.append(f"Produktliste {kollektion} Seite {seite}: ungültiges JSON ({e})")
                ok = False
                break
            for p in liste:
                if isinstance(p, dict) and "handle" in p:
                    produkte[p.get("id") or p["handle"]] = p
            if len(liste) < 250:
                break
    return list(produkte.values()), fehler, ok


def hole_produkt(shop, handle: str, abrufer) -> tuple[Optional[dict], dict, list[str]]:
    """Konkrete Produktseite. Rückgabe: (Produktdaten .js, Seiteninfos, Fehler)."""
    fehler: list[str] = []
    a: Antwort = abrufer.hole(produkt_js_url(shop.basis_url, handle))
    js = None
    if a.ok:
        try:
            js = a.json()
            if not isinstance(js, dict) or "variants" not in js:
                fehler.append("Produktdaten ohne Varianten")
                js = None
        except json.JSONDecodeError as e:
            fehler.append(f"Produktdaten ungültig ({e})")
    else:
        fehler.append(f"Produktdaten: {a.fehler}")
    info: dict = {}
    # Sichtbare Seite nur abrufen, wenn etwas als bestellbar gemeldet wird: Dann wird gegengeprüft
    # (Währung, schema.org-Verfügbarkeit). Bei "nicht verfügbar" spart das Anfragen beim Händler.
    if js is not None and any(v.get("available") is True for v in js.get("variants", [])):
        s = abrufer.hole(produkt_url(shop.basis_url, handle))
        if s.ok:
            info = lese_seite(s.text)
        else:
            info = {"seitenfehler": s.fehler}
    return js, info, fehler


_META_WAEHRUNG = re.compile(r'<meta[^>]+property=["\']og:price:currency["\'][^>]+content=["\']([A-Za-z]{3})["\']'
                            r'|<meta[^>]+content=["\']([A-Za-z]{3})["\'][^>]+property=["\']og:price:currency["\']')
_LD_JSON = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)


def _angebote_aus_ld(obj) -> list[dict]:
    gefunden: list[dict] = []
    if isinstance(obj, list):
        for o in obj:
            gefunden.extend(_angebote_aus_ld(o))
    elif isinstance(obj, dict):
        if obj.get("@type") in ("Offer", "AggregateOffer") or ("availability" in obj and "price" in obj):
            gefunden.append(obj)
        for k in ("offers", "@graph", "hasVariant"):
            if k in obj:
                gefunden.extend(_angebote_aus_ld(obj[k]))
    return gefunden


def lese_seite(html: str) -> dict:
    """Liest Währung und schema.org-Angebote aus der sichtbaren Produktseite."""
    info: dict = {"waehrungen": set(), "angebote": []}
    for m in _META_WAEHRUNG.finditer(html):
        info["waehrungen"].add((m.group(1) or m.group(2)).upper())
    for block in _LD_JSON.findall(html):
        try:
            daten = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for o in _angebote_aus_ld(daten):
            if o.get("priceCurrency"):
                info["waehrungen"].add(str(o["priceCurrency"]).upper())
            info["angebote"].append(o)
    info["waehrungen"] = sorted(info["waehrungen"])
    return info


def schema_verfuegbarkeit(info: dict, varianten_id) -> Optional[str]:
    """schema.org-Verfügbarkeit für eine Variante (nur wenn eindeutig zuordenbar)."""
    angebote = info.get("angebote", [])
    passend = [o for o in angebote if str(varianten_id) in str(o.get("url", "")) or str(o.get("sku", "")) == str(varianten_id)]
    if not passend and len(angebote) == 1:
        passend = angebote
    if len(passend) == 1 and passend[0].get("availability"):
        return str(passend[0]["availability"])
    return None


def bestand_verfolgt(variante: dict) -> Optional[bool]:
    if "inventory_management" not in variante:
        return None
    return variante.get("inventory_management") not in (None, "")


def preis_cent_aus_js(variante: dict) -> Optional[int]:
    p = variante.get("price")
    if isinstance(p, (int, float)):
        p = int(p)
        return p if p > 0 else None
    return None


def verkaufsplaene(js: dict) -> list[str]:
    namen = []
    for g in js.get("selling_plan_groups", []) or []:
        namen.append(str(g.get("name", "")))
        for sp in g.get("selling_plans", []) or []:
            namen.append(str(sp.get("name", "")))
    return namen
