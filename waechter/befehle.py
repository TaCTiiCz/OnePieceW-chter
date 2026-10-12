"""Telegram-Befehle: /status, /lieferbar, /hilfe.

Der Wächter fragt bei jedem Durchgang der Schleife (alle 10–30 Sekunden, solange ein Abschnitt läuft) neue Nachrichten
an den Bot ab (getUpdates, ohne Webhook) und antwortet. Es wird NUR der eigene Chat (TELEGRAM_CHAT_ID) bedient; alle
anderen Absender werden ignoriert. Die Position im Nachrichtenstrom steht im Zustand (telegram_befehle.offset), damit
keine Nachricht doppelt beantwortet wird.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from . import modelle as m
from . import telegram

BEFEHLE = [("status", "Läuft der Wächter? Kurzüberblick"),
           ("naruto", "Naruto: alle Vorbestell-Seiten mit Links"),
           ("lieferbar", "One Piece: günstigste lieferbare / vorbestellbare Displays"),
           ("hilfe", "Was der Bot kann")]
_befehle_gemeldet = False      # setMyCommands einmal pro Prozess
MAX_ALTER_ERSTER_ABRUF = 600   # beim allerersten Abruf ältere Nachrichten nicht mehr beantworten (Sekunden)


def _euro(cent: Optional[int]) -> str:
    if cent is None:
        return "?"
    return f"{cent / 100:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _zeit(s: Optional[str]) -> Optional[dt.datetime]:
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def _vor(t: Optional[dt.datetime], jetzt: dt.datetime) -> str:
    if t is None:
        return "unbekannt"
    s = int((jetzt - t).total_seconds())
    if s < 90:
        return f"vor {max(s, 0)} Sek."
    if s < 5400:
        return f"vor {s // 60} Min."
    return f"vor {s // 3600} Std."


def _api(methode: str, params: dict, transport: Optional[Callable]) -> Optional[dict]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return None
    url = f"https://api.telegram.org/bot{token}/{methode}?" + urllib.parse.urlencode(params)
    try:
        if transport:
            status, text = transport(url, None)
        else:
            with urllib.request.urlopen(url, timeout=10) as r:
                status, text = r.status, r.read().decode("utf-8", "replace")
        daten = json.loads(text)
        return daten if status == 200 and daten.get("ok") else None
    except Exception:   # Token nie in Meldungen übernehmen
        return None


# ---------------------------------------------------------------------------------------------- Auswertung

def op_angebote(op_zustand: dict, alarm_shops: Optional[set], jetzt: dt.datetime, grenze_cent: int,
                max_alter_std: float = 6) -> list[dict]:
    """Lieferbare/vorbestellbare EN-Displays bis zur Preisgrenze, nur sicher erkannte, frisch geprüfte Angebote."""
    erg = []
    for a in (op_zustand.get("angebote") or {}).values():
        l = a.get("letzte") or {}
        if l.get("status") not in m.KAUFBAR or l.get("kategorie") != "display" or l.get("sicherheit") != m.SICHER:
            continue
        if l.get("waehrung") != "EUR" or not l.get("preis_cent") or not (4000 <= l["preis_cent"] <= grenze_cent):
            continue
        if alarm_shops is not None and l.get("shop_id") not in alarm_shops:
            continue
        t = _zeit(a.get("zuletzt_geprueft") or l.get("zeitpunkt"))
        if t is None or (jetzt - t).total_seconds() > max_alter_std * 3600:
            continue
        erg.append(l)
    return sorted(erg, key=lambda l: (l["preis_cent"], l.get("ziel_id") or ""))


def _je_set(angebote: list[dict]) -> list[dict]:
    """Pro Set nur das günstigste Angebot."""
    beste: dict[str, dict] = {}
    for l in angebote:
        k = l.get("ziel_id") or l.get("angebot_id")
        if k not in beste or l["preis_cent"] < beste[k]["preis_cent"]:
            beste[k] = l
    return sorted(beste.values(), key=lambda l: l["preis_cent"])


def _zeile(l: dict) -> str:
    name = html.escape((l.get("ziel_anzeige") or l.get("titel") or "?").replace(" Booster Display (EN, 24 Packs)", ""))
    shop = html.escape(l.get("shop_name") or "?")
    return f'{name} – <b>{_euro(l.get("preis_cent"))}</b> – <a href="{html.escape(l.get("url") or "", quote=True)}">{shop}</a>'


STATUS_REIHENFOLGE = {"PREORDER": 0, "IN STOCK": 1, "WAITLIST": 2, "SOLD OUT": 3}
STATUS_WORT = {"PREORDER": "vorbestellbar", "IN STOCK": "lieferbar", "WAITLIST": "Warteliste", "SOLD OUT": "ausverkauft"}


def naruto_angebote(zustand: dict) -> list[dict]:
    """Passende Naruto-Seiten (ohne Verwechslungen), doppelte Sprachversionen derselben Seite zusammengefasst.
    Reihenfolge: vorbestellbar, lieferbar, Warteliste, ausverkauft; darin sichere vor unsicheren, dann nach Preis."""
    gesehen: dict[tuple, dict] = {}
    for a in ((zustand.get("naruto") or {}).get("angebote") or {}).values():
        l = a.get("letzte") or {}
        if not l.get("passend") or l.get("ausschluss"):
            continue
        k = (l.get("shop"), (l.get("titel") or "").lower(), l.get("preis_cent"), l.get("status"))
        if k not in gesehen:
            gesehen[k] = l
    return sorted(gesehen.values(), key=lambda l: (STATUS_REIHENFOLGE.get(l.get("status"), 9),
                                                    l.get("sicherheit") != m.SICHER, l.get("preis_cent") or 10 ** 9))


def naruto_zaehler(zustand: dict) -> dict:
    z = {"PREORDER": 0, "IN STOCK": 0, "SOLD OUT": 0, "sonst": 0}
    for l in naruto_angebote(zustand):
        if l.get("sicherheit") == m.SICHER:
            z[l.get("status") if l.get("status") in z else "sonst"] += 1
    return z


def _naruto_zeile(l: dict, mit_status: bool = False) -> str:
    titel = (l.get("titel") or "?")
    for weg in ("Naruto Card Game", "NARUTO CARD GAME", "Naruto TCG", " - ", " – ", " — "):
        titel = titel.replace(weg, " ")
    titel = html.escape(" ".join(titel.split())[:48])
    preis = _euro(l.get("preis_cent")) if l.get("preis_cent") else "Preis ?"
    shop = html.escape(l.get("shop_name") or l.get("shop") or "?")
    vorsatz = f"{STATUS_WORT.get(l.get('status'), l.get('status') or '?')}: " if mit_status else ""
    return f'{vorsatz}<a href="{html.escape(l.get("url") or "", quote=True)}">{shop}</a> – {titel} – <b>{preis}</b>'


def status_text(zustand: dict, op_zustand: dict, alarm_shops: Optional[set], jetzt: dt.datetime,
                grenze_cent: int = 25000) -> str:
    aufgaben = zustand.get("aufgaben") or {}
    mit_fehler = sum(1 for a in aufgaben.values() if a.get("letzter_fehler"))
    letzte = max((t for t in (_zeit(a.get("zuletzt_versuch")) for a in aufgaben.values()) if t), default=None)
    op_zeit = max((t for t in (_zeit(s.get("zuletzt_geprueft")) for s in (op_zustand.get("shops") or {}).values()) if t),
                  default=None)
    frisch = letzte is not None and (jetzt - letzte).total_seconds() < 1200
    quelle = os.environ.get("WAECHTER_QUELLE", "github")
    nz = naruto_zaehler(zustand)
    angebote = op_angebote(op_zustand, alarm_shops, jetzt, grenze_cent)
    lieferbar = [l for l in angebote if l["status"] == m.IN_STOCK]
    vor = [l for l in angebote if l["status"] == m.PREORDER]
    op_anzahl = len(op_zustand.get("angebote") or {})
    z = [f"{'🟢' if frisch else '🟠'} <b>TCG-Wächter {'läuft' if frisch else 'meldet sich verzögert'}</b>",
         f"Letzte Prüfung: {_vor(letzte, jetzt)} ({'eigener Server' if quelle == 'server' else 'GitHub'})",
         f"Prüfaufgaben: {len(aufgaben)} (davon {mit_fehler} mit Fehler, meist Seite weg oder gesperrt)",
         "",
         "<b>Naruto</b> (Bandai, Release Sommer 2027)",
         f"Seiten: {nz['PREORDER']} vorbestellbar · {nz['IN STOCK']} lieferbar · {nz['SOLD OUT']} ausverkauft"]
    sicher = [l for l in naruto_angebote(zustand) if l.get("sicherheit") == m.SICHER]
    offen = [l for l in sicher if l.get("status") in ("PREORDER", "IN STOCK")]
    z += [f"• {_naruto_zeile(l, mit_status=True)}" for l in offen[:6]]
    zu = sorted({l.get("shop_name") or l.get("shop") or "?" for l in sicher if l.get("status") == "SOLD OUT"})
    if zu:
        z.append(f"Ausverkauft (wird weiter beobachtet): {html.escape(', '.join(zu))}")
    z += ["",
         "<b>One Piece</b> (EN-Displays)",
         f"{op_anzahl} Angebote beobachtet · letzter Durchlauf {_vor(op_zeit, jetzt)}",
         f"Bis {_euro(grenze_cent)} bei geprüften Händlern: {len(lieferbar)} lieferbar, {len(vor)} vorbestellbar"]
    top = _je_set(lieferbar)[:5]
    if top:
        z += ["", "<b>Günstigste lieferbare Displays</b>"] + [f"{i}. {_zeile(l)}" for i, l in enumerate(top, 1)]
    z += ["", "/naruto – alle Naruto-Seiten · /lieferbar – One-Piece-Liste · /hilfe"]
    return "\n".join(z)


def lieferbar_text(op_zustand: dict, alarm_shops: Optional[set], jetzt: dt.datetime, grenze_cent: int = 25000) -> str:
    angebote = op_angebote(op_zustand, alarm_shops, jetzt, grenze_cent)
    lieferbar = _je_set([l for l in angebote if l["status"] == m.IN_STOCK])
    vor = _je_set([l for l in angebote if l["status"] == m.PREORDER])
    z = [f"<b>One Piece EN-Displays bis {_euro(grenze_cent)}</b> (günstigstes Angebot je Set, geprüfte Händler)"]
    z += ["", "<b>🟢 Lieferbar</b>"] + ([_zeile(l) for l in lieferbar[:20]] or ["– nichts unter der Grenze –"])
    z += ["", "<b>🟡 Vorbestellbar</b>"] + ([_zeile(l) for l in vor[:15]] or ["– nichts unter der Grenze –"])
    z += ["", "<i>Stand der letzten Prüfung, Preise ohne Versand. Vor dem Kauf Seite prüfen.</i>"]
    return "\n".join(z)


def naruto_text(zustand: dict) -> str:
    alle = naruto_angebote(zustand)
    sicher = [l for l in alle if l.get("sicherheit") == m.SICHER]
    unsicher = [l for l in alle if l.get("sicherheit") != m.SICHER]
    z = ["<b>Naruto Card Game (Bandai) – beobachtete Seiten</b>", "Release laut Bandai: Sommer 2027"]
    for status, kopf in (("PREORDER", "🟡 Vorbestellbar"), ("IN STOCK", "🟢 Lieferbar"),
                         ("WAITLIST", "🔔 Warteliste"), ("SOLD OUT", "⚪ Ausverkauft – Seite wird weiter beobachtet")):
        teil = [l for l in sicher if l.get("status") == status]
        if teil:
            z += ["", f"<b>{kopf}</b>"] + [_naruto_zeile(l) for l in teil[:15]]
    if not sicher:
        z += ["", "Noch keine sicher erkannte Naruto-Seite."]
    if unsicher:
        z += ["", f"<b>❔ Unsichere Treffer</b> (ungeprüfter Händler oder Zuordnung unklar, kein Kaufalarm)"]
        z += [_naruto_zeile(l, mit_status=True) for l in unsicher[:8]]
    z += ["", "<i>Kaufalarm kommt automatisch, sobald eine sichere Seite bestellbar wird.</i>"]
    return "\n".join(z)


def hilfe_text() -> str:
    return ("<b>TCG-Wächter – Befehle</b>\n"
            "/status – läuft der Wächter? Kurzüberblick mit Naruto-Vorbestellungen und den günstigsten Displays\n"
            "/naruto – alle beobachteten Naruto-Seiten mit Links\n"
            "/lieferbar – One Piece: je Set das günstigste lieferbare und vorbestellbare Display\n"
            "/hilfe – diese Übersicht\n\n"
            "Kaufalarme kommen weiterhin von selbst. Antwort dauert meist unter 30 Sekunden.")


# ---------------------------------------------------------------------------------------------- Abruf

def bearbeite(zustand: dict, op_zustand_laden: Callable[[], dict], alarm_shops_laden: Callable[[], Optional[set]],
              log: Callable[[str], None] = print, transport: Optional[Callable] = None,
              jetzt: Optional[dt.datetime] = None, grenze_cent: int = 25000) -> int:
    """Neue Befehle abholen und beantworten. Gibt die Zahl der Antworten zurück. Stört den Lauf nie."""
    global _befehle_gemeldet
    aktiv, _ = telegram.konfiguration()
    if not aktiv:
        return 0
    jetzt = jetzt or dt.datetime.now(dt.timezone.utc)
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    tb = zustand.setdefault("telegram_befehle", {})
    erster_abruf = "offset" not in tb
    if not _befehle_gemeldet:
        _api("setMyCommands", {"commands": json.dumps([{"command": c, "description": d} for c, d in BEFEHLE])}, transport)
        _befehle_gemeldet = True
    antwort = _api("getUpdates", {"offset": tb.get("offset", 0), "timeout": 0,
                                  "allowed_updates": json.dumps(["message"])}, transport)
    if not antwort:
        return 0
    beantwortet = 0
    for u in antwort.get("result") or []:
        tb["offset"] = max(tb.get("offset", 0), int(u.get("update_id", 0)) + 1)
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != chat:
            continue   # fremde Chats nie bedienen
        text = (msg.get("text") or "").strip()
        if not text.startswith("/"):
            continue
        if erster_abruf and jetzt.timestamp() - float(msg.get("date") or 0) > MAX_ALTER_ERSTER_ABRUF:
            continue   # alte Nachrichten aus der Zeit vor den Befehlen nicht nachträglich beantworten
        befehl = text.split()[0][1:].split("@")[0].lower()
        try:
            if befehl in ("status", "start"):
                inhalt = status_text(zustand, op_zustand_laden(), alarm_shops_laden(), jetzt, grenze_cent)
            elif befehl in ("naruto", "vorbestellung", "vorbestellungen"):
                inhalt = naruto_text(zustand)
            elif befehl in ("lieferbar", "liste"):
                inhalt = lieferbar_text(op_zustand_laden(), alarm_shops_laden(), jetzt, grenze_cent)
            else:
                inhalt = hilfe_text()
        except Exception as ex:  # pragma: no cover – nie den Lauf stören
            inhalt = f"⚠️ Antwort konnte nicht erstellt werden ({type(ex).__name__})."
        ok, info = telegram.sende(inhalt, transport)
        beantwortet += ok
        log(f"Telegram-Befehl /{befehl}: {'beantwortet' if ok else info}")
    tb["zuletzt_abgefragt"] = jetzt.replace(microsecond=0).isoformat()
    return beantwortet


def fuer_lauf(zustand: dict, konfig, daten: Path, db: Path, log: Callable[[str], None] = print) -> int:
    """Anbindung an den Wächter-Lauf: lädt One-Piece-Zustand und Alarm-Händler nur, wenn ein Befehl kam."""
    def op_laden() -> dict:
        p = Path(daten) / "onepiece" / "zustand.json"
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def alarm_laden() -> Optional[set]:
        try:
            from .onepiece_haendler import mit_datenbank
            return {s.id for s in mit_datenbank(konfig, db).shops if s.kaufalarm_freigegeben}
        except Exception:
            return None

    grenze = int(float(konfig.produkte.get("preisgrenzen", {}).get("max_kaufpreis_eur", 250) or 250) * 100)
    return bearbeite(zustand, op_laden, alarm_laden, log, grenze_cent=grenze)
