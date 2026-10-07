"""Simulierter Restock: prüft den GESAMTEN Weg bis zur Test-Pushmeldung und misst die Verzögerung.

Ablauf:
1. Ein lokaler Test-Shop (nur auf diesem Rechner, 127.0.0.1) bietet eine Naruto-Seite "ausverkauft" an.
2. Der Wächter erfasst die Ausgangsbasis.
3. Der Test-Shop schaltet auf "vorbestellbar" (Zeitpunkt T0).
4. Der Wächter erkennt den Wechsel, ruft die Seite ERNEUT ab, prüft Sprache/Preis/Bestellbarkeit
   und sendet eine Pushmeldung mit der Kennzeichnung "TEST – SIMULIERTER RESTOCK".
5. Gemessen wird T0 -> Push angekommen und Erkennung -> Push.

Ohne eingerichtetes Telegram geht die Meldung an einen lokalen Test-Telegram-Server.
Mit --telegram-echt wird die echte Telegram-API benutzt (Nachricht ist klar als TEST markiert).
Zusätzlich wird geprüft: Abruffehler -> KEIN Alarm und nicht "ausverkauft"; keine doppelten Alarme.
"""

from __future__ import annotations

import copy
import datetime as dt
import http.server
import json
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from . import push
from .abruf import Abrufer
from .naruto import lade_naruto
from .naruto_lauf import KAUFALARM, Lauf, lade_betrieb

TITEL = "NARUTO CARD GAME Booster Display (24 Packs) - Englisch - Bandai"


class _Zustand:
    verfuegbar = False
    fehler = False
    pushes: list = []


def _seite(verfuegbar: bool) -> str:
    avail = "https://schema.org/PreOrder" if verfuegbar else "https://schema.org/OutOfStock"
    knopf = '<button>Jetzt vorbestellen</button>' if verfuegbar else '<p>Ausverkauft</p>'
    ld = {"@context": "https://schema.org", "@type": "Product", "name": TITEL, "brand": "Bandai",
          "offers": {"@type": "Offer", "price": "149.99", "priceCurrency": "EUR", "availability": avail}}
    return (f"<!doctype html><html><head><title>{TITEL}</title>"
            f'<script type="application/ld+json">{json.dumps(ld)}</script></head>'
            f"<body><h1>{TITEL}</h1><p>Sprache: Englisch. 24 Booster.</p>{knopf}</body></html>")


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):  # keine Konsolenausgabe
        pass

    def _send(self, code: int, text: str, typ: str = "text/html; charset=utf-8") -> None:
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/robots.txt":
            return self._send(200, "User-agent: *\nAllow: /\n", "text/plain")
        if self.path.startswith("/vorbestellungen"):
            return self._send(200, '<html><body><a href="/produkte/naruto-card-game-booster-display-en">'
                                   f"{TITEL}</a> Pokémon One Piece TCG Booster</body></html>")
        if self.path.startswith("/produkte/naruto-card-game-booster-display-en"):
            if _Zustand.fehler:
                return self._send(503, "Service Unavailable")
            return self._send(200, _seite(_Zustand.verfuegbar))
        return self._send(404, "nicht gefunden")

    def do_POST(self):
        laenge = int(self.headers.get("Content-Length", 0))
        daten = self.rfile.read(laenge).decode()
        if self.path.endswith("/sendMessage"):
            _Zustand.pushes.append({"t": time.monotonic(), "daten": daten})
            return self._send(200, '{"ok": true, "result": {}}', "application/json")
        return self._send(404, "")


