"""Händlerdatenbank: Kandidaten automatisch prüfen und dauerhaft speichern.

Eingabe:  config/haendler_kandidaten.csv   (Herkunft jedes Kandidaten dokumentiert)
Ausgabe:  data/haendler_db.json            (Prüfergebnis je Händler, mit Belegen und Zeitstempel)

Geprüft wird nur, was öffentlich und laut robots.txt erlaubt ist:
Startseite, robots.txt, Impressum, Versandseite und – je nach Shopsystem – öffentliche
Produkt-Schnittstellen (Shopify /meta.json, WooCommerce Store-API). Suchmaschinentreffer
sind nur die Quelle der Kandidaten, nie ein Nachweis.
"""

from __future__ import annotations

import csv
import datetime as dt
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse, urlencode

from .konfig import PROJEKT

KANDIDATEN = PROJEKT / "config" / "haendler_kandidaten.csv"

EUROPA = {"DE", "AT", "CH", "FR", "ES", "IT", "NL", "BE", "LU", "DK", "SE", "FI", "NO", "PL", "CZ", "SK", "HU", "SI",
          "HR", "PT", "IE", "GR", "RO", "BG", "EE", "LV", "LT", "MT", "CY", "UK", "IS", "LI", "EU"}
NICHT_EU = {"CH", "UK", "NO", "IS", "LI"}

# Dauerhaft ausgeschlossen (Anforderung). TCG Zenith ist bis zu einer Vertrauensprüfung gesperrt.
DAUERHAFT_AUSGESCHLOSSEN = ("tcgdistro", "tcgdistronline")
GESPERRT_BIS_PRUEFUNG = ("tcgzenith", "tcg-zenith")

PLATTFORM_MERKMALE = [
    ("shopify", r"cdn\.shopify\.com|Shopify\.theme|myshopify\.com"),
    ("woocommerce", r"woocommerce|wp-content/plugins/woo"),
    ("shopware", r"shopware|/bundles/storefront/"),
    ("magento", r"Magento|mage/cookies|/static/version\d"),
    ("prestashop", r"prestashop|PrestaShop"),
    ("jtl", r"JTL-Shop|jtl-shop|/templates/NOVA"),
    ("gambio", r"gambio|GXModules"),
    ("oxid", r"oxid|OXID"),
    ("plentymarkets", r"plentymarkets|plenty-"),
    ("lightspeed", r"webshopapp\.com|lightspeed"),
    ("wix", r"wix\.com|wixstatic"),
    ("ecwid", r"ecwid"),
    ("crystalcommerce", r"crystalcommerce"),
    ("odoo", r"odoo"),
]
TCG_WOERTER = ["pokemon", "pokémon", "one piece", "magic: the gathering", "mtg", "yu-gi-oh", "yugioh", "lorcana",
               "dragon ball", "digimon", "gundam", "union arena", "trading card", "sammelkarten", "tcg", "booster",
               "display", "naruto"]
SUCHFELD_NAMEN = ("q", "s", "search", "query", "qs", "keywords", "searchparam", "search_query", "sSearch", "term")
SUCH_VORLAGEN = {
    "woocommerce": "/?s={q}&post_type=product",
    "shopware": "/search?search={q}",
    "magento": "/catalogsearch/result/?q={q}",
    "prestashop": "/index.php?controller=search&s={q}",
    "jtl": "/?qs={q}",
    "gambio": "/advanced_search_result.php?keywords={q}",
    "oxid": "/index.php?cl=search&searchparam={q}",
    "plentymarkets": "/search?query={q}",
    "lightspeed": "/search/{q}/",
}
KATEGORIE_MUSTER = [
    ("naruto", r"naruto"),
    ("vorbestellung", r"vorbestell|pre-?order|precommande|pr[eé]-?commande|preventa|pre-?venta|preordin|prenotazion|reserva|coming-soon|demnaechst|demn%C3%A4chst"),
    ("neuheiten", r"neuheit|neu-eingetroffen|new-arrival|new-release|nouveaut|novedad|novit|nieuw|nyheter|nyheder|uutuu|nowosci|whats-new|neu$"),
    ("bandai", r"bandai|one-piece|onepiece|dragon-ball|gundam|digimon|union-arena"),
]
IMPRESSUM_MUSTER = r"impressum|legal-notice|legal_notice|imprint|mentions-legales|mentions_legales|aviso-legal|note-legali|colofon|informacion-legal|kontakt-impressum"
VERSAND_MUSTER = r"versand|shipping|livraison|envio|env%C3%ADo|spedizion|verzend|frakt|forsendelse|wysyl|toimitus|lieferung"
UST_MUSTER = re.compile(
    r"\b(DE\s?\d{9}|ATU\s?\d{8}|IT\s?\d{11}|FR\s?[0-9A-Z]{2}\s?\d{9}|ES\s?[A-Z0-9]\d{7}[A-Z0-9]|NL\s?\d{9}B\d{2}|"
    r"BE\s?0?\d{9,10}|DK\s?\d{8}|SE\s?\d{12}|PL\s?\d{10}|CHE[-\s]?\d{3}\.\d{3}\.\d{3}|GB\s?\d{9}|IE\s?\d{7}[A-Z]{1,2}|"
    r"PT\s?\d{9}|FI\s?\d{8}|HU\s?\d{8}|EL\s?\d{9}|CZ\s?\d{8,10}|NO\s?\d{9}\s?MVA)\b")
