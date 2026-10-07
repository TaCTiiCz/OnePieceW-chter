"""Naruto-Prüflauf: Planer, Produktseiten, Frühhinweise, Kaufalarme.

Ein Lauf arbeitet alle FÄLLIGEN Aufgaben ab (Produktseiten zuerst) und endet dann.
Der Zustand (Aufgaben, Angebote, gesendete Alarme) wird dauerhaft gespeichert, damit
auch kurze, häufige Läufe (z. B. alle 5 Minuten) lückenlos zusammenarbeiten.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import statistics
import threading
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from . import modelle as m
from . import entdeckung, naruto, push, seite
from .haendler import shopify
from .haendlerdb import ausschlussgrund
from .klassifizierung import normalisiere
from .konfig import KONFIG_DIR, PROJEKT, Konfig
from .status import bestimme_status

# Ereignistypen
KAUFALARM = "KAUFALARM"
KAUFALARM_SPRACHE = "KAUFALARM_ANDERE_SPRACHE"
FRUEHHINWEIS = "FRUEHHINWEIS"
UNGEPRUEFT = "UNGEPRUEFTER_HINWEIS"
FEHLER = "FEHLER"
AUSGANGSLAGE = "AUSGANGSLAGE"

PRIO = {"produkt": 1, "offiziell": 2, "schnell": 3, "langsam": 4, "sitemap": 5, "onepiece": 6}
SCHNELL = {"shopify_neueste", "woo_api", "woo_neueste", "shopsuche", "kategorie_naruto", "kategorie_vorbestellung"}
LANGSAM = {"kategorie_neuheiten", "kategorie_bandai", "shopify_katalog"}


def lade_betrieb(datei: Path = KONFIG_DIR / "betrieb.toml") -> dict:
    with open(datei, "rb") as f:
        return tomllib.load(f)


def _iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat()


def _zeit(s: Optional[str]) -> Optional[dt.datetime]:
    return dt.datetime.fromisoformat(s) if s else None


def _hash(s: str, n: int) -> int:
    return int(hashlib.sha1(s.encode()).hexdigest()[:8], 16) % max(1, n)


# ---------------------------------------------------------------------------
# Händler: Datenbank + manuell geprüfte Shops zusammenführen
# ---------------------------------------------------------------------------
@dataclass
class Haendler:
    id: str
    name: str
    domain: str
    basis_url: str
    land: str
    plattform: str
    vertrauen: str  # freigegeben / vorgeprueft / ungeprueft
    entdeckung: list = field(default_factory=list)
    versand_cent: Optional[int] = None  # nur wenn belegt (config/shops.toml)
    versand_staffel: Optional[object] = None
    versand_hinweis: str = "Versand nach DE unbekannt"
    zoll_hinweis: Optional[str] = None

    @property
    def host(self) -> str:
        return urlparse(self.basis_url).netloc


def lade_haendler(konfig: Optional[Konfig], db_datei: Path) -> list[Haendler]:
    db = json.loads(db_datei.read_text(encoding="utf-8")) if db_datei.exists() else {"haendler": {}}
    manuell = {}
    if konfig:
        for s in konfig.shops:
            manuell[urlparse(s.basis_url).netloc.removeprefix("www.")] = s
    erg: dict[str, Haendler] = {}
    for h in db.get("haendler", {}).values():
        if h.get("status") != "geeignet" or ausschlussgrund(h["domain"], h.get("name", "")):
            continue
        basis = h.get("basis_url") or f"https://{h['domain']}"
        dom = urlparse(basis).netloc.removeprefix("www.")
        x = Haendler(id=h["id"], name=h.get("name", dom), domain=dom, basis_url=basis, land=h.get("land", "?"),
                     plattform=h.get("plattform", "unbekannt"), vertrauen=h.get("vertrauen", "ungeprueft"),
                     entdeckung=list(h.get("entdeckung", [])), zoll_hinweis=h.get("zoll_hinweis"))
        hv = (h.get("versand_hinweise") or {}).get("betrag_hinweis")
        x.versand_hinweis = f"Versand DE laut Shopseite ca. {hv}" if hv else "Versand nach DE unbekannt"
        erg[dom] = x
    for dom, s in manuell.items():
        x = erg.get(dom)
        if x is None:
            x = Haendler(id=s.id, name=s.name, domain=dom, basis_url=s.basis_url, land=s.land, plattform=s.plattform,
                         vertrauen="ungeprueft",
                         entdeckung=[{"art": "shopify_neueste", "url": s.basis_url + "/products.json?limit=100"}]
                         if s.plattform == "shopify" else [])
            erg[dom] = x
        if s.kaufalarm_freigegeben:
            x.vertrauen = "freigegeben"
        if s.versand_de.status == "bekannt":
            x.versand_staffel = s.versand_de
            x.versand_hinweis = f"{s.versand_de.hinweis} (belegt {s.versand_de.geprueft_am})"
    return sorted(erg.values(), key=lambda h: h.id)


# ---------------------------------------------------------------------------
# Planer
# ---------------------------------------------------------------------------
def _gruppe(art: str) -> str:
    if art == "produkt":
        return "produkt"
    if art in SCHNELL:
        return "schnell"
    if art in LANGSAM:
        return "langsam"
    if art == "sitemap":
        return "sitemap"
    return art


def intervall_fuer(art: str, betrieb: dict, fokus: bool = False) -> int:
    i = betrieb["intervalle"]
    g = _gruppe(art)
    if g == "produkt":
        return int(i["naruto_produktseite_fokus"] if fokus else i["naruto_produktseite"])
    if g == "schnell":
        return int(min(i["entdeckung_schnell"], 120) if fokus else i["entdeckung_schnell"])
    return int({"langsam": i["entdeckung_langsam"], "sitemap": i["sitemap"], "offiziell": i["offiziell"],
                "onepiece": i["onepiece"]}.get(g, i["entdeckung_langsam"]))


def fokus_shops(zustand: dict, ncfg: dict, betrieb: dict, jetzt: dt.datetime) -> set[str]:
    """Shops mit einem bekannten Vorbestellstart im Fokusfenster ("*" = alle)."""
    vor = dt.timedelta(minutes=betrieb["fokus"]["minuten_vorher"])
    nach = dt.timedelta(hours=betrieb["fokus"]["stunden_nachher"])
    termine = [(t.get("shop") or "*", t["zeitpunkt"]) for t in ncfg.get("termine", [])]
    termine += [(t["shop"], t["zeitpunkt"]) for t in zustand["naruto"].get("termine", {}).values()]
    erg = set()
    for shop, zp in termine:
        zp = str(zp)
        ganztag = len(zp) == 10
        try:
            t = dt.datetime.fromisoformat(zp + ("T00:00:00+00:00" if ganztag else ""))
            if t.tzinfo is None:
                t = t.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
        ende = t + (dt.timedelta(days=1) if ganztag else dt.timedelta()) + nach
        if t - vor <= jetzt <= ende:
            erg.add(shop)
    return erg


def synchronisiere(zustand: dict, haendler: list[Haendler], ncfg: dict, betrieb: dict, jetzt: dt.datetime,
                   onepiece: bool = True) -> None:
    aufg = zustand.setdefault("aufgaben", {})
    soll: dict[str, dict] = {}
    fokus = fokus_shops(zustand, ncfg, betrieb, jetzt)
    for h in haendler:
        for e in h.entdeckung:
            tid = f"{h.id}|{e['art']}|{e['url']}"
            soll[tid] = {"art": e["art"], "shop": h.id, "url": e["url"]}
    for q in ncfg.get("offizielle_quellen", []):
        soll[f"offiziell|{q['id']}"] = {"art": "offiziell", "shop": "offiziell", "url": q["url"], "quelle": q}
    for aid, a in zustand["naruto"]["angebote"].items():
        soll[f"produkt|{aid}"] = {"art": "produkt", "shop": a["shop"], "url": a["url"], "angebot": aid}
    if onepiece:
        soll["onepiece"] = {"art": "onepiece", "shop": "onepiece", "url": ""}
    for tid in list(aufg):
        if tid not in soll:
            del aufg[tid]
    for tid, s in soll.items():
        f = s["shop"] in fokus or "*" in fokus
        intervall = intervall_fuer(s["art"], betrieb, fokus=f)
        if tid not in aufg:
            versatz = 0 if s["art"] in ("produkt", "offiziell") else _hash(tid, intervall)
            aufg[tid] = {**s, "faellig": _iso(jetzt + dt.timedelta(seconds=versatz)), "fehlerserie": 0}
        a = aufg[tid]
        a.update({k: v for k, v in s.items() if k != "quelle"})
        a["intervall"] = intervall
        a["fokus"] = f
        if f and _zeit(a["faellig"]) > jetzt + dt.timedelta(seconds=intervall):
            a["faellig"] = _iso(jetzt)


def faellige(zustand: dict, jetzt: dt.datetime) -> list[tuple[str, dict]]:
    aufg = zustand.get("aufgaben", {})
    f = [(tid, a) for tid, a in aufg.items() if _zeit(a["faellig"]) <= jetzt]
    return sorted(f, key=lambda x: (PRIO.get(_gruppe(x[1]["art"]), 9), x[1]["faellig"]))


def erledigt(a: dict, ok: bool, jetzt: dt.datetime, betrieb: dict, fehler: Optional[str] = None) -> None:
    a["zuletzt_versuch"] = _iso(jetzt)
    if ok:
        a["fehlerserie"] = 0
        a["zuletzt_ok"] = _iso(jetzt)
        a["letzter_fehler"] = None
        a["faellig"] = _iso(jetzt + dt.timedelta(seconds=a["intervall"]))
    else:
        a["fehlerserie"] = a.get("fehlerserie", 0) + 1
        a["letzter_fehler"] = fehler
        # wachsender Abstand: Intervall x 2^(Fehler-1), höchstens max_backoff_minuten
        warte = min(a["intervall"] * (2 ** (a["fehlerserie"] - 1)), betrieb["grenzen"]["max_backoff_minuten"] * 60)
        a["faellig"] = _iso(jetzt + dt.timedelta(seconds=warte))


# ---------------------------------------------------------------------------
# Produktseite prüfen
# ---------------------------------------------------------------------------
@dataclass
class NBeob:
    angebot_id: str
    shop: str
    shop_name: str
    url: str
    titel: str
    zeit: str
    abruf_ok: bool
    status: str = m.UNCLEAR
    gruende: list = field(default_factory=list)
    sprache: str = m.UNBEKANNT
    sprache_offiziell: bool = False
    variante: str = m.TYP_UNBEKANNT
    sicherheit: str = m.UNSICHER
    passend: bool = True
    ausschluss: Optional[str] = None
    preis_cent: Optional[int] = None
    waehrung: Optional[str] = None
    versand_cent: Optional[int] = None
    versand_hinweis: str = ""
    gesamt_cent: Optional[int] = None
    anzahlung: bool = False
    coming_soon: bool = False
    warteliste: bool = False
    kauf_knopf: bool = False
    nur_text: bool = False
    release: Optional[str] = None
    termine: list = field(default_factory=list)
    fehler: Optional[str] = None
    dauer_ms: int = 0
    vertrauen: str = "ungeprueft"


def _angebot_id(shop: str, url: str, variante: Optional[str] = None) -> str:
    return f"{shop}|{url.split('?')[0].split('#')[0]}|{variante or '-'}"


def pruefe_produktseite(h: Haendler, url: str, abrufer, ncfg: dict, heute: dt.date) -> list[NBeob]:
    """Ruft die konkrete Produktseite ab. Fehler werden als Fehler gemeldet, nie als ausverkauft."""
    zeit = _iso(dt.datetime.now(dt.timezone.utc))
    start = time.monotonic()
    basis = NBeob(angebot_id=_angebot_id(h.id, url), shop=h.id, shop_name=h.name, url=url, titel="", zeit=zeit,
                  abruf_ok=False, vertrauen=h.vertrauen)
    pfad = urlparse(url).path
    beobs: list[NBeob] = []
    if h.plattform == "shopify" and "/products/" in pfad:
        handle = pfad.rsplit("/products/", 1)[-1].strip("/")
        js, info, fehler = shopify.hole_produkt(_shop_stub(h), handle, abrufer)
        if js is None:
            basis.fehler = "; ".join(fehler) or "Abruf fehlgeschlagen"
            basis.dauer_ms = int((time.monotonic() - start) * 1000)
            return [basis]
        varianten = js.get("variants", []) or []
        for v in varianten:
            titel = js.get("title", "") + ("" if (v.get("title") or "").lower() == "default title" else f" {v.get('title')}")
            b = NBeob(**{**asdict(basis), "angebot_id": _angebot_id(h.id, url, str(v.get("id")) if len(varianten) > 1 else None),
                         "url": url + (f"?variant={v.get('id')}" if len(varianten) > 1 else ""), "titel": titel,
                         "abruf_ok": True})
            st, gr = bestimme_status(verfuegbar=v.get("available") if isinstance(v.get("available"), bool) else None,
                                     bestand_verfolgt=shopify.bestand_verfolgt(v), titel=js.get("title", ""),
                                     variante=v.get("title", ""), tags=js.get("tags", []) or [],
                                     beschreibung=js.get("description", "") or "",
                                     verkaufsplaene=shopify.verkaufsplaene(js),
                                     schema_verfuegbarkeit=shopify.schema_verfuegbarkeit(info, v.get("id")), heute=heute)
            b.status, b.gruende = st, gr
            b.preis_cent = shopify.preis_cent_aus_js(v)
            w = info.get("waehrungen") or []
            b.waehrung = w[0] if len(w) == 1 else (None if w else "EUR?")
            b.kauf_knopf = v.get("available") is True
            beschr = seite.sichtbarer_text(js.get("description", "") or "")
            b.anzahlung = bool(seite.ANZAHLUNG.search(beschr + " " + titel))
            b.coming_soon = bool(seite.COMING_SOON.search(beschr + " " + titel)) and st not in m.KAUFBAR
            dates = [d for d in seite.finde_daten(beschr) if d >= heute]
            b.release = min(dates).isoformat() if dates else None
            _naruto_einordnen(b, js.get("vendor", ""), tuple(js.get("tags", []) or []), ncfg)
            beobs.append(b)
    else:
        a = abrufer.hole(url)
        if not a.ok:
            basis.fehler = a.fehler or "Abruf fehlgeschlagen"
            basis.dauer_ms = int((time.monotonic() - start) * 1000)
            return [basis]
        si = seite.analysiere(a.text, heute)
        b = NBeob(**{**asdict(basis), "titel": si.titel or url, "abruf_ok": True, "status": si.status,
                     "gruende": si.gruende, "preis_cent": si.preis_cent, "waehrung": si.waehrung, "anzahlung": si.anzahlung,
                     "coming_soon": si.coming_soon, "warteliste": si.warteliste, "kauf_knopf": si.kauf_knopf,
                     "nur_text": si.schema_status is None, "release": si.release, "termine": si.termine})
        _naruto_einordnen(b, "", (), ncfg)
        beobs.append(b)
    dauer = int((time.monotonic() - start) * 1000)
    for b in beobs:
        b.dauer_ms = dauer
        if b.waehrung in ("EUR", "EUR?") and b.preis_cent is not None and h.versand_staffel is not None:
            b.versand_cent = h.versand_staffel.kosten_cent(b.preis_cent)
        b.versand_hinweis = h.versand_hinweis
        if b.versand_cent is not None and b.preis_cent is not None:
            b.gesamt_cent = b.preis_cent + b.versand_cent
    return beobs


def _shop_stub(h: Haendler):
    class S:  # minimale Shop-Angaben für den Shopify-Adapter
        basis_url = h.basis_url
    return S()


def _naruto_einordnen(b: NBeob, hersteller: str, tags: tuple, ncfg: dict) -> None:
    t = naruto.pruefe(b.titel, b.url, tags, hersteller, ncfg)
    b.passend, b.sicherheit, b.sprache, b.sprache_offiziell, b.variante = (t.passend, t.sicherheit, t.sprache,
                                                                           t.sprache_offiziell, t.variante)
    b.ausschluss = t.ausschluss
    b.gruende = list(b.gruende) + t.gruende


# ---------------------------------------------------------------------------
# Ereignisse und Alarme
# ---------------------------------------------------------------------------
def bestellbar_bestaetigt(b: NBeob) -> tuple[bool, str]:
    """Strenge Prüfung für einen KAUFALARM."""
    if not b.abruf_ok:
        return False, "Abruf fehlgeschlagen"
    if b.status not in m.KAUFBAR:
        return False, f"Status {b.status}"
    if b.coming_soon and not b.kauf_knopf:
        return False, "'Coming soon' – noch nicht bestellbar"
    if b.warteliste and not b.kauf_knopf:
        return False, "nur Warteliste/Benachrichtigung"
    if b.anzahlung:
        return False, "Anzahlung ohne klaren Gesamtpreis"
    if b.preis_cent is None:
        return False, "kein Preis auf der Seite"
    if not b.passend:
        return False, b.ausschluss or "kein passendes Produkt"
    return True, "bestellbar"


def _fp(*teile) -> str:
    return hashlib.sha1("|".join(str(t) for t in teile).encode()).hexdigest()[:16]


def _teuer(b: NBeob, zustand: dict, ncfg: dict) -> Optional[str]:
    if b.preis_cent is None:
        return None
    vergleich = [a["letzte"]["preis_cent"] for a in zustand["naruto"]["angebote"].values()
                 if a.get("letzte") and a["letzte"].get("preis_cent") and a["letzte"].get("variante") == b.variante
                 and a["letzte"].get("sprache") == b.sprache and a["letzte"].get("sicherheit") == m.SICHER
                 and a["letzte"].get("status") in m.KAUFBAR]
    grenze_fix = ncfg["alarm"].get("teuer_ab_euro_display", 0)
    if grenze_fix and b.variante == m.DISPLAY and b.preis_cent > grenze_fix * 100:
        return f"über {grenze_fix} € (eigene Grenze)"
    if len(vergleich) >= 3:
        med = statistics.median(vergleich)
        if b.preis_cent > ncfg["alarm"].get("teuer_faktor_median", 1.5) * med:
            return f"deutlich über dem Median vergleichbarer Angebote ({med / 100:.2f} €)".replace(".", ",")
    return None


class Lauf:
    def __init__(self, konfig: Optional[Konfig], abrufer, daten_dir: Path, *, db_datei: Optional[Path] = None,
                 jetzt: Optional[dt.datetime] = None, push_kanal: Optional[push.Kanal] = None,
                 log: Callable[[str], None] = print, ncfg: Optional[dict] = None, betrieb: Optional[dict] = None,
                 onepiece: bool = True, testmodus: bool = False):
        self.konfig = konfig
        self.abrufer = abrufer
        self.dir = Path(daten_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "verlauf").mkdir(exist_ok=True)
        self.db_datei = db_datei or (PROJEKT / "data" / "haendler_db.json")
        self.jetzt = jetzt or dt.datetime.now(dt.timezone.utc)
        self.ncfg = ncfg or naruto.lade_naruto()
        self.betrieb = betrieb or lade_betrieb()
        self.push = push_kanal or push.Kanal.aus_umgebung()
        self.log = log
        self.onepiece = onepiece
        self.testmodus = testmodus
        self.lock = threading.RLock()
        self.zustand = self._lade()
        self.ereignisse: list[dict] = []
        self.verlauf: list[dict] = []
        self.anfragen = 0

    # -- Speicher ---------------------------------------------------------
    def _lade(self) -> dict:
        p = self.dir / "zustand.json"
        z = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        z.setdefault("naruto", {}).setdefault("angebote", {})
        z["naruto"].setdefault("shops", {})
        z["naruto"].setdefault("offiziell", {})
        z["naruto"].setdefault("termine", {})
        z.setdefault("aufgaben", {})
        z.setdefault("hosts", {})
        z.setdefault("meldungen", {})
        z.setdefault("push", {})
        z.setdefault("laeufe", [])
        return z

    def speichern(self) -> None:
        p = self.dir / "zustand.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.zustand, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(p)
        monat = self.jetzt.strftime("%Y-%m")
        for name, zeilen in ((f"verlauf/{monat}.jsonl", self.verlauf), ("ereignisse.jsonl", self.ereignisse)):
            if zeilen:
                with open(self.dir / name, "a", encoding="utf-8") as f:
                    for z in zeilen:
                        f.write(json.dumps(z, ensure_ascii=False, sort_keys=True) + "\n")

    # -- Ereignis anlegen und ggf. sofort senden ---------------------------------
    def _ereignis(self, typ: str, b: Optional[NBeob], text: str, extra: Optional[dict] = None, senden: bool = True) -> dict:
        jetzt = dt.datetime.now(dt.timezone.utc)
        e = {"typ": typ, "zeit": _iso(jetzt), "text": text, "testmodus": self.testmodus, **(extra or {})}
        if b is not None:
            e.update(angebot=b.angebot_id, shop=b.shop, shop_name=b.shop_name, url=b.url, titel=b.titel,
                     status=b.status, sprache=b.sprache, variante=b.variante, preis_cent=b.preis_cent,
                     waehrung=b.waehrung, versand_cent=b.versand_cent, versand_hinweis=b.versand_hinweis,
                     gesamt_cent=b.gesamt_cent, release=b.release, vertrauen=b.vertrauen, pruefzeit=b.zeit,
                     sicherheit=b.sicherheit, sprache_offiziell=b.sprache_offiziell)
        t_erkannt = e.pop("erkannt_monotonic", None)
        fp = _fp(typ, e.get("angebot", text), e.get("status"), e.get("preis_cent"))
        sperre = dt.timedelta(hours=float(self.ncfg["alarm"].get("wiederholsperre_stunden", 12)))
        zuletzt = self.zustand["meldungen"].get(fp)
        e["fingerabdruck"] = fp
        if zuletzt and jetzt - _zeit(zuletzt) < sperre:
            e["unterdrueckt"] = True
            e["gesendet"] = False
        else:
            self.zustand["meldungen"][fp] = _iso(jetzt)
            e["unterdrueckt"] = False
            e["gesendet"] = False
            if senden:
                if t_erkannt is not None:
                    e["erkennung_bis_versand_ms"] = int((time.monotonic() - t_erkannt) * 1000)
                ok, info, ms = self.push.sende(push.formatiere(e, self.ncfg))
                e["gesendet"], e["push_info"], e["push_ms"] = ok, info, ms
                if t_erkannt is not None:
                    e["latenz_ms"] = int((time.monotonic() - t_erkannt) * 1000)
                self._push_status(ok, info)
                if not ok and self.push.aktiv:
                    self.zustand.setdefault("offene_pushes", []).append(e)
        self.ereignisse.append(e)
        self.log(f"  » {typ}: {text} ({'gesendet' if e['gesendet'] else ('unterdrückt' if e['unterdrueckt'] else 'nicht gesendet')})")
        return e

    def _push_status(self, ok: bool, info: str) -> None:
        p = self.zustand["push"]
        p["kanal"] = self.push.name
        p["aktiv"] = self.push.aktiv
        if ok:
            p["letzter_erfolg"] = _iso(dt.datetime.now(dt.timezone.utc))
            p["gesendet_gesamt"] = p.get("gesendet_gesamt", 0) + 1
        elif self.push.aktiv:
            p["letzter_fehler"] = f"{_iso(dt.datetime.now(dt.timezone.utc))}: {info}"

    # -- Beobachtung verarbeiten -------------------------------------------------
    def verarbeite(self, b: NBeob, h: Haendler, quelle: str = "produktseite", erkannt_t: Optional[float] = None) -> None:
        erkannt_t = erkannt_t or time.monotonic()
        with self.lock:
            ang = self.zustand["naruto"]["angebote"]
            neu = b.angebot_id not in ang
            shop_z = self.zustand["naruto"]["shops"].setdefault(h.id, {"basis_erfasst": False})
            alt = ang.get(b.angebot_id) or {"erstmals": b.zeit, "shop": h.id, "url": b.url.split("?")[0] if "?variant" not in b.url else b.url,
                                             "nach_basis": shop_z["basis_erfasst"], "quelle": quelle,
                                             "letzter_sicherer_status": None, "fehlerserie": 0}
            vorher = alt.get("letzter_sicherer_status")
            letzte = alt.get("letzte") or {}
            alt["url"] = b.url
            if not b.abruf_ok:
                alt["fehlerserie"] = alt.get("fehlerserie", 0) + 1
                alt["letzter_fehler"] = b.fehler
                b2 = NBeob(**{**letzte, **{k: getattr(b, k) for k in ("zeit", "abruf_ok", "fehler", "dauer_ms")}}) if letzte else b
                alt["letzte"] = asdict(b2)
                alt["letzte"]["status"] = m.UNCLEAR
                ang[b.angebot_id] = alt
                self._verlauf(b, letzte)
                if alt["fehlerserie"] == self.betrieb["grenzen"]["fehler_push_ab"] and alt.get("letzte", {}).get("sicherheit") == m.SICHER:
                    self._ereignis(FEHLER, b2, f"Abruf fehlgeschlagen ({alt['fehlerserie']}x in Folge) – Status UNBEKANNT, "
                                               f"NICHT ausverkauft: {b2.titel or b.url}")
                return
            alt["fehlerserie"] = 0
            alt["letzter_fehler"] = None
            if not b.passend:
                alt["letzte"] = asdict(b)
                alt["ausgeschlossen"] = b.ausschluss
                ang[b.angebot_id] = alt
                return
            self._verlauf(b, letzte)
            alt["letzte"] = asdict(b)
            ang[b.angebot_id] = alt
            sicher = b.status in m.SICHERE_STATUS
            # erkannte Vorbestellstarts -> Frühhinweis + Fokus
            for t in b.termine:
                key = f"{h.id}|{t}"
                if key not in self.zustand["naruto"]["termine"]:
                    self.zustand["naruto"]["termine"][key] = {"shop": h.id, "zeitpunkt": t,
                                                              "quelle": b.url, "erkannt": b.zeit}
                    if shop_z["basis_erfasst"] or not neu:
                        self._ereignis(FRUEHHINWEIS, b, f"Angekündigter Vorbestellstart {t}: {b.titel} bei {h.name} – "
                                                        "noch NICHT bestellbar, Prüfung wird darauf ausgerichtet")
            if sicher:
                alt["letzter_sicherer_status"] = b.status
                if vorher != b.status:
                    alt["status_seit"] = b.zeit
            erstmals_jetzt = (neu and alt["nach_basis"]) or (not neu and vorher not in m.KAUFBAR and vorher is not None) \
                or (not neu and vorher is None and alt.get("nach_basis"))
            if b.status in m.KAUFBAR and erstmals_jetzt:
                kandidat = True
            else:
                kandidat = False
            if neu and alt["nach_basis"] and not (b.status in m.KAUFBAR):
                via = " (über Sitemap gefunden – Seite evtl. schon länger online)" if quelle == "sitemap" else ""
                self._ereignis(FRUEHHINWEIS if h.vertrauen != "ungeprueft" else UNGEPRUEFT, b,
                               f"Neue passende Produktseite{via}: {b.titel} bei {h.name} – noch NICHT bestellbar ({b.status})")
        if kandidat:
            self._kaufalarm_pruefen(b, h, erkannt_t)

    def _kaufalarm_pruefen(self, b: NBeob, h: Haendler, erkannt_t: float) -> None:
        """Vor jedem Kaufalarm: Produktseite ERNEUT abrufen und streng prüfen."""
        neu = [x for x in pruefe_produktseite(h, b.url.split("?")[0] if "?variant=" not in b.url else b.url.split("?")[0],
                                              self.abrufer, self.ncfg, self.jetzt.date())
               if x.angebot_id == b.angebot_id]
        b2 = neu[0] if neu else NBeob(**{**asdict(b), "abruf_ok": False, "fehler": "Variante beim erneuten Abruf nicht gefunden"})
        ok, grund = bestellbar_bestaetigt(b2)
        with self.lock:
            self._verlauf(b2, asdict(b))
            self.zustand["naruto"]["angebote"][b.angebot_id]["letzte"] = asdict(b2)
            self.zustand["naruto"]["angebote"][b.angebot_id]["zweitpruefung"] = {"zeit": b2.zeit, "ok": ok, "grund": grund}
            extra = {"erkannt_monotonic": erkannt_t, "zweitpruefung": grund, "teuer": _teuer(b2, self.zustand, self.ncfg),
                     "nur_text": b2.nur_text,
                     "spekulativ": not self.ncfg["identitaet"].get("produkte_offiziell_angekuendigt", False)}
            if not ok:
                # nicht als "bestellbar" merken, damit die nächste Prüfung es erneut versucht
                self.zustand["naruto"]["angebote"][b.angebot_id]["letzter_sicherer_status"] = "UNBESTAETIGT"
                if b2.abruf_ok and b2.status in m.KAUFBAR:
                    self._ereignis(FRUEHHINWEIS, b2, f"Seite wirkt bestellbar, aber nicht bestätigt ({grund}): {b2.titel} bei {h.name}",
                                   extra)
                return
            if b2.sicherheit != m.SICHER:
                self.zustand["naruto"]["angebote"][b.angebot_id]["letzter_sicherer_status"] = "UNBESTAETIGT"
                self._ereignis(FRUEHHINWEIS, b2, f"Bestellbar, aber Zuordnung unsicher ({'; '.join(b2.gruende[-2:])}): "
                                                 f"{b2.titel} bei {h.name}", extra)
            elif h.vertrauen == "ungeprueft":
                self._ereignis(UNGEPRUEFT, b2, f"Bestellbar bei UNGEPRÜFTEM Shop {h.name}: {b2.titel} – keine Kaufempfehlung", extra)
            elif b2.sprache == self.ncfg["erkennung"].get("sprache_prioritaet", "EN"):
                self._ereignis(KAUFALARM, b2, f"Vorbestellbar: {b2.titel} bei {h.name}", extra)
            else:
                self._ereignis(KAUFALARM_SPRACHE, b2, f"Vorbestellbar ({b2.sprache}): {b2.titel} bei {h.name}", extra)

    def _verlauf(self, b: NBeob, letzte: dict) -> None:
        felder = ("abruf_ok", "status", "preis_cent", "waehrung", "gesamt_cent", "sprache", "variante", "fehler")
        if not letzte or any(letzte.get(f) != getattr(b, f) for f in felder):
            self.verlauf.append({"zeit": b.zeit, "angebot": b.angebot_id, "shop": b.shop, "status": b.status,
                                 "abruf_ok": b.abruf_ok, "preis_cent": b.preis_cent, "waehrung": b.waehrung,
                                 "gesamt_cent": b.gesamt_cent, "sprache": b.sprache, "variante": b.variante,
                                 "fehler": b.fehler, "quelle": b.url, "testmodus": self.testmodus})

    # -- Aufgaben ausführen ----------------------------------------------------
    def _aufgabe(self, tid: str, a: dict, h: Optional[Haendler]) -> None:
        jetzt = dt.datetime.now(dt.timezone.utc)
        art = a["art"]
        if art == "produkt":
            ang = self.zustand["naruto"]["angebote"].get(a.get("angebot"), {})
            url = ang.get("url", a["url"]).split("?variant=")[0]
            t0 = time.monotonic()
            beobs = pruefe_produktseite(h, url, self.abrufer, self.ncfg, self.jetzt.date())
            for b in beobs:
                self.verarbeite(b, h, erkannt_t=t0)
            ok = all(b.abruf_ok for b in beobs)
            with self.lock:
                erledigt(a, ok, jetzt, self.betrieb, None if ok else beobs[0].fehler)
            return
        if art == "offiziell":
            self._offiziell(tid, a)
            return
        ok, kandidaten, fehler, cursor = entdeckung.fuehre_aus(a, self.abrufer, h.basis_url)
        with self.lock:
            a["cursor"] = cursor
            erledigt(a, ok, jetzt, self.betrieb, fehler)
            a["letzte_kandidaten"] = len(kandidaten)
        for k in kandidaten:
            t = naruto.pruefe(k.titel, k.url, k.tags, k.hersteller, self.ncfg)
            if not t.passend:
                with self.lock:
                    self.zustand["naruto"].setdefault("ausgeschlossen", {})[k.url] = {
                        "titel": k.titel, "grund": t.ausschluss, "shop": h.id, "zeit": _iso(jetzt)}
                continue
            bekannt = any(x.get("url", "").split("?")[0] == k.url.split("?")[0]
                          for x in self.zustand["naruto"]["angebote"].values())
            if bekannt:
                continue
            self.log(f"  + neue Naruto-Seite bei {h.name}: {k.titel} ({k.url})")
            t0 = time.monotonic()
            for b in pruefe_produktseite(h, k.url, self.abrufer, self.ncfg, self.jetzt.date()):
                self.verarbeite(b, h, quelle="sitemap" if a["art"] == "sitemap" else a["art"], erkannt_t=t0)

    def _offiziell(self, tid: str, a: dict) -> None:
        jetzt = dt.datetime.now(dt.timezone.utc)
        ant = self.abrufer.hole(a["url"])
        z = self.zustand["naruto"]["offiziell"].setdefault(tid, {"bekannt": [], "erstmals": _iso(jetzt)})
        if not ant.ok:
            with self.lock:
                erledigt(a, False, jetzt, self.betrieb, ant.fehler)
                z["letzter_fehler"] = ant.fehler
            return
        from .haendlerdb import links as alle_links
        wichtig = ("pre-order", "preorder", "pre order", "release", "booster", "starter", "deck", "price", "msrp",
                   "retailer", "launch", "date", "product")
        if "article-list" in a["url"] or a.get("quelle", {}).get("art") == "newsliste":
            eintraege = [(u, t) for u, t in alle_links(ant.text, a["url"]) if "/news/" in u or "/welcome" in u]
            neu = [(u, t) for u, t in eintraege if u not in z["bekannt"]]
            with self.lock:
                erstlauf = not z["bekannt"]
                z["bekannt"] = sorted(set(z["bekannt"]) | {u for u, _ in eintraege})
                z["letzte_titel"] = [t for _, t in eintraege[:8]]
                for u, t in neu:
                    if erstlauf:
                        continue
                    rel = any(w in t.lower() for w in wichtig)
                    self._ereignis(FRUEHHINWEIS, None, f"Offizielle Naruto-Meldung: {t[:150]}",
                                   {"url": u, "shop_name": "Offizielle Website", "offiziell": True}, senden=rel)
        else:
            text = normalisiere(seite.sichtbarer_text(ant.text))[:50000]
            h = hashlib.sha1(text.encode()).hexdigest()
            with self.lock:
                if z.get("hash") and z["hash"] != h:
                    alt_woerter = set(z.get("woerter", []))
                    neu_woerter = {w for w in wichtig if w in text} - alt_woerter
                    self._ereignis(FRUEHHINWEIS, None, f"Offizielle Seite geändert: {a['url']}" +
                                   (f" (neu: {', '.join(sorted(neu_woerter))})" if neu_woerter else ""),
                                   {"url": a["url"], "shop_name": "Offizielle Website", "offiziell": True},
                                   senden=bool(neu_woerter))
                z["hash"] = h
                z["woerter"] = sorted({w for w in wichtig if w in text})
        with self.lock:
            erledigt(a, True, jetzt, self.betrieb)
            z["zuletzt_ok"] = _iso(jetzt)

    # -- Hauptablauf -------------------------------------------------------------
    def ausfuehren(self, nur_faellige: bool = True) -> dict:
        t_start = time.monotonic()
        haendler = lade_haendler(self.konfig, self.db_datei)
        index = {h.id: h for h in haendler}
        if hasattr(self.abrufer, "host_zustand"):
            self.abrufer.host_zustand = self.zustand["hosts"]
        g = self.betrieb["grenzen"]
        for h in haendler:
            self.abrufer.setze_host_regeln(h.host, float(g["min_abstand_sekunden"]), int(g["max_anfragen_pro_shop_und_lauf"]))
        self.abrufer.setze_host_regeln("www.naruto-cardgame.com", 5.0, 6)
        synchronisiere(self.zustand, haendler, self.ncfg, self.betrieb, self.jetzt, onepiece=self.onepiece)
        f = faellige(self.zustand, self.jetzt) if nur_faellige else list(self.zustand["aufgaben"].items())
        # nach Host gruppieren: pro Host nacheinander, Hosts parallel
        gruppen: dict[str, list] = {}
        onepiece_faellig = False
        for tid, a in f:
            if a["art"] == "onepiece":
                onepiece_faellig = True
                continue
            h = index.get(a["shop"])
            host = urlparse(a["url"]).netloc if a["art"] == "offiziell" else (h.host if h else None)
            if host is None:
                continue
            gruppen.setdefault(host, []).append((tid, a, h))
        self.log(f"Naruto-Lauf: {len(haendler)} Händler, {len(self.zustand['aufgaben'])} Aufgaben, "
                 f"{sum(len(v) for v in gruppen.values())} fällig auf {len(gruppen)} Hosts")
        abgearbeitet = {"produkt": 0, "entdeckung": 0, "offiziell": 0}
        zeitlimit = float(g["max_laufzeit_sekunden"])

        def host_arbeiten(eintraege):
            for tid, a, h in eintraege:
                if time.monotonic() - t_start > zeitlimit:
                    break
                try:
                    self._aufgabe(tid, a, h)
                except Exception as ex:  # eine kaputte Seite darf den Lauf nicht stoppen
                    with self.lock:
                        erledigt(a, False, dt.datetime.now(dt.timezone.utc), self.betrieb, f"Programmfehler: {type(ex).__name__}: {ex}")
                    self.log(f"  ! Fehler bei {tid}: {type(ex).__name__}: {ex}")
                with self.lock:
                    k = "produkt" if a["art"] == "produkt" else ("offiziell" if a["art"] == "offiziell" else "entdeckung")
                    abgearbeitet[k] += 1

        with ThreadPoolExecutor(max_workers=int(g["parallele_shops"])) as pool:
            futs = [pool.submit(host_arbeiten, v) for v in gruppen.values()]
            for fu in as_completed(futs):
                fu.result()

        # Ausgangsbasis je Shop: erfasst, sobald alle schnellen/langsamen Entdeckungswege einmal erfolgreich waren
        neue_basis = []
        for h in haendler:
            sz = self.zustand["naruto"]["shops"].setdefault(h.id, {"basis_erfasst": False})
            wege = [a for a in self.zustand["aufgaben"].values() if a["shop"] == h.id and a["art"] not in ("produkt", "sitemap")]
            if wege and not sz["basis_erfasst"] and all(a.get("zuletzt_ok") for a in wege):
                sz["basis_erfasst"], sz["basis_seit"] = True, _iso(self.jetzt)
                neue_basis.append(h)
            ok_zeiten = [a.get("zuletzt_ok") for a in self.zustand["aufgaben"].values() if a["shop"] == h.id and a.get("zuletzt_ok")]
            sz["letzter_erfolg"] = max(ok_zeiten) if ok_zeiten else sz.get("letzter_erfolg")
        if neue_basis:
            self._ausgangslage(neue_basis)
        self._offene_pushes()
        dauer = time.monotonic() - t_start
        info = {"zeit": _iso(self.jetzt), "dauer_s": round(dauer, 1), "abgearbeitet": abgearbeitet,
                "faellig": sum(len(v) for v in gruppen.values()), "haendler": len(haendler),
                "ereignisse": len(self.ereignisse), "onepiece_faellig": onepiece_faellig, "testmodus": self.testmodus,
                "push": self.push.beschreibung()}
        grenze = self.jetzt - dt.timedelta(days=7)
        kurz = [e for e in self.zustand.get("ereignisse_kurz", []) if _zeit(e["zeit"]) >= grenze]
        kurz += [{k: e.get(k) for k in ("zeit", "typ", "text", "gesendet", "unterdrueckt", "latenz_ms", "url", "testmodus")}
                 for e in self.ereignisse]
        self.zustand["ereignisse_kurz"] = kurz[-200:]
        meld_grenze = self.jetzt - dt.timedelta(days=30)
        self.zustand["meldungen"] = {k: v for k, v in self.zustand["meldungen"].items() if _zeit(v) >= meld_grenze}
        self.zustand["laeufe"] = (self.zustand["laeufe"] + [info])[-300:]
        self.zustand["letzter_lauf"] = info
        self.zustand["push"]["kanal"] = self.push.name
        self.zustand["push"]["aktiv"] = self.push.aktiv
        self.zustand["push"]["beschreibung"] = self.push.beschreibung()
        return info

    def _ausgangslage(self, shops: list[Haendler]) -> None:
        ids = {h.id for h in shops}
        bestellbar = [a["letzte"] for a in self.zustand["naruto"]["angebote"].values()
                      if a["shop"] in ids and a.get("letzte") and a["letzte"].get("passend")
                      and a["letzte"].get("status") in m.KAUFBAR]
        if not bestellbar:
            return
        zeilen = [f"{b['titel']} – {b['shop_name']} ({b['status']}, {push.euro(b.get('preis_cent'))}) {b['url']}"
                  for b in bestellbar[:10]]
        self._ereignis(AUSGANGSLAGE, None, "Ausgangslage: bereits bestellbare Naruto-Angebote (nicht neu):\n" + "\n".join(zeilen),
                       {"url": "", "shop_name": ", ".join(h.name for h in shops[:5])}, senden=True)

    def _offene_pushes(self) -> None:
        offen = self.zustand.get("offene_pushes", [])
        if not offen or not self.push.aktiv:
            self.zustand["offene_pushes"] = [] if not self.push.aktiv else offen
            return
        rest = []
        for e in offen:
            if dt.datetime.now(dt.timezone.utc) - _zeit(e["zeit"]) > dt.timedelta(hours=6):
                continue
            ok, info, _ = self.push.sende(push.formatiere(e, self.ncfg, nachgesendet=True))
            self._push_status(ok, info)
            if not ok:
                rest.append(e)
        self.zustand["offene_pushes"] = rest
