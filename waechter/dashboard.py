"""Betriebs-Dashboard (Markdown, auf GitHub im Browser lesbar).

Zeigt nur gemessene Werte aus dem gespeicherten Zustand – nichts wird geschätzt.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Optional

from . import modelle as m
from .push import euro, zeit_de

ZEICHEN = {m.IN_STOCK: "🟢 IN STOCK", m.PREORDER: "🟡 PREORDER", m.WAITLIST: "🟠 WAITLIST", m.SOLD_OUT: "🔴 SOLD OUT",
           m.UNCLEAR: "⚪ UNCLEAR"}
VERTRAUEN = {"freigegeben": "✅ geprüft", "vorgeprueft": "☑️ vorgeprüft", "ungeprueft": "❗ ungeprüft"}


def _esc(s) -> str:
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ")


def _alter(iso: Optional[str], jetzt: dt.datetime) -> str:
    if not iso:
        return "nie"
    d = jetzt - dt.datetime.fromisoformat(iso)
    s = int(d.total_seconds())
    if s < 120:
        return f"vor {s} s"
    if s < 7200:
        return f"vor {s // 60} min"
    if s < 172800:
        return f"vor {s // 3600} h"
    return f"vor {s // 86400} Tagen"


def erzeuge(zustand: dict, haendler: list, db: dict, ncfg: dict, betrieb: dict, jetzt: dt.datetime,
            onepiece_bericht: Optional[str] = None) -> str:
    z: list[str] = []
    a = z.append
    lauf = zustand.get("letzter_lauf") or {}
    aufg = zustand.get("aufgaben", {})
    angebote = zustand.get("naruto", {}).get("angebote", {})
    pushz = zustand.get("push", {})
    tag = dt.timedelta(hours=24)

    a("# 🍥 Wächter-Dashboard – NARUTO CARD GAME (Priorität 1) · One Piece (Priorität 2)\n")
    if lauf.get("testmodus"):
        a("> 🧪 **TESTMODUS / SIMULATION** – die folgenden Werte stammen aus einer Simulation, nicht aus echten Shops.\n")
    a(f"**Letzter Lauf:** {zeit_de(lauf.get('zeit'))} ({_alter(lauf.get('zeit'), jetzt)}) · Dauer {lauf.get('dauer_s', '–')} s · "
      f"Ausführung: {betrieb['betrieb']['ausfuehrung']}\n")

    # --- Kennzahlen ---------------------------------------------------------
    ids = {h.id for h in haendler}
    shop_ok_24h = {t["shop"] for t in aufg.values() if t.get("zuletzt_ok") and t["shop"] in ids
                   and jetzt - dt.datetime.fromisoformat(t["zuletzt_ok"]) < tag}
    produkt_aufg = [t for t in aufg.values() if t["art"] == "produkt"]
    produkt_ok = [t for t in produkt_aufg if t.get("zuletzt_ok") and jetzt - dt.datetime.fromisoformat(t["zuletzt_ok"]) < tag]
    dbz = db.get("zusammenfassung", {})
    a("## Betrieb in Zahlen (gemessen)\n")
    a("| Kennzahl | Wert |\n|---|---|")
    a(f"| Händler in der Datenbank (Kandidaten) | {dbz.get('kandidaten', 0)} |")
    a(f"| davon live geprüft & geeignet | **{dbz.get('geeignet', 0)}** (Stand {zeit_de(db.get('aktualisiert'))}) |")
    a(f"| **tatsächlich überwacht** (≥1 erfolgreicher Abruf in 24 h) | **{len(shop_ok_24h)}** von {len(haendler)} |")
    a(f"| Naruto-Produktseiten bekannt / in 24 h erfolgreich geprüft | {len(produkt_aufg)} / {len(produkt_ok)} |")
    a(f"| Prüfaufgaben gesamt / mit Fehlern | {len(aufg)} / {sum(1 for t in aufg.values() if t.get('fehlerserie'))} |")
    a(f"| Pushkanal | {_esc(pushz.get('beschreibung', 'unbekannt'))} |")
    a(f"| Letzter erfolgreicher Push | {zeit_de(pushz.get('letzter_erfolg')) if pushz.get('letzter_erfolg') else 'noch keiner'} |")
    if pushz.get("letzter_fehler"):
        a(f"| Letzter Push-Fehler | {_esc(pushz['letzter_fehler'])} |")
    if pushz.get("letzter_test"):
        t = pushz["letzter_test"]
        a(f"| Letzter Push-Test (Simulation) | {zeit_de(t.get('zeit'))}: {'✅' if t.get('ok') else '❌'} "
          f"Erkennung→Push {t.get('erkennung_bis_push_ms', '?')} ms, Statuswechsel→Push {t.get('wechsel_bis_push_s', '?')} s |")
    a("")

    # --- Produktidentität ------------------------------------------------------
    idn = ncfg["identitaet"]
    a("## Produkt (offiziell geprüft)\n")
    a(f"- **{idn['offizieller_name']}** – {idn['hersteller']} – [{idn['offizielle_website']}]({idn['offizielle_website']})")
    a(f"- Erscheinung: {idn['erscheinung']}")
    a(f"- Offiziell angekündigte Produkte/Preise/Vorbestelltermine: **{'ja' if idn.get('produkte_offiziell_angekuendigt') else 'noch keine'}** "
      "→ jede Vorbestellung vor der Ankündigung ist SPEKULATIV")
    a(f"- Unbestätigt: {ncfg['unbestaetigt']['spracheditionen']}\n")
    off = zustand.get("naruto", {}).get("offiziell", {})
    if off:
        a("| Offizielle Quelle | zuletzt erfolgreich | neueste Einträge |\n|---|---|---|")
        for tid, o in off.items():
            a(f"| {_esc(tid.split('|')[-1])} | {_alter(o.get('zuletzt_ok'), jetzt)} | {_esc('; '.join(o.get('letzte_titel', [])[:3]))} |")
        a("")

    # --- Naruto-Angebote -----------------------------------------------------------
    a("## Naruto-Angebote\n")
    passend = [x for x in angebote.values() if x.get("letzte") and x["letzte"].get("passend")]
    if not passend:
        a("_Noch keine passende Naruto-Produktseite gefunden._\n")
    else:
        reihen = {m.IN_STOCK: 0, m.PREORDER: 0, m.WAITLIST: 1, m.SOLD_OUT: 2, m.UNCLEAR: 3}
        a("| Status | Shop | Vertrauen | Produkt | Sprache | Variante | Preis | Versand DE | Gesamt | Release | geprüft | Link |\n"
          "|---|---|---|---|---|---|---|---|---|---|---|---|")
        for x in sorted(passend, key=lambda x: (reihen.get(x["letzte"]["status"], 9), x["letzte"]["sprache"] != "EN")):
            b = x["letzte"]
            st = ZEICHEN.get(b["status"], b["status"]) + ("" if b.get("abruf_ok") else " (Abruffehler)")
            if b.get("anzahlung"):
                st += " · Anzahlung"
            if b.get("coming_soon"):
                st += " · coming soon"
            a(f"| {st} | {_esc(b['shop_name'])} | {VERTRAUEN.get(b.get('vertrauen'), '?')} | {_esc(b['titel'][:60])} | "
              f"{b['sprache']}{'' if b.get('sprache_offiziell') else ' ❓'} | {b['variante']} | {euro(b.get('preis_cent'), b.get('waehrung'))} | "
              f"{euro(b.get('versand_cent')) if b.get('versand_cent') is not None else '❓'} | "
              f"{euro(b.get('gesamt_cent')) if b.get('gesamt_cent') is not None else '❓'} | {b.get('release') or '❓'} | "
              f"{_alter(b.get('zeit'), jetzt)} | [öffnen]({b['url']}) |")
        a("")

    # --- Ereignisse ------------------------------------------------------------
    a("## Meldungen der letzten 7 Tage\n")
    erg = zustand.get("ereignisse_kurz", [])
    if not erg:
        a("_Keine._\n")
    else:
        a("| Zeit | Art | Meldung | Push | Erkennung→Push |\n|---|---|---|---|---|")
        for e in reversed(erg[-40:]):
            push_txt = "gesendet" if e.get("gesendet") else ("Wiederholung unterdrückt" if e.get("unterdrueckt") else "nicht gesendet")
            a(f"| {zeit_de(e['zeit'])} | {e['typ']}{' 🧪' if e.get('testmodus') else ''} | {_esc(e['text'][:110])} | {push_txt} | "
              f"{str(e.get('latenz_ms')) + ' ms' if e.get('latenz_ms') is not None else '–'} |")
        a("")

    # --- Prüfintervalle ------------------------------------------------------------
    i = betrieb["intervalle"]
    a("## Aktive Prüfintervalle\n")
    a(f"Gestartet wird der Wächter **{betrieb['betrieb']['ausfuehrung']}**"
      + (f" etwa alle **{betrieb['betrieb']['zeitplan_minuten']} Minuten**" if betrieb['betrieb'].get('zeitplan_minuten') else "")
      + ". Kürzere Ziel-Intervalle wirken erst mit einem dauerhaft laufenden Server.\n")
    a("| Prüfung | Ziel-Intervall | Aufgaben |\n|---|---|---|")
    zaehl: dict[str, int] = {}
    for t in aufg.values():
        zaehl[t["art"]] = zaehl.get(t["art"], 0) + 1
    a(f"| Naruto-Produktseiten | {i['naruto_produktseite'] // 60} min (Fokus: {i['naruto_produktseite_fokus']} s) | {zaehl.get('produkt', 0)} |")
    a(f"| Neuheiten/Vorbestell-Kategorien, Shopsuche, Feeds | {i['entdeckung_schnell'] // 60} min | "
      f"{sum(v for k, v in zaehl.items() if k in ('shopify_neueste', 'woo_api', 'woo_neueste', 'shopsuche', 'kategorie_naruto', 'kategorie_vorbestellung'))} |")
    a(f"| weitere Kategorien, Shopify-Gesamtkatalog | {i['entdeckung_langsam'] // 3600} h | "
      f"{sum(v for k, v in zaehl.items() if k in ('kategorie_neuheiten', 'kategorie_bandai', 'shopify_katalog'))} |")
    a(f"| Sitemaps | {i['sitemap'] // 3600} h | {zaehl.get('sitemap', 0)} |")
    a(f"| Offizielle Naruto-Website | {i['offiziell'] // 60} min | {zaehl.get('offiziell', 0)} |")
    a(f"| One Piece (Priorität 2) | {i['onepiece'] // 60} min | {zaehl.get('onepiece', 0)} |")
    fokus = [t for t in aufg.values() if t.get("fokus")]
    termine = zustand.get("naruto", {}).get("termine", {})
    if termine:
        a("\n**Bekannte Vorbestellstarts (Fokus):** " + "; ".join(f"{t['shop']}: {t['zeitpunkt']}" for t in termine.values()))
    a(f"\nAufgaben im Fokusmodus: {len(fokus)}\n")

    # --- Shops -------------------------------------------------------------------
    a("## Händler – letzter erfolgreicher Abruf\n")
    a("| Händler | Land | Vertrauen | System | Prüfwege | letzter Erfolg | Fehler | Basis seit |\n|---|---|---|---|---|---|---|---|")
    nshops = zustand.get("naruto", {}).get("shops", {})
    for h in haendler:
        t = [x for x in aufg.values() if x["shop"] == h.id]
        ok = max((x["zuletzt_ok"] for x in t if x.get("zuletzt_ok")), default=None)
        fehler = [x for x in t if x.get("fehlerserie")]
        ftxt = f"{len(fehler)}: {_esc((fehler[0].get('letzter_fehler') or '')[:50])}" if fehler else "–"
        a(f"| [{_esc(h.name)}]({h.basis_url}) | {h.land} | {VERTRAUEN.get(h.vertrauen, h.vertrauen)} | {h.plattform} | "
          f"{len(t)} | {_alter(ok, jetzt)} | {ftxt} | {zeit_de(nshops.get(h.id, {}).get('basis_seit')) if nshops.get(h.id, {}).get('basis_seit') else '–'} |")
    a("")

    # --- Lücken -------------------------------------------------------------------
    a("## Abdeckungslücken und Fehler\n")
    luecken = []
    for d in db.get("haendler", {}).values():
        if d.get("status") in ("blockiert", "nicht_erreichbar", "eingeschraenkt"):
            luecken.append((d["name"], d["status"], "; ".join(d.get("gruende", []))[:100]))
    nie = [h for h in haendler if not any(x.get("zuletzt_ok") for x in aufg.values() if x["shop"] == h.id)]
    for h in nie:
        luecken.append((h.name, "noch kein erfolgreicher Abruf", ""))
    unbekannt_versand = sum(1 for h in haendler if h.versand_staffel is None)
    a(f"- Händler ohne belegte Versandkosten nach DE: **{unbekannt_versand}** von {len(haendler)} → Gesamtpreis dort „❓“")
    a(f"- Händler ungeprüft (nur „ungeprüfter Hinweis“, kein Kaufalarm): **{sum(1 for h in haendler if h.vertrauen == 'ungeprueft')}**")
    a("- Ausgeschlossen: TCG Distro / tcgdistronline.com (dauerhaft), TCG Zenith (bis zur Vertrauensprüfung)")
    a("- Tägliche automatische Suche nach neuen Händlern: wöchentliche Neuprüfung der Datenbank; neue Kandidaten über "
      "`config/haendler_kandidaten.csv` (siehe README)\n")
    if luecken:
        a("| Händler | Lücke | Details |\n|---|---|---|")
        for n, s, g in luecken[:80]:
            a(f"| {_esc(n)} | {_esc(s)} | {_esc(g)} |")
        a("")
    if onepiece_bericht:
        a(f"## One Piece\n\nSiehe [{onepiece_bericht}]({onepiece_bericht}).\n")
    return "\n".join(z) + "\n"
