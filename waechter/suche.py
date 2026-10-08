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


def suche(log: Callable[[str], None] = print, transport: Optional[Callable] = None,
          kandidaten_datei: Path = KANDIDATEN) -> dict:
    schluessel = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    if not schluessel and transport is None:
        log("Händlersuche nicht eingerichtet (Secret BRAVE_SEARCH_API_KEY fehlt) – übersprungen.")
        return {"aktiv": False, "neu": []}
    with open(KONFIG_DIR / "suche.toml", "rb") as f:
        cfg = tomllib.load(f)
    bekannt = {k["domain"].removeprefix("www.") for k in lade_kandidaten(kandidaten_datei)}
    neu: list[tuple[str, str]] = []
    heute = dt.date.today().isoformat()
    for a in cfg["anfragen"]:
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
            log(f"  Suche '{a['q']}' fehlgeschlagen ({type(e).__name__})")
            continue
        urls = [x.get("url", "") for x in (daten.get("web", {}) or {}).get("results", [])]
        for d in domains_aus_ergebnissen(urls, cfg):
            if d not in bekannt and d not in {n for n, _ in neu}:
                neu.append((d, a["q"]))
    if neu:
        with open(kandidaten_datei, "a", encoding="utf-8") as f:
            for d, q in neu:
                f.write(f"{d};{d};?;Brave-Suche {heute}: {q.replace(';', ',')}\n")
    log(f"Händlersuche: {len(neu)} neue Kandidaten")
    return {"aktiv": True, "neu": [d for d, _ in neu]}
