"""Push-Benachrichtigungen für Naruto-Ereignisse (Telegram).

Kanal-Auswahl:
- Telegram, wenn TELEGRAM_AKTIV=1, TELEGRAM_BOT_TOKEN und TELEGRAM_CHAT_ID gesetzt sind.
- Sonst "nicht eingerichtet": Ereignisse erscheinen nur im Dashboard.
Für die Simulation kann eine eigene Telegram-Adresse (Test-Server) gesetzt werden.
"""

from __future__ import annotations

import datetime as dt
import html
import os
import time
from typing import Callable, Optional

from . import telegram

try:
    from zoneinfo import ZoneInfo
    _BERLIN = ZoneInfo("Europe/Berlin")
except Exception:  # pragma: no cover
    _BERLIN = None

KOPF = {
    "KAUFALARM": "🚨 KAUFALARM – jetzt vorbestellbar",
    "KAUFALARM_ANDERE_SPRACHE": "🔔 KAUFALARM (andere Sprache)",
    "FRUEHHINWEIS": "🟡 FRÜHHINWEIS – noch nicht bestellbar",
    "UNGEPRUEFTER_HINWEIS": "⚠️ UNGEPRÜFTER HINWEIS – keine Kaufempfehlung",
    "FEHLER": "⛔ FEHLER – Abruf fehlgeschlagen (nicht ausverkauft!)",
    "AUSGANGSLAGE": "📋 AUSGANGSLAGE",
}
VERTRAUEN = {"freigegeben": "✅ geprüft (dokumentiert)", "vorgeprueft": "☑️ automatisch vorgeprüft (Impressum/Versand DE)",
             "ungeprueft": "❗ UNGEPRÜFT"}


def euro(cent: Optional[int], waehrung: Optional[str] = "EUR") -> str:
    if cent is None:
        return "❓ fehlt"
    s = f"{cent / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    w = (waehrung or "").rstrip("?")
    zeichen = "€" if w in ("EUR", "") else w
    return f"{s} {zeichen}" + (" (Währung unbestätigt)" if not waehrung or str(waehrung).endswith("?") else "")


def zeit_de(iso: Optional[str]) -> str:
    if not iso:
        return "❓"
    t = dt.datetime.fromisoformat(iso)
    if _BERLIN:
        t = t.astimezone(_BERLIN)
    return t.strftime("%d.%m.%Y %H:%M:%S")


def formatiere(e: dict, ncfg: Optional[dict] = None, nachgesendet: bool = False, test: bool = False) -> str:
    z: list[str] = []
    if test or e.get("testmodus"):
        z.append("🧪 <b>TEST – SIMULIERTER RESTOCK – KEIN ECHTES ANGEBOT</b>")
    z.append(f"<b>{KOPF.get(e['typ'], e['typ'])}</b>" + (" (nachgesendet)" if nachgesendet else ""))
    z.append(html.escape(e.get("text", "")))
    if e.get("titel"):
        z.append("")
        z.append(f"<b>Produkt:</b> {html.escape(e['titel'])}")
        z.append(f"<b>Shop:</b> {html.escape(e.get('shop_name', '?'))} – {VERTRAUEN.get(e.get('vertrauen'), '❓')}")
        sprache = e.get("sprache") or "❓"
        hinweis = "" if e.get("sprache_offiziell") else " (❓ nicht offiziell bestätigt/unklar)"
        z.append(f"<b>Sprache:</b> {html.escape(sprache)}{hinweis} | <b>Variante:</b> {html.escape(e.get('variante') or '❓')}")
        z.append(f"<b>Status:</b> {html.escape(e.get('status') or '❓')}"
                 + (f" – Zweitprüfung: {html.escape(e['zweitpruefung'])}" if e.get("zweitpruefung") else ""))
        versand = euro(e.get("versand_cent"), e.get("waehrung")) if e.get("versand_cent") is not None else \
            f"❓ fehlt ({html.escape(e.get('versand_hinweis') or 'unbekannt')})"
        z.append(f"<b>Preis:</b> {euro(e.get('preis_cent'), e.get('waehrung'))} | <b>Versand DE:</b> {versand} | "
                 f"<b>Gesamt:</b> {euro(e.get('gesamt_cent'), e.get('waehrung'))}")
        if e.get("teuer"):
            z.append(f"💰 <b>Teuer:</b> {html.escape(e['teuer'])}")
        z.append(f"<b>Release:</b> {html.escape(e.get('release') or '❓ unbekannt (offiziell: Sommer 2027)')}")
        z.append(f"<b>Prüfzeit:</b> {zeit_de(e.get('pruefzeit') or e.get('zeit'))}")
        if e.get("nur_text"):
            z.append("ℹ️ Bestellbarkeit nur aus dem Seitentext erkannt (keine strukturierten Shopdaten).")
        if e.get("spekulativ"):
            z.append("⚠️ <b>SPEKULATIV:</b> Bandai hat noch keine Naruto-Produkte, Preise oder Termine offiziell angekündigt.")
    if e.get("url"):
        z.append(f'👉 <a href="{html.escape(e["url"], quote=True)}">{"Bestelllink" if e["typ"].startswith("KAUFALARM") else "Zur Seite"}</a>')
    z.append("<i>Keine automatische Bestellung.</i>")
    return "\n".join(z)


class Kanal:
    """Pushkanal mit Erfolgsmessung."""

    def __init__(self, name: str, aktiv: bool, sender: Optional[Callable[[str], tuple[bool, str]]] = None, info: str = ""):
        self.name = name
        self.aktiv = aktiv
        self._sender = sender
        self.info = info

    @classmethod
    def aus_umgebung(cls) -> "Kanal":
        aktiv, info = telegram.konfiguration()
        if aktiv:
            return cls("Telegram", True, lambda text: telegram.sende(text), info)
        return cls("Telegram", False, None, info)

    @classmethod
    def telegram_mit_adresse(cls, api_basis: str) -> "Kanal":
        """Für die Simulation: Telegram-API-Aufruf an einen eigenen (Test-)Server."""
        def sender(text):
            import urllib.request, urllib.parse, json
            daten = urllib.parse.urlencode({"chat_id": os.environ.get("TELEGRAM_CHAT_ID", "sim"), "text": text,
                                            "parse_mode": "HTML"}).encode()
            req = urllib.request.Request(f"{api_basis}/botSIMULATION/sendMessage", data=daten, method="POST")
            with urllib.request.urlopen(req, timeout=10) as r:
                return (r.status == 200 and json.loads(r.read()).get("ok", False)), "gesendet (Test-Server)"
        return cls("Telegram (Test-Server der Simulation)", True, sender, "Simulation")

    def beschreibung(self) -> str:
        return f"{self.name}: {'aktiv' if self.aktiv else 'NICHT eingerichtet'} – {self.info}"

    def sende(self, text: str) -> tuple[bool, str, int]:
        if not self.aktiv or self._sender is None:
            return False, "Pushkanal nicht eingerichtet", 0
        t0 = time.monotonic()
        try:
            ok, info = self._sender(text)
        except Exception as ex:
            ok, info = False, f"Fehler ({type(ex).__name__})"
        return ok, info, int((time.monotonic() - t0) * 1000)
