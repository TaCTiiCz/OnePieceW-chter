"""Telegram-Benachrichtigungen (vorbereitet, standardmäßig AUS).

Aktiv nur, wenn ALLE drei Umgebungsvariablen gesetzt sind:
  TELEGRAM_AKTIV=1           (GitHub: Repository-Variable)
  TELEGRAM_BOT_TOKEN=...     (GitHub: Secret – niemals in den Quellcode!)
  TELEGRAM_CHAT_ID=...       (GitHub: Secret)
Der Token wird nie geloggt oder in Dateien geschrieben.
"""

from __future__ import annotations

import html
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

from . import modelle as m

SYMBOL = {m.RESTOCK: "🟢", m.NEU_LIEFERBAR: "🟢", m.NEUE_VORBESTELLUNG: "🟡", m.PREISRUECKGANG: "🔻"}


def konfiguration() -> tuple[bool, str]:
    aktiv = os.environ.get("TELEGRAM_AKTIV", "").strip().lower() in ("1", "true", "ja", "yes")
    token = bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip())
    chat = bool(os.environ.get("TELEGRAM_CHAT_ID", "").strip())
    if not aktiv:
        return False, "Telegram ist vorbereitet, aber nicht eingeschaltet (TELEGRAM_AKTIV ist nicht 1)"
    if not (token and chat):
        return False, "Telegram eingeschaltet, aber Secret TELEGRAM_BOT_TOKEN oder TELEGRAM_CHAT_ID fehlt"
    return True, "Telegram aktiv"


def formatiere(e: dict, beob: Optional[dict]) -> str:
    z = [f"{SYMBOL.get(e['typ'], '•')} <b>{html.escape(e['text'])}</b>"]
    d = e.get("daten", {})
    z.append(f"Status: {html.escape(d.get('status', '?'))}")
    z.append(f"Preis: {html.escape(d.get('preis', '?'))} | Versand DE: {html.escape(d.get('versand', '?'))} | "
             f"Gesamt: {html.escape(d.get('gesamt', '?'))}")
    if beob:
        z.append(f"Sprache: {beob.get('sprache')} | Typ: {beob.get('typ')} | versiegelt: {beob.get('versiegelt')} | "
                 f"24 Packs: {beob.get('vollstaendig')}")
        if beob.get("prioritaet"):
            z.append("⭐ Prioritäts-Set")
    z.append(f'<a href="{html.escape(e["url"], quote=True)}">Zur Produktseite</a>')
    z.append("<i>Keine automatische Bestellung. Bitte Seite selbst prüfen.</i>")
    return "\n".join(z)


def sende(text: str, transport: Optional[Callable] = None) -> tuple[bool, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return False, "Zugangsdaten fehlen"
    daten = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML",
                                    "disable_web_page_preview": "true"}).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        if transport:
            status, antwort = transport(url, daten)
        else:
            req = urllib.request.Request(url, data=daten, method="POST")
            with urllib.request.urlopen(req, timeout=20) as r:
                status, antwort = r.status, r.read().decode("utf-8", "replace")
        if status == 200 and json.loads(antwort).get("ok"):
            return True, "gesendet"
        return False, f"Telegram antwortete mit HTTP {status}"
    except urllib.error.HTTPError as e:
        return False, f"Telegram-Fehler HTTP {e.code}"
    except Exception as e:  # Token nie in Fehlermeldung übernehmen
        return False, f"Telegram nicht erreichbar ({type(e).__name__})"
