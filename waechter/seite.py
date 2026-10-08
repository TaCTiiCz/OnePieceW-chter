"""Allgemeine Auswertung einer Produktseite – unabhängig vom Shopsystem.

Quellen (in dieser Reihenfolge des Vertrauens):
1. schema.org-Daten (JSON-LD, Microdata) mit availability / price / priceCurrency
2. OpenGraph-Produktangaben (product:availability, product:price:*)
3. Sichtbarer Text: Bestell-Knopf vs. "ausverkauft", "Coming soon", "Benachrichtigen", "Anzahlung"

Widersprüche führen zu UNCLEAR. Wartelisten, "Coming soon" und Anzahlungen ohne klaren
Gesamtpreis gelten NICHT als bestellbar.
"""

from __future__ import annotations

import datetime as dt
import html as htmlmod
import json
import re
from dataclasses import dataclass, field
from typing import Optional

from . import modelle as m
from .status import finde_daten

_LD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)
_META = re.compile(r'<meta\b([^>]*)>', re.I)
_ATTR = re.compile(r'([a-zA-Z\-:]+)\s*=\s*["\']([^"\']*)["\']')
_TITEL = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S | re.I)
_ITEMPROP = re.compile(r'itemprop=["\'](availability|price|priceCurrency)["\'][^>]*?(?:content|href)=["\']([^"\']+)["\']'
                       r'|(?:content|href)=["\']([^"\']+)["\'][^>]*?itemprop=["\'](availability|price|priceCurrency)["\']', re.I)

KAUF_KNOPF = re.compile(r"in den warenkorb|add to cart|add to basket|jetzt vorbestellen|vorbestellen|pre-?order now|"
                        r"ajouter au panier|pr[ée]commander|a[ñn]adir al carrito|reservar|aggiungi al carrello|preordina|"
                        r"in winkelwagen|l[äa]gg i varukorg|læg i kurv|do koszyka", re.I)
AUSVERKAUFT = re.compile(r"ausverkauft|sold out|out of stock|nicht (mehr )?verfügbar|nicht lieferbar|épuisé|en rupture|agotado|"
                         r"esaurito|uitverkocht|slutsåld|udsolgt|niedostępny|currently unavailable|derzeit nicht", re.I)
COMING_SOON = re.compile(r"coming soon|demnächst|bald verfügbar|bald erhältlich|in kürze|prochainement|bient[oô]t|"
                         r"próximamente|prossimamente|binnenkort|kommer snart|noch nicht bestellbar|not yet available|"
                         r"vorbestellung (startet|ab|beginnt)|pre-?orders? (open|start)", re.I)
WARTELISTE = re.compile(r"benachrichtig|notify me|email me when|warteliste|waitlist|wait list|m'alerter|avísame|avvisami|"
                        r"lista d'attesa|lista de espera|e-mail bei verfügbarkeit", re.I)
ANZAHLUNG = re.compile(r"anzahlung|deposit|acompte|anticipo|aanbetaling|handpenning|zaliczka|restbetrag|restzahlung|"
                       r"balance due|remaining balance|solde à payer", re.I)
VORBESTELLUNG = re.compile(r"vorbestell|pre-?order|precommande|précommande|preventa|pre-?venta|preordin|prenotazion|"
                           r"voorbestel|förbeställ|forudbestil|przedsprzeda", re.I)
STARTTERMIN = re.compile(r"(vorbestell\w*|pre-?orders?|precommandes?|preventa|preordin\w*)[^!?\n]{0,40}?"
                         r"\b(ab|from|starts?|open(s|ing)?|à partir|desde|dal|beginnt|startet)\b[^!?\n]{0,60}", re.I)
VERFUEGBARKEIT = {
    "instock": m.IN_STOCK, "instoreonly": m.IN_STOCK, "onlineonly": m.IN_STOCK, "limitedavailability": m.IN_STOCK,
    "preorder": m.PREORDER, "presale": m.PREORDER,
    "backorder": m.WAITLIST,
    "outofstock": m.SOLD_OUT, "soldout": m.SOLD_OUT, "discontinued": m.SOLD_OUT,
}