def starte_server() -> tuple[http.server.ThreadingHTTPServer, str]:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def simuliere(telegram_echt: bool = False, intervall: float = 5.0, log=print, daten_dir: Optional[Path] = None) -> dict:
    _Zustand.verfuegbar, _Zustand.fehler, _Zustand.pushes = False, False, []
    srv, basis = starte_server()
    tmp = Path(tempfile.mkdtemp(prefix="waechter-sim-"))
    daten = daten_dir or (tmp / "daten")
    db = tmp / "haendler_db.json"
    db.write_text(json.dumps({"haendler": {"simshop": {
        "id": "simshop", "name": "SIMULATIONS-SHOP (Test)", "domain": basis.split("//")[1], "basis_url": basis,
        "land": "DE", "plattform": "unbekannt", "status": "geeignet", "vertrauen": "vorgeprueft",
        "entdeckung": [{"art": "kategorie_vorbestellung", "url": basis + "/vorbestellungen"}]}}}), encoding="utf-8")
    ncfg = copy.deepcopy(lade_naruto())
    ncfg["offizielle_quellen"] = []
    betrieb = copy.deepcopy(lade_betrieb())
    betrieb["intervalle"].update(naruto_produktseite=int(intervall), entdeckung_schnell=int(intervall * 2))
    betrieb["grenzen"].update(min_abstand_sekunden=0.2, max_laufzeit_sekunden=30, max_anfragen_pro_shop_und_lauf=50)
    betrieb["betrieb"].update(ausfuehrung="Simulation", zeitplan_minuten=0)
    if telegram_echt:
        kanal = push.Kanal.aus_umgebung()
        if not kanal.aktiv:
            srv.shutdown()
            return {"ok": False, "fehler": "Telegram ist nicht eingerichtet (TELEGRAM_AKTIV/Secrets fehlen)"}
    else:
        kanal = push.Kanal.telegram_mit_adresse(basis)

    def lauf() -> Lauf:
        ab = Abrufer({}, pausen=(0.5,))
        l = Lauf(None, ab, daten, db_datei=db, ncfg=ncfg, betrieb=betrieb, push_kanal=kanal, log=lambda s: None,
                 onepiece=False, testmodus=True)
        l.ausfuehren()
        l.speichern()
        return l

    ergebnis: dict = {"ok": False, "schritte": []}
    try:
        # Ausgangsbasis: so lange prüfen, bis die Seite einmal sicher als "ausverkauft" erfasst ist
        basis_meldungen = 0
        for _ in range(30):
            l1 = lauf()
            basis_meldungen += len(l1.ereignisse)
            angebote = list(l1.zustand["naruto"]["angebote"].values())
            if angebote and angebote[0].get("letzter_sicherer_status") == "SOLD OUT":
                break
            time.sleep(1.0)
        ergebnis["schritte"].append(f"Ausgangsbasis: {len(angebote)} Angebot(e) erfasst (ausverkauft), "
                                    f"{basis_meldungen} Meldungen (erwartet: 0)")
        time.sleep(intervall + 0.5)
        l2 = lauf()
        ergebnis["schritte"].append(f"Lauf danach (unverändert ausverkauft): {len(l2.ereignisse)} Meldungen")
        # Abruffehler darf weder Alarm noch "ausverkauft" erzeugen
        _Zustand.fehler = True
        time.sleep(intervall + 0.5)
        l3 = lauf()
        b = next(iter(l3.zustand["naruto"]["angebote"].values()))
        ergebnis["fehler_test"] = {"meldungen": [e["typ"] for e in l3.ereignisse], "status": b["letzte"]["status"],
                                   "letzter_sicherer_status": b["letzter_sicherer_status"]}
        ergebnis["schritte"].append(f"Lauf 3 (Abruffehler 503): Status {b['letzte']['status']}, Meldungen {len(l3.ereignisse)}")
        _Zustand.fehler = False
        # Restock auslösen
        t0 = time.monotonic()
        _Zustand.verfuegbar = True
        log("Test-Shop: jetzt VORBESTELLBAR (T0)")
        alarm = None
        frist = t0 + intervall * 6 + 30
        while time.monotonic() < frist and alarm is None:
            time.sleep(0.5)
            l = lauf()
            alarm = next((e for e in l.ereignisse if e["typ"] == KAUFALARM and e.get("gesendet")), None)
        if alarm is None:
            ergebnis["fehler"] = "kein Kaufalarm innerhalb der Frist"
            return ergebnis
        t_push = (_Zustand.pushes[-1]["t"] if (_Zustand.pushes and not telegram_echt) else time.monotonic())
        ergebnis["wechsel_bis_push_s"] = round(t_push - t0, 2)
        ergebnis["erkennung_bis_push_ms"] = alarm.get("latenz_ms")
        ergebnis["push_dauer_ms"] = alarm.get("push_ms")
        ergebnis["zweitpruefung"] = alarm.get("zweitpruefung")
        ergebnis["pushtext"] = push.formatiere(alarm, ncfg)
        ergebnis["schritte"].append(f"Restock erkannt und gemeldet nach {ergebnis['wechsel_bis_push_s']} s "
                                    f"(Prüfintervall {intervall} s)")
        # keine doppelte Meldung
        time.sleep(intervall + 0.5)
        l5 = lauf()
        doppelt = [e for e in l5.ereignisse if e["typ"] == KAUFALARM and e.get("gesendet")]
        ergebnis["doppelt_gesendet"] = len(doppelt)
        ergebnis["schritte"].append(f"Lauf danach (unverändert bestellbar): {len(doppelt)} weitere Kaufalarme")
        ergebnis["ok"] = (not doppelt and ergebnis["fehler_test"]["meldungen"] == []
                          and ergebnis["fehler_test"]["letzter_sicherer_status"] == "SOLD OUT")
        ergebnis["kanal"] = kanal.beschreibung()
        ergebnis["zeit"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
        return ergebnis
    finally:
        srv.shutdown()
