"""Wächter-Dojo: schreibt `status.json` für die Pixel-Ansicht (dojo/index.html).

Die Datei enthält NUR Statuswerte, die ohnehin im Dashboard stehen (Stationen, Zeitpunkte, Meldungstexte).
Niemals Zugangsdaten, Token oder Chat-IDs – diese kommen hier nicht vor.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
from pathlib import Path
from typing import Optional

from .konfig import PROJEKT

DOJO_HTML = PROJEKT / "dojo" / "index.html"

# Reihenfolge = Reihenfolge der Tische im Dojo: je Wächter zwei Tische
#   Naruto-Ninja:  Produkte (bekannte Produktseiten) und Entdeckung (neue Seiten, Neuheiten, offizielle Seite, Sitemaps)
#   One-Piece-Seemann: Restock (wieder lieferbar) und Vorbestellung (neu vorbestellbar)
STATIONEN = [
    ("produkt", "Produkte", "naruto"),
    ("entdeckung", "Entdeckung", "naruto"),
    ("op_restock", "Restock", "onepiece"),
    ("op_vorbestellung", "Vorbestellung", "onepiece"),
]
AUFGABENGRUPPE = {"produkt": "produkt", "entdeckung": "entdeckung", "op_restock": "onepiece", "op_vorbestellung": "onepiece"}
ALARM_TYPEN = {"KAUFALARM", "KAUFALARM_ANDERE_SPRACHE"}
OP_ALARM_TYPEN = {"OP_RESTOCK", "OP_VORBESTELLUNG"}  # One-Piece-Prüfung
OP_STATION = {"OP_RESTOCK": "op_restock", "OP_VORBESTELLUNG": "op_vorbestellung"}
ERGEBNIS_ZEILEN = 12
# Pokémon-Wächter (Angler am Teich): diese Ereignisse bedeuten "Fund zum Normalpreis"
POKEMON_FANG_TYPEN = {"KAUFALARM", "KAUFALARM_ANDERE_SPRACHE", "UNGEPRUEFTER_HINWEIS"}


def _zeit(s: Optional[str]) -> Optional[dt.datetime]:
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def _iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat()


def gruppe(art: str) -> str:
    """Aufgabenart -> Gruppe (produkt / onepiece / entdeckung)."""
    if art in ("produkt", "onepiece"):
        return art
    return "entdeckung"


def _kurz(text: str, n: int = 110) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[: n - 1] + "…"


def pokemon_kurz(pz: Optional[dict], jetzt: dt.datetime, *, alarm_stunden: float = 3.0, fehler_ab: int = 3) -> Optional[dict]:
    """Kurzstatus für den Angler am Teich: angelt (prüft), Fang (Normalpreis-Fund) oder Problem."""
    if not pz:
        return None
    from . import modelle as m
    aufgaben = list((pz.get("aufgaben") or {}).values())
    ok_zeiten = [z for z in (_zeit(a.get("zuletzt_ok")) for a in aufgaben) if z]
    zuletzt = max(ok_zeiten) if ok_zeiten else None
    fehler = [a for a in aufgaben if a.get("fehlerserie", 0) >= fehler_ab]
    faenge = []
    for e in pz.get("ereignisse_kurz") or []:
        z = _zeit(e.get("zeit"))
        fenster = dt.timedelta(minutes=15) if e.get("testmodus") else dt.timedelta(hours=alarm_stunden)
        if z and jetzt - z <= fenster and e.get("typ") in POKEMON_FANG_TYPEN:
            faenge.append(e)
    angebote = (pz.get("pokemon") or {}).get("angebote") or {}
    bestellbar = 0
    for a in angebote.values():
        l = a.get("letzte") or {}
        if l.get("passend") and l.get("sicherheit") == m.SICHER and l.get("status") in m.KAUFBAR \
                and a.get("preisstufe") in ("fair", "ok"):
            bestellbar += 1
    if faenge:
        status, detail = "catch", _kurz(faenge[-1].get("text", "Fund zum Normalpreis"), 90)
    elif aufgaben and len(fehler) * 4 >= len(aufgaben):
        status, detail = "error", f"{len(fehler)} von {len(aufgaben)} Aufgaben mit Fehlern"
    elif zuletzt and jetzt - zuletzt <= dt.timedelta(minutes=60):
        status, detail = "fishing", f"angelt nach Normalpreisen · {len(aufgaben)} Aufgaben" + \
            (f", {bestellbar} zum Normalpreis bestellbar" if bestellbar else "")
    else:
        status, detail = "stale", f"{len(aufgaben)} Aufgaben, kein aktueller Lauf"
    return {"status": status, "detail": detail, "last_checked": _iso(zuletzt) if zuletzt else None,
            "aufgaben": len(aufgaben), "bestellbar": bestellbar, "fang": _kurz(faenge[-1].get("text", ""), 120) if faenge else None,
            "test": bool(faenge and faenge[-1].get("testmodus"))}


def erzeuge(zustand: dict, jetzt: dt.datetime, *, alarm_stunden: float = 3.0, aktuell_minuten: float = 30.0,
            fehler_ab: int = 3, pokemon: Optional[dict] = None) -> dict:
    """Baut den Status aus dem gespeicherten Wächter-Zustand (nichts wird geschätzt)."""
    lauf = zustand.get("letzter_lauf") or {}
    lauf_zeit = _zeit(lauf.get("zeit"))
    aufgaben = list((zustand.get("aufgaben") or {}).values())
    ereignisse = zustand.get("ereignisse_kurz") or []
    tag = dt.timedelta(hours=24)

    alarme, op_alarme = [], []
    for e in ereignisse:
        z = _zeit(e.get("zeit"))
        fenster = dt.timedelta(minutes=15) if e.get("testmodus") else dt.timedelta(hours=alarm_stunden)
        if z and jetzt - z <= fenster:
            if e.get("typ") in ALARM_TYPEN:
                alarme.append(e)
            elif e.get("typ") in OP_ALARM_TYPEN:
                op_alarme.append(e)

    gruppen: dict[str, list[dict]] = {g: [] for g in AUFGABENGRUPPE.values()}
    for a in aufgaben:
        gruppen.setdefault(gruppe(a.get("art", "")), []).append(a)

    stationen = []
    for gid, name, agent in STATIONEN:
        ts = gruppen.get(AUFGABENGRUPPE[gid], [])
        if agent == "onepiece" and not ts:
            continue  # One Piece ist optional – ohne Aufgabe keine Tische
        ok_zeiten = [_zeit(t.get("zuletzt_ok")) for t in ts if t.get("zuletzt_ok")]
        ok_zeiten = [z for z in ok_zeiten if z]
        zuletzt = max(ok_zeiten) if ok_zeiten else None
        fehler = [t for t in ts if t.get("fehlerserie", 0) >= fehler_ab]
        im_lauf = bool(lauf_zeit and any(z >= lauf_zeit for z in ok_zeiten))
        if gid == "produkt" and alarme:
            status, detail = "restock", _kurz(alarme[-1].get("text", "Restock gefunden"), 90)
        elif any(OP_STATION[e["typ"]] == gid for e in op_alarme):
            letzte = [e for e in op_alarme if OP_STATION[e["typ"]] == gid][-1]
            status, detail = "restock", _kurz(letzte.get("text", "Fund bei One Piece"), 90)
        elif ts and len(fehler) * 4 >= len(ts):  # mindestens ein Viertel der Aufgaben kaputt
            status, detail = "error", f"{len(fehler)} von {len(ts)} Aufgaben mit Fehlern"
        elif zuletzt and jetzt - zuletzt <= tag:
            status, detail = "ok", f"{len(ts)} Aufgaben" + (f", {len(fehler)} mit Fehlern" if fehler else "")
        else:
            status, detail = "unknown", f"{len(ts)} Aufgaben, noch kein Erfolg in 24 h"
        stationen.append({"id": gid, "name": name, "agent": agent, "status": status, "im_lauf": im_lauf,
                          "last_checked": _iso(zuletzt) if zuletzt else None, "detail": detail})

    push = zustand.get("push") or {}
    push_problem = False
    if push.get("aktiv") and push.get("letzter_fehler"):
        f_zeit = _zeit(str(push["letzter_fehler"]).split(": ", 1)[0]) if ": " in str(push["letzter_fehler"]) else None
        e_zeit = _zeit(push.get("letzter_erfolg"))
        push_problem = bool(f_zeit and (e_zeit is None or f_zeit > e_zeit) and jetzt - f_zeit <= dt.timedelta(hours=6))

    pk = pokemon_kurz(pokemon, jetzt, alarm_stunden=alarm_stunden, fehler_ab=fehler_ab)
    if alarme or op_alarme or (pk and pk["status"] == "catch"):
        state = "alert"
    elif not lauf_zeit or jetzt - lauf_zeit > dt.timedelta(minutes=aktuell_minuten):
        state = "stale"
    elif push_problem:
        state = "error"
    else:
        state = "checking"

    alle = [(e, "") for e in ereignisse[-ERGEBNIS_ZEILEN:]]
    if pokemon:
        alle += [(e, "🎴 ") for e in (pokemon.get("ereignisse_kurz") or [])[-ERGEBNIS_ZEILEN:]]
    alle.sort(key=lambda x: x[0].get("zeit") or "")
    events = []
    for e, vor in reversed(alle[-ERGEBNIS_ZEILEN:]):
        events.append({"time": e.get("zeit"), "text": vor + ("🧪 " if e.get("testmodus") else "") + f"{e.get('typ', '')}: {_kurz(e.get('text', ''))}"})

    return {
        "updated": _iso(jetzt),
        "quelle": os.environ.get("WAECHTER_QUELLE", "github"),   # "server" (eigener Server) oder "github"
        "state": state,
        "current": None,
        "last_run": _iso(lauf_zeit) if lauf_zeit else None,
        "run_seconds": lauf.get("dauer_s"),
        "sites": stationen,
        "events": events,
        "naruto": _naruto_kurz(zustand),
        "pokemon": pk,
        "stats": {
            "haendler": lauf.get("haendler"),
            "aufgaben": len(aufgaben),
            "aufgaben_mit_fehlern": sum(1 for t in aufgaben if t.get("fehlerserie", 0) >= fehler_ab),
            "push_problem": push_problem,
        },
    }


def _naruto_kurz(zustand: dict) -> dict:
    """Kurzfassung für Widget/Dojo: bestellbare Naruto-Angebote (nur sicher zugeordnete) und das günstigste."""
    from . import befehle
    from . import modelle as m
    try:
        bestellbar = [l for l in befehle.naruto_angebote(zustand)
                      if l.get("status") in m.KAUFBAR and l.get("sicherheit") == m.SICHER]
    except Exception:   # Statusdatei darf nie daran scheitern
        return {"bestellbar": 0, "guenstigste": None}
    mit_preis = sorted((l for l in bestellbar if l.get("preis_cent")), key=lambda l: l["preis_cent"])
    g = mit_preis[0] if mit_preis else None
    return {"bestellbar": len(bestellbar),
            "guenstigste": {"titel": _kurz(g.get("titel") or "", 60), "shop": g.get("shop_name") or g.get("shop"),
                            "preis_cent": g.get("preis_cent"), "status": g.get("status"), "url": g.get("url")} if g else None}


def schreibe(zustand: dict, ziel_dir: Path, jetzt: Optional[dt.datetime] = None, pokemon: Optional[dict] = None) -> Path:
    """Schreibt status.json und kopiert die Dojo-Seite daneben."""
    jetzt = jetzt or dt.datetime.now(dt.timezone.utc)
    ziel_dir = Path(ziel_dir)
    ziel_dir.mkdir(parents=True, exist_ok=True)
    datei = ziel_dir / "status.json"
    tmp = datei.with_suffix(".json.tmp")   # atomar: der Server-Abgleich darf nie eine halbe Datei hochladen
    tmp.write_text(json.dumps(erzeuge(zustand, jetzt, pokemon=pokemon), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, datei)
    if DOJO_HTML.exists():
        shutil.copyfile(DOJO_HTML, ziel_dir / "index.html")
    icon = DOJO_HTML.parent / "icon.png"
    if icon.exists():   # App-Icon für "Zum Home-Bildschirm"
        shutil.copyfile(icon, ziel_dir / "icon.png")
    (ziel_dir / ".nojekyll").write_text("", encoding="utf-8")
    return datei
