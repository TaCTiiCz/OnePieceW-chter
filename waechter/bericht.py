"""Erzeugt den Bericht reports/latest.md (im Browser auf GitHub direkt lesbar)."""

from __future__ import annotations

import datetime as dt

from . import modelle as m
from .konfig import Konfig

try:
    from zoneinfo import ZoneInfo
    _BERLIN = ZoneInfo("Europe/Berlin")
except Exception:  # pragma: no cover
    _BERLIN = None

STATUS_SYMBOL = {m.IN_STOCK: "🟢 IN STOCK", m.PREORDER: "🟡 PREORDER", m.WAITLIST: "🟠 WAITLIST",
                 m.SOLD_OUT: "🔴 SOLD OUT", m.UNCLEAR: "⚪ UNCLEAR"}
STATUS_REIHENFOLGE = {s: i for i, s in enumerate((m.IN_STOCK, m.PREORDER, m.WAITLIST, m.SOLD_OUT, m.UNCLEAR))}
EREIGNIS_NAME = {m.RESTOCK: "🟢 Restock", m.NEU_LIEFERBAR: "🟢 Neu lieferbar", m.NEUE_VORBESTELLUNG: "🟡 Neue Vorbestellung",
                 m.PREISRUECKGANG: "🔻 Preisrückgang"}


def _zeit(iso: str | None) -> str:
    if not iso:
        return "–"
    t = dt.datetime.fromisoformat(iso)
    if _BERLIN:
        t = t.astimezone(_BERLIN)
    return t.strftime("%d.%m.%Y %H:%M")


def _euro(cent, waehrung="EUR") -> str:
    if cent is None:
        return "unbekannt"
    s = f"{cent / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €" if waehrung == "EUR" else f"{s} {waehrung or '?'}"


def _esc(text) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def _zeile(eintrag: dict, freigegeben: dict) -> str:
    b = eintrag["letzte"]
    preis = _euro(b["preis_cent"], b["waehrung"]) + ("" if b["waehrung_bestaetigt"] or b["preis_cent"] is None else " ⚠️")
    versand = _euro(b["versand_cent"], b["waehrung"]) if b["versand_cent"] is not None else "❓ unbekannt"
    gesamt = f"**{_euro(b['gesamt_cent'], b['waehrung'])}**" if b["gesamt_cent"] is not None else "❓"
    shop = _esc(b["shop_name"]) + ("" if freigegeben.get(b["shop_id"]) else " ⛔")
    seit = _zeit(eintrag.get("letzter_sicherer_status_seit"))
    gruende = "; ".join(b.get("status_gruende", [])[:2])
    return (f"| {STATUS_SYMBOL.get(b['status'], b['status'])} | {shop} | {preis} | {versand} | {gesamt} | "
            f"{b['sprache']} | {b['typ']} | {b['versiegelt']} | {b['vollstaendig']} | {seit} | "
            f"[{_esc(b['titel'][:60])}]({b['url']}) | {_esc(gruende)} |")


KOPF = ("| Status | Händler | Preis | Versand DE | Gesamt | Sprache | Typ | versiegelt | 24 Packs | Status seit | "
        "Produktseite | Hinweis |\n|---|---|---|---|---|---|---|---|---|---|---|---|")


def _sortiert(eintraege: list[dict]) -> list[dict]:
    return sorted(eintraege, key=lambda e: (STATUS_REIHENFOLGE.get(e["letzte"]["status"], 9),
                                            e["letzte"]["gesamt_cent"] or e["letzte"]["preis_cent"] or 10**9))


