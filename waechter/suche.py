"""Tägliche Händlersuche über die offizielle Brave-Search-API (optional).

Ohne Secret BRAVE_SEARCH_API_KEY passiert nichts – das Dashboard zeigt die Suche dann als
"nicht eingerichtet". Gefundene Domains werden als Kandidaten (mit Herkunft und Datum) an
config/haendler_kandidaten.csv angehängt und anschließend live geprüft.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from .haendlerdb import KANDIDATEN, ausschlussgrund, lade_kandidaten
from .konfig import KONFIG_DIR

API = "https://api.search.brave.com/res/v1/web/search"


def domains_aus_ergebnissen(urls: list[str], cfg: dict) -> list[str]:
    erg = []
    for u in urls:
        host = urlparse(u).netloc.lower().removeprefix("www.")
        if not host or any(i in host for i in cfg["filter"]["ignorieren"]):
            continue
        if not any(host.endswith(e) for e in cfg["filter"]["endungen"]):
            continue
        if ausschlussgrund(host):
            continue
        if host not in erg:
            erg.append(host)
    return erg


ZUSTAND = KANDIDATEN.parent.parent / "data" / "suche_zustand.json"


def alle_anfragen(cfg: dict) -> list[dict]:
    """Feste Anfragen plus Kombinationen aus Produkt x Begriff je Land (Reihenfolge stabil, ohne Doppelte)."""
    erg = [dict(a) for a in cfg.get("anfragen", [])]
    for g in cfg.get("gruppen", []):
        for begriff in g["begriffe"]:
            for produkt in g["produkte"]:
                erg.append({"q": f"{produkt} {begriff}", "land": g.get("land", "ALL")})
    gesehen, eindeutig = set(), []
    for a in erg:
        k = (a["q"], a.get("land"))
        if k not in gesehen:
            gesehen.add(k)
            eindeutig.append(a)
    return eindeutig


def plane_anfragen(cfg: dict, zustand: dict, heute: dt.date) -> tuple[list[dict], dict]:
    """Wählt die Anfragen dieses Laufs: Wochenbudget und Laufgrenze einhalten, reihum weitermachen."""
    jahr, woche, _ = heute.isocalendar()
    kw = f"{jahr}-W{woche:02d}"
    if zustand.get("woche") != kw:
        zustand = {"woche": kw, "verbraucht": 0, "cursor": int(zustand.get("cursor", 0))}
    b = cfg.get("budget", {})
    erlaubt = max(0, min(int(b.get("pro_lauf", 15)), int(b.get("pro_woche", 100)) - int(zustand["verbraucht"])))
    liste = alle_anfragen(cfg)
    if not liste:
        return [], zustand
    start = int(zustand.get("cursor", 0)) % len(liste)
    return [liste[(start + i) % len(liste)] for i in range(min(erlaubt, len(liste)))], zustand


def suche(log: Callable[[str], None] = print, transport: Optional[Callable] = None,
          kandidaten_datei: Path = KANDIDATEN, zustand_datei: Optional[Path] = None,
          heute: Optional[dt.date] = None) -> dict:
    schluessel = (os.environ.get("BRAVE_SEARCH_API_KEY") or os.environ.get("BRAVE_API_KEY") or "").strip()
    if not schluessel and transport is None:
        log("Händlersuche nicht eingerichtet (Secret BRAVE_SEARCH_API_KEY oder BRAVE_API_KEY fehlt) – übersprungen.")
        return {"aktiv": False, "neu": []}
    with open(KONFIG_DIR / "suche.toml", "rb") as f:
        cfg = tomllib.load(f)
    zustand_datei = zustand_datei or ZUSTAND
    try:
        zustand = json.loads(zustand_datei.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        zustand = {}
    anfragen, zustand = plane_anfragen(cfg, zustand, heute or dt.date.today())
    if not anfragen:
        log(f"Händlersuche: Wochenbudget ({cfg.get('budget', {}).get('pro_woche', 100)}) aufgebraucht – bis nächste Woche Pause.")
        return {"aktiv": True, "neu": [], "suchen": 0}
    gesamt = len(alle_anfragen(cfg))
    bekannt = {k["domain"].removeprefix("www.") for k in lade_kandidaten(kandidaten_datei)}
    neu: list[tuple[str, str]] = []
    heute = dt.date.today().isoformat()
    gesendet = 0
    for a in anfragen:
        params = {"q": a["q"], "count": 20}
        if a.get("land") and a["land"] != "ALL":
            params["country"] = a["land"]
        url = API + "?" + urllib.parse.urlencode(params)
        try:
            if transport:
                daten = transport(url)
            else:
                req = urllib.request.Request(url, headers={"Accept": "application/json", "X-Subscription-Token": schluessel})
                with urllib.request.urlopen(req, timeout=20) as r:
                    daten = json.loads(r.read())
        except Exception as e:
            code = getattr(e, "code", None)
            log(f"  Suche '{a['q']}' fehlgeschlagen ({type(e).__name__}{f' {code}' if code else ''})")
            if code in (401, 402, 403, 429):   # Key ungültig / Guthaben leer / Limit: sofort aufhören, nichts mehr verbrauchen
                log("  Abbruch: Brave lehnt weitere Anfragen ab.")
                break
            gesendet += 1
            continue
        gesendet += 1
        urls = [x.get("url", "") for x in (daten.get("web", {}) or {}).get("results", [])]
        for d in domains_aus_ergebnissen(urls, cfg):
            if d not in bekannt and d not in {n for n, _ in neu}:
                neu.append((d, a["q"]))
    if neu:
        with open(kandidaten_datei, "a", encoding="utf-8") as f:
            for d, q in neu:
                f.write(f"{d};{d};?;Brave-Suche {heute}: {q.replace(';', ',')}\n")
    zustand["verbraucht"] = int(zustand.get("verbraucht", 0)) + gesendet
    zustand["cursor"] = (int(zustand.get("cursor", 0)) + gesendet) % max(1, gesamt)
    zustand_datei.parent.mkdir(parents=True, exist_ok=True)
    zustand_datei.write_text(json.dumps(zustand, indent=1), encoding="utf-8")
    log(f"Händlersuche: {gesendet} Suchen ({zustand['verbraucht']} diese Woche), {len(neu)} neue Kandidaten")
    return {"aktiv": True, "neu": [d for d, _ in neu], "suchen": gesendet}