@dataclass
class SeitenInfo:
    titel: str = ""
    status: str = m.UNCLEAR
    gruende: list[str] = field(default_factory=list)
    preis_cent: Optional[int] = None
    waehrung: Optional[str] = None
    anzahlung: bool = False
    coming_soon: bool = False
    warteliste: bool = False
    kauf_knopf: bool = False
    termine: list[str] = field(default_factory=list)  # erkannte Vorbestellstarts (ISO-Datum)
    release: Optional[str] = None
    schema_status: Optional[str] = None
    text_auszug: str = ""


def _preis_cent(wert) -> Optional[int]:
    if wert is None:
        return None
    s = str(wert).strip().replace(" ", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        c = int(round(float(re.sub(r"[^0-9.]", "", s)) * 100))
    except ValueError:
        return None
    return c if c > 0 else None


def _angebote(obj, tiefe=0) -> list[dict]:
    if tiefe > 6:
        return []
    erg: list[dict] = []
    if isinstance(obj, list):
        for o in obj:
            erg += _angebote(o, tiefe + 1)
    elif isinstance(obj, dict):
        typ = obj.get("@type")
        typen = typ if isinstance(typ, list) else [typ]
        if any(t in ("Offer", "AggregateOffer") for t in typen) or ("availability" in obj and ("price" in obj or "lowPrice" in obj)):
            erg.append(obj)
        for k in ("offers", "@graph", "hasVariant", "mainEntity", "itemOffered"):
            if k in obj:
                erg += _angebote(obj[k], tiefe + 1)
    return erg


def _produktname(obj) -> Optional[str]:
    if isinstance(obj, list):
        for o in obj:
            n = _produktname(o)
            if n:
                return n
    elif isinstance(obj, dict):
        typ = obj.get("@type")
        if (typ == "Product" or (isinstance(typ, list) and "Product" in typ)) and obj.get("name"):
            return str(obj["name"])
        for k in ("@graph", "mainEntity"):
            if k in obj:
                n = _produktname(obj[k])
                if n:
                    return n
    return None


def sichtbarer_text(seite: str) -> str:
    s = re.sub(r"<script\b.*?</script>|<style\b.*?</style>|<noscript\b.*?</noscript>", " ", seite, flags=re.S | re.I)
    s = re.sub(r"<(nav|footer|header)\b.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", htmlmod.unescape(s)).strip()


def analysiere(seite: str, heute: Optional[dt.date] = None) -> SeitenInfo:
    heute = heute or dt.date.today()
    info = SeitenInfo()
    schema_status: list[str] = []
    preise: list[tuple[int, Optional[str]]] = []

    for block in _LD.findall(seite):
        try:
            daten = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        info.titel = info.titel or (_produktname(daten) or "")
        for o in _angebote(daten):
            v = str(o.get("availability", "")).lower().rsplit("/", 1)[-1]
            if v in VERFUEGBARKEIT:
                schema_status.append(VERFUEGBARKEIT[v])
            p = _preis_cent(o.get("price", o.get("lowPrice")))
            if p:
                preise.append((p, (o.get("priceCurrency") or None)))
    for mt in _META.findall(seite):
        a = {k.lower(): v for k, v in _ATTR.findall(mt)}
        prop = a.get("property", a.get("name", "")).lower()
        if prop in ("product:availability", "og:availability"):
            v = a.get("content", "").lower().replace(" ", "").replace("_", "")
            v = {"oos": "outofstock", "instock": "instock", "pending": "preorder", "available for order": "instock"}.get(v, v)
            if v in VERFUEGBARKEIT:
                schema_status.append(VERFUEGBARKEIT[v])
        elif prop in ("product:price:amount", "og:price:amount") and not preise:
            p = _preis_cent(a.get("content"))
            if p:
                preise.append((p, None))
        elif prop in ("product:price:currency", "og:price:currency"):
            if preise and preise[-1][1] is None:
                preise[-1] = (preise[-1][0], a.get("content", "").upper() or None)
            info.waehrung = info.waehrung or (a.get("content", "").upper() or None)
        elif prop == "og:title" and not info.titel:
            info.titel = htmlmod.unescape(a.get("content", ""))
    for t in _ITEMPROP.findall(seite):
        name, wert = (t[0], t[1]) if t[0] else (t[3], t[2])
        if name.lower() == "availability":
            v = wert.lower().rsplit("/", 1)[-1]
            if v in VERFUEGBARKEIT:
                schema_status.append(VERFUEGBARKEIT[v])
        elif name.lower() == "price" and not preise:
            p = _preis_cent(wert)
            if p:
                preise.append((p, None))
        elif name.lower() == "pricecurrency":
            info.waehrung = info.waehrung or wert.upper()

    if not info.titel:
        mh = _H1.search(seite) or _TITEL.search(seite)
        if mh:
            info.titel = re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", mh.group(1)))).strip()

    text = sichtbarer_text(seite)
    info.text_auszug = text[:3000]
    hauptteil = text[:20000]
    info.kauf_knopf = bool(KAUF_KNOPF.search(hauptteil))
    ausverkauft_text = bool(AUSVERKAUFT.search(hauptteil))
    info.coming_soon = bool(COMING_SOON.search(hauptteil))
    info.warteliste = bool(WARTELISTE.search(hauptteil))
    info.anzahlung = bool(ANZAHLUNG.search(hauptteil))
    vorbestell_text = bool(VORBESTELLUNG.search(hauptteil))

    # Vorbestellstart / Erscheinungsdatum aus dem Text
    for treffer in STARTTERMIN.finditer(hauptteil):
        for d in finde_daten(treffer.group(0)):
            if d >= heute:
                info.termine.append(d.isoformat())
    daten = [d for d in finde_daten(hauptteil) if d >= heute]
    if daten:
        info.release = min(daten).isoformat()

    if preise:
        info.preis_cent, w = preise[0]
        info.waehrung = w or info.waehrung
        if len({p for p, _ in preise}) > 1:
            info.gruende.append("mehrere Preise auf der Seite (Varianten?) – erster Preis verwendet")

    # Status ableiten
    sstatus = sorted(set(schema_status))
    info.schema_status = ",".join(sstatus) if sstatus else None
    if len(sstatus) > 1:
        # mehrere Varianten mit verschiedenem Status: ohne Variantenzuordnung nicht sicher
        info.status, grund = m.UNCLEAR, f"Seite meldet mehrere Verfügbarkeiten ({', '.join(sstatus)})"
    elif sstatus:
        info.status, grund = sstatus[0], f"schema.org-Verfügbarkeit: {sstatus[0]}"
    elif info.kauf_knopf and not ausverkauft_text:
        info.status, grund = (m.PREORDER if vorbestell_text else m.IN_STOCK), "Bestell-Knopf sichtbar (keine strukturierten Daten)"
    elif ausverkauft_text and not info.kauf_knopf:
        info.status, grund = m.SOLD_OUT, "Text: ausverkauft/nicht verfügbar"
    else:
        info.status, grund = m.UNCLEAR, "keine eindeutigen Verfügbarkeitsangaben"
    info.gruende.insert(0, grund)

    # Schutzregeln: was NICHT als bestellbar zählt
    if info.status in m.KAUFBAR:
        if info.coming_soon and not info.kauf_knopf:
            info.status = m.WAITLIST
            info.gruende.append("'Coming soon'/noch nicht bestellbar")
        elif info.warteliste and not info.kauf_knopf:
            info.status = m.WAITLIST
            info.gruende.append("nur Benachrichtigung/Warteliste")
        elif not info.kauf_knopf and sstatus:
            info.gruende.append("kein Bestell-Knopf im Text erkannt (evtl. per JavaScript) – vor Kaufalarm erneut prüfen")
        if info.status == m.IN_STOCK and vorbestell_text:
            info.status = m.PREORDER
            info.gruende.append("Text nennt Vorbestellung")
        if ausverkauft_text and info.kauf_knopf is False:
            info.status = m.UNCLEAR
            info.gruende.append("widersprüchlich: strukturiert bestellbar, Text sagt ausverkauft")
    if info.preis_cent is None and info.status in m.KAUFBAR:
        info.gruende.append("kein Preis gefunden")
    return info