def erzeuge_bericht(konfig: Konfig, zustand: dict) -> str:
    lauf = zustand.get("letzter_lauf") or {}
    testdaten = lauf.get("testdaten", False)
    freigegeben = {s.id: s.kaufalarm_freigegeben for s in konfig.shops}
    angebote = [e for e in zustand.get("angebote", {}).values() if e.get("letzte")]
    sicher = [e for e in angebote if e["letzte"]["sicherheit"] == m.SICHER]
    unsicher = [e for e in angebote if e["letzte"]["sicherheit"] != m.SICHER]
    prio = [p.upper() for p in konfig.produkte.get("displays", {}).get("prioritaet", [])]
    z: list[str] = []
    a = z.append

    a("# One-Piece-TCG-Wächter – Bericht\n")
    if testdaten:
        a("> ⚠️ **TESTDATEN – KEINE LIVE-PRÜFUNG.** Dieser Bericht wurde aus gespeicherten Beispieldaten "
          "(`tests/fixtures`) erzeugt. Preise und Bestände sind NICHT aktuell.\n")
    a(f"**Stand:** {_zeit(lauf.get('zeit'))} Uhr (deutsche Zeit) · **Modus:** "
      f"{'Testdaten' if testdaten else 'Live'} · **Telegram:** {_esc(lauf.get('telegram', '–'))}\n")
    a("Keine automatischen Käufe. Ein Status ist nur ein Hinweis – bitte vor dem Kauf immer die Produktseite selbst "
      "öffnen. ⛔ = Händler (noch) nicht für Kaufalarme freigegeben. ⚠️ = Währung nicht auf der Seite bestätigt. "
      "❓ = unbekannt (wird nie als 0 € gezählt).\n")

    kaufbar = [e for e in sicher if e["letzte"]["status"] in m.KAUFBAR]
    fehler_angebote = [e for e in angebote if not e["letzte"]["abruf_ok"]]
    a("## Kurzüberblick\n")
    a(f"- Beobachtete Angebote: **{len(angebote)}** (sicher zugeordnet: {len(sicher)}, unsicher: {len(unsicher)})")
    a(f"- Davon bestellbar (IN STOCK/PREORDER, sicher): **{len(kaufbar)}**")
    a(f"- Ereignisse in diesem Lauf: **{len([e for e in lauf.get('ereignisse', []) if not e.get('unterdrueckt')])}**")
    a(f"- Angebote mit Abruffehler: **{len(fehler_angebote)}**\n")

    a("## Ereignisse dieses Laufs\n")
    erg = lauf.get("ereignisse", [])
    if not erg:
        basis = [s for s, b in lauf.get("shops", {}).items() if b.get("basis_jetzt_erfasst")]
        if basis:
            a(f"_Keine. Erster erfolgreicher Abruf für: {', '.join(basis)} – Ausgangsbasis gespeichert, "
              "deshalb werden bewusst keine Restocks gemeldet._\n")
        else:
            a("_Keine neuen Restocks, Vorbestellungen oder Preisrückgänge._\n")
    else:
        a("| Ereignis | Beschreibung | Telegram | Link |\n|---|---|---|---|")
        for e in erg:
            tg = ("gesendet" if e.get("gemeldet") else ("unterdrückt (Wiederholung)" if e.get("unterdrueckt") else
                  ("Kaufalarm" if e.get("alarm") else f"nur Bericht: {e.get('alarm_grund')}")))
            a(f"| {EREIGNIS_NAME.get(e['typ'], e['typ'])} | {_esc(e['text'])} | {_esc(tg)} | [öffnen]({e['url']}) |")
        a("")

    a(f"## ⭐ Prioritäts-Sets: {', '.join(prio)}\n")
    for code in prio:
        zeilen = _sortiert([e for e in sicher if e["letzte"]["ziel_id"] == f"display-{code}"])
        a(f"### {code} Booster Display (Englisch)\n")
        if zeilen:
            a(KOPF)
            for e in zeilen:
                a(_zeile(e, freigegeben))
            a("")
        else:
            a("_Bei den überwachten Händlern kein sicher zugeordnetes Angebot gefunden._\n")

    a("## Weitere Booster Displays (Englisch)\n")
    weitere = [e for e in sicher if e["letzte"]["kategorie"] == "display" and e["letzte"]["set_code"] not in prio]
    if weitere:
        a(KOPF)
        for e in sorted(weitere, key=lambda e: (e["letzte"]["set_code"] or "", STATUS_REIHENFOLGE.get(e["letzte"]["status"], 9))):
            a(_zeile(e, freigegeben))
        a("")
    else:
        a("_Keine._\n")

    a("## Sleeved Booster (Englisch)\n")
    sl = _sortiert([e for e in sicher if e["letzte"]["kategorie"] == "sleeved"])
    if sl:
        a(KOPF)
        for e in sl:
            a(_zeile(e, freigegeben))
        a("")
    else:
        a(f"_Keine Angebote für {', '.join(konfig.produkte.get('sleeved', {}).get('sets', []))} gefunden._\n")

    a("## Sonderprodukte\n")
    for sp in konfig.produkte.get("sonderprodukte", []):
        a(f"### {sp['anzeige']}\n")
        a(f"Offiziell: {sp.get('offizieller_inhalt', '–')} ([Quelle]({sp.get('offizielle_quelle', '')}))\n")
        if sp.get("identitaet") != "bestaetigt":
            a("> Hinweis: Ein offizielles Produkt namens „2nd Anniversary LIMITED COLLECTION“ wurde nicht gefunden. "
              "Angebote unter diesem Namen stehen nur bei den unsicheren Treffern. Details: `docs/produktidentitaet.md`\n")
        zeilen = _sortiert([e for e in sicher if e["letzte"]["ziel_id"] == sp["id"]])
        if zeilen:
            a(KOPF)
            for e in zeilen:
                a(_zeile(e, freigegeben))
            a("")
        else:
            a("_Kein sicher zugeordnetes Angebot gefunden._\n")

    a("## Unsichere Treffer (kein Kaufalarm)\n")
    a("Hier fehlt eine eindeutige Angabe (z. B. Sprache oder Produkttyp). Bitte selbst prüfen.\n")
    if unsicher:
        a("| Ziel | Status | Händler | Preis | Grund der Unsicherheit | Produktseite |\n|---|---|---|---|---|---|")
        for e in _sortiert(unsicher):
            b = e["letzte"]
            a(f"| {_esc(b['ziel_anzeige'])} | {STATUS_SYMBOL.get(b['status'])} | {_esc(b['shop_name'])} | "
              f"{_euro(b['preis_cent'], b['waehrung'])} | {_esc('; '.join(b.get('treffer_gruende', [])))} | "
              f"[{_esc(b['titel'][:60])}]({b['url']}) |")
        a("")
    else:
        a("_Keine._\n")

    a("## Abruffehler\n")
    shopfehler = [(s, f) for s, b in lauf.get("shops", {}).items() for f in b.get("fehler", [])]
    if not fehler_angebote and not shopfehler:
        a("_Keine._\n")
    else:
        a("Abruffehler lösen nie einen Restock aus. Der letzte sichere Status bleibt gespeichert.\n")
        for s, f in shopfehler:
            a(f"- **{_esc(s)}**: {_esc(f)}")
        for e in fehler_angebote:
            b = e["letzte"]
            a(f"- {_esc(b['shop_name'])}: [{_esc(b['titel'][:60] or b['angebot_id'])}]({b['url']}) – {_esc(b['fehler'])}")
        a("")

    a("## Händler\n")
    a("| Händler | Land | Kaufalarme | Versand nach DE | Produktliste | Gelesen / Kandidaten / Seiten | Ausgangsbasis seit |\n"
      "|---|---|---|---|---|---|---|")
    for s in konfig.shops:
        b = lauf.get("shops", {}).get(s.id, {})
        sz = zustand.get("shops", {}).get(s.id, {})
        versand = (s.versand_de.hinweis if s.versand_de.status == "bekannt" else "❓ unbekannt") + \
            f" ([Quelle]({s.versand_de.quelle}))"
        a(f"| [{_esc(s.name)}]({s.basis_url}) | {s.land} | {'✅ freigegeben' if s.kaufalarm_freigegeben else '⛔ nicht freigegeben'} | "
          f"{_esc(versand)} | {'ok' if b.get('listen_ok') else 'Fehler'} | "
          f"{b.get('produkte_gelesen', 0)} / {b.get('kandidaten', 0)} / {b.get('seiten_geprueft', 0)} | "
          f"{_zeit(sz.get('basis_seit'))} |")
    a("\nDie dokumentierte Händlerprüfung steht in `docs/haendlerpruefung.md`. Shop-Seriosität und Case-Hunting-Risiko "
      "werden nicht bewertet; eine Originalversiegelung beweist keine unselektierte Case-Herkunft.\n")

    aus = lauf.get("ausgeschlossen", [])
    a(f"## Ausgeschlossene One-Piece-Angebote ({len(aus)})\n")
    a("Schutz gegen Verwechslungen: Diese Angebote wurden gefunden, aber bewusst nicht beobachtet.\n")
    if aus:
        zaehler: dict[str, int] = {}
        for x in aus:
            schluessel = x["grund"].split(" (")[0]
            zaehler[schluessel] = zaehler.get(schluessel, 0) + 1
        for g, n in sorted(zaehler.items(), key=lambda kv: -kv[1]):
            a(f"- {n}× {_esc(g)}")
        a("\n<details><summary>Liste anzeigen</summary>\n")
        a("| Händler | Titel | Grund |\n|---|---|---|")
        for x in aus:
            a(f"| {_esc(x['shop'])} | [{_esc(x['titel'][:80])}]({x['url']}) | {_esc(x['grund'])} |")
        a("\n</details>\n")
    return "\n".join(z) + "\n"
