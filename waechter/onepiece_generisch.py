"""One-Piece-Prüfung für Shops OHNE Shopify (WooCommerce, Shopware, JTL, Lightspeed, Magento, …).

Ablauf pro Shop:
  1. Listen- und Suchseiten lesen (Kategorien „One Piece“/Vorbestellung/Neuheiten, Shopsuche, WooCommerce-API).
  2. Aus Links die Produkt-Kandidaten holen und am Titel als OP-Display/Sleeved/Sonderprodukt erkennen.
  3. Jede Produktseite einzeln abrufen und streng auswerten (Schema.org, Kauf-Knopf, Preis).
Alles hier ist nur ein FINDEN. Ein Kaufalarm entsteht wie bei Shopify erst über die gemeinsame Ereignislogik
(nur sichere Treffer, nur freigegebene Händler). Unklare Seiten bleiben UNCLEAR und lösen nie etwas aus.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from typing import Callable, Optional
from urllib.parse import urlparse

from . import modelle as m
from . import seite
from .haendlerdb import links
from .klassifizierung import klassifiziere
from .konfig import Shop
from .zuordnung import ordne_zu

OP_WORT = re.compile(r"one[\s\-_+]?piece|\bop[\s\-_]?\d{1,2}\b", re.I)
RAUSCH_PFADE = ("/blog", "/news", "/pages/", "/collections/", "/category/", "/kategorie/", "/kategorien", "/tag/",
                "/search", "/suche", "/cart", "/warenkorb", "/account", "/login", "/checkout", "/wishlist", "/wp-json")
MAX_LISTEN = 5          # Listenseiten pro Shop und Lauf
MAX_PRODUKTSEITEN = 12  # Produktseiten pro Shop und Lauf (bekannte Angebote zuerst)


def listen_urls_aus_db(h: dict) -> list[str]:
    """Aus den Entdeckungsquellen der Händlerdatenbank die für One Piece brauchbaren Listen-URLs ableiten."""
    erg: list[str] = []

    def add(u: str) -> None:
        if u and u not in erg:
            erg.append(u)

    quellen = h.get("entdeckung") or []
    for e in quellen:
        art, url = e.get("art", ""), e.get("url", "")
        if art in ("kategorie_bandai", "kategorie_vorbestellung", "kategorie_neuheiten"):
            add(url)
    for e in quellen:
        art, url = e.get("art", ""), e.get("url", "")
        if art in ("shopsuche", "woo_api") and re.search(r"naruto", url, re.I):
            add(re.sub(r"naruto", "one+piece+display", url, flags=re.I))
        elif art == "woo_neueste":
            add(url)
    # Vorrang: Kategorien, die „one piece“ schon in der Adresse haben
    erg.sort(key=lambda u: 0 if OP_WORT.search(u) else 1)
    return erg[:MAX_LISTEN]


def _slug(url: str) -> str:
    p = urlparse(url).path.strip("/").rsplit("/", 1)[-1] or urlparse(url).netloc
    return re.sub(r"[^a-z0-9\-_.]+", "-", p.lower()).strip("-")[:80] or "produkt"


def _kandidaten(text: str, url: str, basis: str) -> list[tuple[str, str]]:
    """(Produkt-URL, Titel) aus einer Listenseite (HTML oder WooCommerce-Store-API)."""
    if "wp-json/wc/store" in url:
        try:
            daten = json.loads(text)
        except ValueError:
            return []
        return [(p.get("permalink", ""), re.sub(r"<[^>]+>", "", str(p.get("name", ""))))
                for p in daten if isinstance(p, dict) and p.get("permalink")]
    gesehen: dict[str, str] = {}
    for u, t in links(text, basis):
        u = u.split("#")[0]
        pfad = urlparse(u).path.lower()
        if len(pfad.strip("/")) < 3 or any(x in pfad for x in RAUSCH_PFADE):
            continue
        if not (OP_WORT.search(t) or OP_WORT.search(pfad)):
            continue
        if u not in gesehen or len(t) > len(gesehen[u]):
            gesehen[u] = t
    return list(gesehen.items())


def _beobachtung(shop: Shop, url: str, info: seite.SeitenInfo, k: m.Klassifizierung, t: m.Treffer, vorlage_titel: str,
                 zeitpunkt: str) -> m.Beobachtung:
    gruende = list(info.gruende)
    status = info.status
    if status in m.KAUFBAR:
        if info.preis_cent is None:
            status = m.UNCLEAR; gruende.append("Preis fehlt – Status unklar")
        elif info.anzahlung:
            status = m.UNCLEAR; gruende.append("Anzahlung ohne klaren Gesamtpreis")
        elif info.warteliste and not info.kauf_knopf:
            status = m.UNCLEAR; gruende.append("nur Warteliste/Benachrichtigung")
        elif info.coming_soon and not info.kauf_knopf:
            status = m.UNCLEAR; gruende.append("'Coming soon' ohne Kauf-Knopf")
        elif info.schema_status is None and not info.kauf_knopf:
            status = m.UNCLEAR; gruende.append("nur Text, kein Kauf-Knopf – nicht bestätigt")
    if info.waehrung and info.waehrung == shop.waehrung:
        waehrung, bestaetigt = shop.waehrung, True
    elif info.waehrung:
        waehrung, bestaetigt = info.waehrung, False
        gruende.append(f"Seite zeigt Währung {info.waehrung} statt {shop.waehrung}")
    else:
        waehrung, bestaetigt = shop.waehrung, False
        gruende.append("Währung nicht auf der Seite bestätigt (Konfigurationswert verwendet)")
    return m.Beobachtung(
        angebot_id=f"{shop.id}:{_slug(url)}:0", shop_id=shop.id, shop_name=shop.name, ziel_id=t.ziel_id,
        ziel_anzeige=t.anzeige, kategorie=t.kategorie, sicherheit=t.sicherheit, prioritaet=t.prioritaet,
        titel=info.titel or vorlage_titel, variante="", url=url, zeitpunkt=zeitpunkt, abruf_ok=True, status=status,
        status_gruende=gruende, sprache=k.sprache, typ=k.typ, set_code=k.set_code, versiegelt=k.versiegelt,
        vollstaendig=k.vollstaendig, preis_cent=info.preis_cent, waehrung=waehrung, waehrung_bestaetigt=bestaetigt,
        versand_cent=None, versand_hinweis="Versandkosten nach DE unbekannt", gesamt_cent=None,
        treffer_gruende=list(t.gruende) + ["Seite ohne Shopify-Schnittstelle (HTML-Auswertung)"])


def _fehler(shop: Shop, url: str, vorlage: dict, fehler: str, zeitpunkt: str) -> m.Beobachtung:
    return m.Beobachtung(
        angebot_id=f"{shop.id}:{_slug(url)}:0", shop_id=shop.id, shop_name=shop.name,
        ziel_id=vorlage.get("ziel_id", "?"), ziel_anzeige=vorlage.get("ziel_anzeige", "?"),
        kategorie=vorlage.get("kategorie", "?"), sicherheit=vorlage.get("sicherheit", m.UNSICHER),
        prioritaet=vorlage.get("prioritaet", False), titel=vorlage.get("titel", ""), variante="", url=url,
        zeitpunkt=zeitpunkt, abruf_ok=False, status=m.UNCLEAR, status_gruende=["Abruffehler – kein Statuswechsel abgeleitet"],
        sprache=vorlage.get("sprache", m.UNBEKANNT), typ=vorlage.get("typ", m.TYP_UNBEKANNT), set_code=vorlage.get("set_code"),
        versiegelt=vorlage.get("versiegelt", m.UNBEKANNT), vollstaendig=vorlage.get("vollstaendig", m.UNBEKANNT),
        preis_cent=None, waehrung=None, waehrung_bestaetigt=False, versand_cent=None,
        versand_hinweis="unbekannt (Abruffehler)", gesamt_cent=None, fehler=fehler)


def pruefe_shop_generisch(shop: Shop, konfig, abrufer, zustand: dict, zeitpunkt: str, heute: dt.date,
                          log: Callable[[str], None]) -> tuple[list[m.Beobachtung], list[dict], dict]:
    setnamen = konfig.produkte.get("displays", {}).get("setnamen", {})
    bericht = {"name": shop.name, "listen_ok": False, "fehler": [], "produkte_gelesen": 0, "kandidaten": 0,
               "seiten_geprueft": 0, "generisch": True}
    beobachtungen: list[m.Beobachtung] = []
    ausgeschlossen: list[dict] = []
    pause = abrufer.host_pausiert(shop.host)
    if pause:
        bericht["fehler"].append(f"Shop übersprungen: {pause}")
        return beobachtungen, ausgeschlossen, bericht

    # 1) Listen lesen
    zu_pruefen: dict[str, dict] = {}   # URL -> Vorlage
    for lu in (shop.pruefung.get("listen") or []):
        a = abrufer.hole(lu)
        if not a.ok:
            bericht["fehler"].append(f"{lu}: {a.fehler}")
            continue
        bericht["listen_ok"] = True
        for u, titel in _kandidaten(a.text, lu, shop.basis_url):
            bericht["produkte_gelesen"] += 1
            k = klassifiziere(titel, "", _slug(u), [], "", "", "", setnamen)
            t, grund = ordne_zu(titel, k, konfig.produkte)
            if t is None:
                if k.ist_one_piece:
                    ausgeschlossen.append({"shop": shop.name, "titel": titel, "grund": grund, "url": u})
                continue
            zu_pruefen.setdefault(u, {"titel": titel, "ziel_id": t.ziel_id})

    # 2) Bereits bekannte Angebote immer erneut prüfen (auch wenn sie aus der Liste verschwunden sind)
    bekannt: list[str] = []
    for aid, eintrag in zustand["angebote"].items():
        if aid.startswith(shop.id + ":"):
            u = (eintrag.get("letzte") or {}).get("url")
            if u:
                bekannt.append(u)
                zu_pruefen.setdefault(u, dict(eintrag.get("letzte") or {}))
    reihenfolge = bekannt + [u for u in zu_pruefen if u not in bekannt]
    bericht["kandidaten"] = len(reihenfolge)

    # 3) Produktseiten einzeln prüfen
    for u in reihenfolge[:MAX_PRODUKTSEITEN]:
        a = abrufer.hole(u)
        if not a.ok:
            beobachtungen.append(_fehler(shop, u, zu_pruefen[u], a.fehler or "unbekannter Fehler", zeitpunkt))
            continue
        bericht["seiten_geprueft"] += 1
        info = seite.analysiere(a.text, heute)
        titel = info.titel or zu_pruefen[u].get("titel", "")
        k = klassifiziere(titel, "", _slug(u), [], info.text_auszug, "", "", setnamen)
        t, grund = ordne_zu(titel, k, konfig.produkte)
        if t is None:
            ausgeschlossen.append({"shop": shop.name, "titel": titel, "grund": f"Produktseite: {grund}", "url": u})
            continue
        beobachtungen.append(_beobachtung(shop, u, info, k, t, zu_pruefen[u].get("titel", ""), zeitpunkt))
    log(f"  {shop.name} (HTML): {bericht['produkte_gelesen']} Links, {bericht['kandidaten']} Kandidaten, "
        f"{bericht['seiten_geprueft']} Produktseiten geprüft, {len(bericht['fehler'])} Listenfehler")
    return beobachtungen, ausgeschlossen, bericht