REGISTER_MUSTER = re.compile(r"HR[AB]\s?\d+|FN\s?\d+\s?[a-z]\b|Handelsregister|Firmenbuch|KVK|Kamer van Koophandel|SIRE[NT]|"
                             r"\bRCS\b|\bREA\b|\bCIF\b|\bNIF\b|\bCVR\b|Org\.?\s?nr|Company (number|No)|Companies House|"
                             r"Partita IVA|P\.\s?IVA|USt-?Id|Umsatzsteuer|UID", re.I)
DE_WOERTER = r"deutschland|germany|allemagne|alemania|germania|duitsland|tyskland|niemcy|saksa"


def _jetzt() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def lade_kandidaten(datei: Path = KANDIDATEN) -> list[dict]:
    with open(datei, encoding="utf-8") as f:
        zeilen = list(csv.DictReader(f, delimiter=";"))
    gesehen, kandidaten = set(), []
    for z in zeilen:
        d = (z.get("domain") or "").strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
        if not d or d in gesehen:
            continue
        gesehen.add(d)
        kandidaten.append({"domain": d, "name": (z.get("name") or d).strip(), "land": (z.get("land") or "?").strip().upper(),
                           "quelle": (z.get("quelle") or "").strip()})
    return kandidaten


def _kompakt(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def ausschlussgrund(domain: str, name: str = "") -> Optional[str]:
    k = _kompakt(domain) + " " + _kompakt(name)
    if any(a in k for a in DAUERHAFT_AUSGESCHLOSSEN):
        return "dauerhaft ausgeschlossen (TCG Distro / tcgdistronline.com)"
    if any(_kompakt(a) in k for a in GESPERRT_BIS_PRUEFUNG):
        return "gesperrt bis zur Vertrauensprüfung (TCG Zenith)"
    return None


# --- HTML-Hilfen ------------------------------------------------------------
_A = re.compile(r"<a\b[^>]*?href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
_FORM = re.compile(r"<form\b([^>]*)>(.*?)</form>", re.I | re.S)
_INPUT = re.compile(r"<input\b([^>]*)>", re.I)
_ATTR = re.compile(r"([a-zA-Z\-:]+)\s*=\s*[\"']([^\"']*)[\"']")


def links(seite: str, basis: str) -> list[tuple[str, str]]:
    """Gibt (absolute URL, Linktext) zurück, nur gleiche Domain."""
    host = urlparse(basis).netloc.removeprefix("www.")
    ergebnis = []
    for href, text in _A.findall(seite):
        url = urljoin(basis, html.unescape(href.strip()))
        if urlparse(url).scheme not in ("http", "https"):
            continue
        if urlparse(url).netloc.removeprefix("www.") != host:
            continue
        t = re.sub(r"<[^>]+>", " ", text)
        ergebnis.append((url, re.sub(r"\s+", " ", html.unescape(t)).strip()))
    return ergebnis


def suchformular(seite: str, basis: str, begriff: str) -> Optional[str]:
    for attrs, inhalt in _FORM.findall(seite):
        a = dict((k.lower(), v) for k, v in _ATTR.findall(attrs))
        if a.get("method", "get").lower() != "get":
            continue
        for inp in _INPUT.findall(inhalt):
            ia = dict((k.lower(), v) for k, v in _ATTR.findall(inp))
            name = ia.get("name", "")
            if ia.get("type", "text").lower() in ("search", "text") and name in SUCHFELD_NAMEN:
                ziel = urljoin(basis, html.unescape(a.get("action") or "/"))
                if urlparse(ziel).netloc.removeprefix("www.") != urlparse(basis).netloc.removeprefix("www."):
                    continue
                extra = {}
                for inp2 in _INPUT.findall(inhalt):
                    ia2 = dict((k.lower(), v) for k, v in _ATTR.findall(inp2))
                    if ia2.get("type", "").lower() == "hidden" and ia2.get("name") and len(ia2.get("value", "")) < 40:
                        extra[ia2["name"]] = ia2.get("value", "")
                return ziel + ("&" if "?" in ziel else "?") + urlencode({**extra, name: begriff})
    return None


def plattform_erkennen(seite: str) -> str:
    for name, muster in PLATTFORM_MERKMALE:
        if re.search(muster, seite[:400_000]):
            return name
    return "unbekannt"


def text_von(seite: str) -> str:
    s = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", seite, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s))


def impressum_auswerten(seite: str) -> dict:
    t = text_von(seite)
    ust = UST_MUSTER.search(t)
    reg = REGISTER_MUSTER.search(t)
    form = re.search(r"\b(GmbH|UG \(haftungsbeschränkt\)|e\.\s?K\.|GmbH & Co\. KG|OHG|AG|GbR|S\.L\.U?|S\.r\.l\.s?|SRL|SAS|SARL|"
                     r"B\.V\.|BV|Ltd\.?|Limited|AB|ApS|Oy|sp\. z o\.o\.|s\.r\.o\.|Kft\.|Lda\.?|Einzelunternehmen|Inhaber(in)?)\b", t)
    stelle = ust or reg
    schnipsel = t[max(0, stelle.start() - 80): stelle.end() + 40].strip() if stelle else ""
    return {"ust_id": ust.group(1).replace(" ", "") if ust else None, "register": bool(reg),
            "rechtsform": form.group(1) if form else None, "beleg": schnipsel[:200]}


def versand_auswerten(seite: str) -> dict:
    t = text_von(seite)
    tl = t.lower()
    erg = {"nennt_deutschland": bool(re.search(DE_WOERTER, tl)),
           "nennt_eu": bool(re.search(r"\beu\b|europ|weltweit|worldwide|international", tl)), "betrag_hinweis": None}
    m = re.search(rf"({DE_WOERTER})[^€\d]{{0,80}}?(\d{{1,3}}[,.]\d{{2}})\s?(€|eur)", tl)
    if m:
        erg["betrag_hinweis"] = f"{m.group(2)} € (automatisch gelesen, unbestätigt)"
    return erg


def kategorien_finden(alle_links: list[tuple[str, str]]) -> list[dict]:
    gefunden: dict[str, dict] = {}
    for art, muster in KATEGORIE_MUSTER:
        for url, text in alle_links:
            pfad = urlparse(url).path.lower()
            if "/products/" in pfad or pfad.endswith((".jpg", ".png", ".pdf")):
                continue
            if re.search(muster, pfad) or re.search(muster, text.lower()):
                if url not in gefunden and sum(1 for g in gefunden.values() if g["art"] == art) < 2:
                    gefunden[url] = {"art": art, "url": url.split("#")[0]}
    reihenfolge = {a: i for i, (a, _) in enumerate(KATEGORIE_MUSTER)}
    return sorted(gefunden.values(), key=lambda g: reihenfolge[g["art"]])[:6]


def pruefe_haendler(k: dict, abrufer, vorher: Optional[dict] = None, log: Callable[[str], None] = print) -> dict:
    """Prüft einen Kandidaten. Jeder Befund wird mit Quelle gespeichert."""
    domain = k["domain"]
    e = {"id": _kompakt(domain.split(".")[0]) or _kompakt(domain), "domain": domain, "name": k["name"], "land": k["land"],
         "quelle": k["quelle"], "geprueft_am": _jetzt(), "gruende": [], "entdeckung": [],
         "erstmals_geprueft": (vorher or {}).get("erstmals_geprueft") or _jetzt()}
    grund = ausschlussgrund(domain, k["name"])
    if grund:
        e.update(status="ausgeschlossen", vertrauen="gesperrt", gruende=[grund])
        return e
    basis = f"https://{domain}"
    abrufer.setze_host_regeln(urlparse(basis).netloc, 3.0, 12)
    start = abrufer.hole(basis + "/")
    if not start.ok:
        e.update(status="blockiert" if (start.status in (401, 403) or "Bot-Schutz" in (start.fehler or "")
                                        or "robots" in (start.fehler or "")) else "nicht_erreichbar",
                 vertrauen="ungeprueft", http_status=start.status, gruende=[start.fehler or "Fehler"])
        return e
    final = start.url_final or start.url
    basis = f"{urlparse(final).scheme}://{urlparse(final).netloc}"
    e["basis_url"] = basis
    host = urlparse(basis).netloc
    abrufer.setze_host_regeln(host, 3.0, 12)
    seite = start.text
    e["plattform"] = plattform_erkennen(seite)
    # Sichtbarer Text + Menü-Links + Meta-Beschreibung (viele Startseiten laden Inhalte per JavaScript)
    meta = " ".join(re.findall(r'<meta[^>]+(?:name|property)=["\'](?:description|og:description|og:title)["\'][^>]+content=["\']([^"\']*)',
                               seite[:200_000], re.I))
    linktexte = " ".join(f"{u} {t}" for u, t in links(seite, basis)).replace("-", " ").replace("_", " ")
    tl = (text_von(seite[:600_000]) + " " + meta + " " + linktexte).lower()
    hinweise = sorted({w for w in TCG_WOERTER if w in tl})
    e["tcg_hinweise"] = hinweise
    e["tcg_bezug"] = len(hinweise) >= 3
    e["naruto_erwaehnt"] = "naruto" in tl
    e["tdm_vorbehalt"] = bool(re.search(r'name=["\']tdm-reservation["\'][^>]*content=["\']1', seite, re.I))
    if re.search(r'name=["\']ai-crawl-limit["\']|Verfügbarkeiten NICHT über', seite):
        e["eigene_bot_regeln"] = True
        e["gruende"].append("Shop legt eigene Regeln für automatische Abrufe fest – nur über deren Vorgaben nutzbar")
    alle_links = links(seite, basis)
    robots_info = abrufer.host_zustand.get(host, {}).get("robots", {}).get("text", "")
    e["sitemaps"] = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots_info)[:5] or [basis + "/sitemap.xml"]

    # Impressum
    imp = next((u for u, t in alle_links if re.search(IMPRESSUM_MUSTER, u.lower() + " " + t.lower())), None)
    if not imp and e["plattform"] == "shopify":
        imp = basis + "/policies/legal-notice"
    e["impressum_url"] = imp
    if imp:
        a = abrufer.hole(imp)
        if a.ok:
            e["impressum"] = impressum_auswerten(a.text)
        else:
            e["impressum"] = {"fehler": a.fehler}

    # Versand nach Deutschland
    e["versand_de"], e["versand_de_quelle"] = "unbekannt", ""
    if e["plattform"] == "shopify":
        m = abrufer.hole(basis + "/meta.json")
        if m.ok:
            try:
                meta = m.json()
                laender = meta.get("ships_to_countries") or []
                e["shop_land_meta"] = meta.get("country")
                e["waehrung"] = meta.get("currency")
                if laender:
                    e["versand_de"] = "ja" if "DE" in laender else "nein"
                    e["versand_de_quelle"] = f"{basis}/meta.json (ships_to_countries)"
            except (json.JSONDecodeError, AttributeError):
                pass
        e["entdeckung"].append({"art": "shopify_neueste", "url": basis + "/products.json?limit=100"})
        e["entdeckung"].append({"art": "shopify_katalog", "url": basis + "/products.json?limit=250"})
    if e["plattform"] == "woocommerce":
        api = basis + "/wp-json/wc/store/v1/products?search=naruto&per_page=50"
        w = abrufer.hole(api)
        if w.ok and w.text.lstrip().startswith("["):
            e["entdeckung"].append({"art": "woo_api", "url": api})
            e["entdeckung"].append({"art": "woo_neueste", "url": basis + "/wp-json/wc/store/v1/products?orderby=date&order=desc&per_page=50"})
    if e["versand_de"] == "unbekannt" and k["land"] == "DE":
        e["versand_de"], e["versand_de_quelle"] = "ja", "Inlandshändler (Land DE)"
    versand = next((u for u, t in alle_links if re.search(VERSAND_MUSTER, u.lower() + " " + t.lower())), None)
    if not versand and e["plattform"] == "shopify":
        versand = basis + "/policies/shipping-policy"
    e["versand_url"] = versand
    if versand:
        v = abrufer.hole(versand)
        if v.ok:
            va = versand_auswerten(v.text)
            e["versand_hinweise"] = va
            if e["versand_de"] == "unbekannt":
                if va["nennt_deutschland"]:
                    e["versand_de"], e["versand_de_quelle"] = "vermutlich", f"{versand} nennt Deutschland"
                elif va["nennt_eu"]:
                    e["versand_de"], e["versand_de_quelle"] = "vermutlich", f"{versand} nennt EU/international"

    # Entdeckungswege (alles weitere prüft der Planer laut robots.txt vor jedem Abruf)
    such = suchformular(seite, basis, "naruto")
    if not such and e["plattform"] in SUCH_VORLAGEN:
        such = basis + SUCH_VORLAGEN[e["plattform"]].format(q="naruto")
    if such and e["plattform"] != "shopify":
        e["entdeckung"].append({"art": "shopsuche", "url": such})
    for kat in kategorien_finden(alle_links):
        e["entdeckung"].append({"art": f"kategorie_{kat['art']}", "url": kat["url"]})
    for sm in e["sitemaps"][:2]:
        e["entdeckung"].append({"art": "sitemap", "url": sm})

    # Bewertung
    imp_info = e.get("impressum") or {}
    if k["land"] not in EUROPA:
        e["gruende"].append(f"Land {k['land']} nicht in Europa")
    if not e["tcg_bezug"]:
        e["gruende"].append("kein erkennbares TCG-Sortiment auf der Startseite")
    if e["versand_de"] == "nein":
        e["gruende"].append("liefert laut Shopdaten nicht nach Deutschland")
    if k["land"] in NICHT_EU:
        e["zoll_hinweis"] = "Versand aus Nicht-EU-Land: Zoll/Einfuhrumsatzsteuer möglich"
    geeignet = k["land"] in EUROPA and e["tcg_bezug"] and e["versand_de"] != "nein" and not e.get("eigene_bot_regeln")
    e["status"] = "geeignet" if geeignet else ("eingeschraenkt" if e.get("eigene_bot_regeln") else "ungeeignet")
    vorgeprueft = (bool(imp_info.get("ust_id") or imp_info.get("register")) and e["versand_de"] == "ja")
    e["vertrauen"] = "vorgeprueft" if (geeignet and vorgeprueft) else "ungeprueft"
    if not e["entdeckung"]:
        e["gruende"].append("kein automatischer Entdeckungsweg gefunden (Abdeckungslücke)")
    log(f"  {domain}: {e['status']} / {e['vertrauen']} / {e['plattform']} / Versand DE {e['versand_de']}")
    return e


def pruefe_alle(abrufer, ziel: Path, kandidaten: Optional[list[dict]] = None, nur_neue: bool = False,
                parallel: int = 8, log: Callable[[str], None] = print) -> dict:
    kandidaten = kandidaten if kandidaten is not None else lade_kandidaten()
    db = json.loads(ziel.read_text(encoding="utf-8")) if ziel.exists() else {"version": 1, "haendler": {}}
    alt = {h["domain"]: h for h in db.get("haendler", {}).values()}
    zu_pruefen = [k for k in kandidaten if not (nur_neue and k["domain"] in alt)]
    log(f"Prüfe {len(zu_pruefen)} von {len(kandidaten)} Kandidaten …")

    def eins(k):
        try:
            return pruefe_haendler(k, abrufer, alt.get(k["domain"]), log)
        except Exception as ex:  # ein kaputter Shop darf die Prüfung nicht abbrechen
            return {"id": _kompakt(k["domain"].split(".")[0]), "domain": k["domain"], "name": k["name"], "land": k["land"],
                    "quelle": k["quelle"], "status": "nicht_erreichbar", "vertrauen": "ungeprueft",
                    "gruende": [f"Prüffehler: {type(ex).__name__}"], "geprueft_am": _jetzt(), "entdeckung": []}

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        ergebnisse = list(pool.map(eins, zu_pruefen))
    haendler = {h["domain"]: h for h in alt.values()}
    for e in ergebnisse:
        haendler[e["domain"]] = e
    ids: dict[str, int] = {}
    for h in sorted(haendler.values(), key=lambda h: h["domain"]):
        basis_id = h["id"] or "shop"
        ids[basis_id] = ids.get(basis_id, 0) + 1
        h["id"] = basis_id if ids[basis_id] == 1 else f"{basis_id}{ids[basis_id]}"
    db = {"version": 1, "aktualisiert": _jetzt(), "haendler": {h["id"]: h for h in haendler.values()}}
    zusammenfassung = zaehle(db)
    db["zusammenfassung"] = zusammenfassung
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(json.dumps(db, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return zusammenfassung


def zaehle(db: dict) -> dict:
    hs = list(db.get("haendler", {}).values())
    z: dict = {"kandidaten": len(hs)}
    for feld in ("status", "vertrauen", "plattform", "versand_de", "land"):
        z[feld] = {}
        for h in hs:
            z[feld][h.get(feld, "?")] = z[feld].get(h.get(feld, "?"), 0) + 1
    z["geeignet"] = z["status"].get("geeignet", 0)
    z["mit_entdeckungsweg"] = sum(1 for h in hs if h.get("status") == "geeignet" and h.get("entdeckung"))
    z["naruto_erwaehnt"] = sum(1 for h in hs if h.get("naruto_erwaehnt"))
    return z
