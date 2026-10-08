"""Höflicher HTTP-Abruf (Anforderung 9).

- Ehrlicher User-Agent, keine Browser-Imitation.
- robots.txt wird beachtet (inkl. Crawl-delay).
- Mindestabstand zwischen Anfragen pro Host, Obergrenze pro Lauf.
- Bei 429/5xx: langsamer werden (Retry-After bzw. wachsende Pausen).
- Bei 401/403 oder Captcha/Bot-Schutz: sofort aufhören. Es wird NICHTS umgangen.
- Sperren/Drosselungen werden im Zustand gespeichert und beim nächsten Lauf respektiert.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from . import __version__

USER_AGENT = (f"OnePieceWaechter/{__version__} (privater Bestands- und Preiswaechter, keine Kaeufe; "
              "+https://github.com/TaCTiiCz/OnePieceW-chter)")
ROBOTS_TOKEN = "onepiecewaechter"

WIEDERHOLBAR = {429, 500, 502, 503, 504}
SPERRE = {401, 403}
# Nur eindeutige Merkmale echter Bot-Schutz-Seiten (nicht z. B. reCAPTCHA in Kontaktformularen)
_BOT_SCHUTZ = re.compile(r"cf-chl|challenge-platform|/cdn-cgi/challenge|attention required! \| cloudflare|"
                         r"are you a robot|captcha-delivery|px-captcha|hcaptcha-challenge", re.IGNORECASE)


@dataclass
class Antwort:
    ok: bool
    status: Optional[int]
    text: str = ""
    fehler: Optional[str] = None
    url: str = ""
    url_final: str = ""
    dauer_ms: int = 0

    def json(self):
        return json.loads(self.text)


class HostGesperrt(Exception):
    pass


# --- robots.txt (eigene Auswertung mit * und $ wie bei Google) ------------------
class Robots:
    def __init__(self, text: str):
        self.regeln: list[tuple[bool, str]] = []
        self.crawl_delay: Optional[float] = None
        gruppen: list[tuple[list[str], list[tuple[bool, str]], Optional[float]]] = []
        agents: list[str] = []
        regeln: list[tuple[bool, str]] = []
        delay: Optional[float] = None
        letzte_war_regel = False
        for zeile in text.splitlines():
            zeile = zeile.split("#", 1)[0].strip()
            if ":" not in zeile:
                continue
            feld, wert = (x.strip() for x in zeile.split(":", 1))
            feld = feld.lower()
            if feld == "user-agent":
                if letzte_war_regel:
                    gruppen.append((agents, regeln, delay))
                    agents, regeln, delay = [], [], None
                agents.append(wert.lower())
                letzte_war_regel = False
            elif feld in ("allow", "disallow"):
                if wert or feld == "allow":
                    regeln.append((feld == "allow", wert))
                letzte_war_regel = True
            elif feld == "crawl-delay":
                try:
                    delay = float(wert)
                except ValueError:
                    pass
                letzte_war_regel = True
        if agents:
            gruppen.append((agents, regeln, delay))
        eigene = [g for g in gruppen if any(a and a != "*" and a in ROBOTS_TOKEN for a in g[0])]
        alle = [g for g in gruppen if "*" in g[0]]
        for g in (eigene or alle):
            self.regeln.extend(g[1])
            if g[2] is not None:
                self.crawl_delay = g[2]

    @staticmethod
    def _passt(muster: str, pfad: str) -> bool:
        rx = re.escape(muster).replace(r"\*", ".*")
        if rx.endswith(r"\$"):
            rx = rx[:-2] + "$"
        return re.match(rx, pfad) is not None

    def erlaubt(self, url: str) -> bool:
        p = urlparse(url)
        pfad = (p.path or "/") + (("?" + p.query) if p.query else "")
        bester: Optional[tuple[int, bool]] = None
        for erlaubt, muster in self.regeln:
            if self._passt(muster, pfad):
                kandidat = (len(muster), erlaubt)
                if bester is None or kandidat[0] > bester[0] or (kandidat[0] == bester[0] and erlaubt):
                    bester = kandidat
        return True if bester is None else bester[1]


def _jetzt() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Abrufer:
    """Echter Abruf über das Internet."""

    def __init__(self, host_zustand: dict, schlafen: Callable[[float], None] = time.sleep,
                 transport: Optional[Callable] = None, protokoll: Optional[Callable[[str], None]] = None,
                 pausen: tuple = (10.0, 30.0, 90.0), robots_cache_stunden: float = 24.0):
        self.host_zustand = host_zustand  # wird im Zustand gespeichert
        self.pausen = pausen  # Wartezeiten zwischen Wiederholungen (wachsend)
        self.robots_cache_stunden = robots_cache_stunden
        self.schlafen = schlafen
        self.transport = transport or self._urllib_transport
        self.log = protokoll or (lambda s: None)
        self._robots: dict[str, Robots] = {}
        self._letzte_anfrage: dict[str, float] = {}
        self._anfragen: dict[str, int] = {}
        self._abstand: dict[str, float] = {}
        self._limit: dict[str, int] = {}
        self._gesperrt_lauf: dict[str, str] = {}

    # -- Konfiguration pro Host ---------------------------------------------
    def setze_host_regeln(self, host: str, min_abstand: float, max_anfragen: int) -> None:
        self._abstand[host] = min_abstand
        self._limit[host] = max_anfragen

    def host_pausiert(self, host: str) -> Optional[str]:
        """Grund, falls der Host aus einem früheren Lauf noch pausiert ist."""
        z = self.host_zustand.get(host, {})
        bis = z.get("pause_bis")
        if bis and dt.datetime.fromisoformat(bis) > _jetzt():
            return f"pausiert bis {bis} ({z.get('grund', '')})"
        return self._gesperrt_lauf.get(host)

    def _pausiere(self, host: str, stunden: float, grund: str) -> None:
        bis = (_jetzt() + dt.timedelta(hours=stunden)).replace(microsecond=0).isoformat()
        z = self.host_zustand.setdefault(host, {})
        z.update(pause_bis=bis, grund=grund)
        self._gesperrt_lauf[host] = grund
        self.log(f"  ! {host}: {grund} – Pause bis {bis}")

    # -- Transport -----------------------------------------------------------
    @staticmethod
    def _urllib_transport(url: str, kopf: dict, timeout: float) -> tuple[int, dict, str]:
        req = urllib.request.Request(url, headers=kopf)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                roh = r.read(8_000_000)
                if r.headers.get("Content-Encoding") == "gzip" or roh[:2] == b"\x1f\x8b":
                    roh = gzip.decompress(roh)
                kopf_antwort = dict(r.headers)
                kopf_antwort["x-final-url"] = r.geturl()
                return r.status, kopf_antwort, roh.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            try:
                body = e.read(200_000).decode("utf-8", errors="replace")
            except Exception:
                body = ""
            return e.code, dict(e.headers or {}), body

    # -- robots.txt ----------------------------------------------------------
    def _robots_fuer(self, basis: str) -> Robots:
        host = urlparse(basis).netloc
        if host not in self._robots:
            # robots.txt wird bis zu 24 h zwischengespeichert, damit häufige Läufe den Shop nicht belasten
            cache = self.host_zustand.get(host, {}).get("robots")
            if cache and _jetzt() - dt.datetime.fromisoformat(cache["geholt"]) < dt.timedelta(hours=self.robots_cache_stunden):
                self._robots[host] = Robots(cache["text"])
            else:
                status, _, text = self._roh(f"{urlparse(basis).scheme}://{host}/robots.txt", host)
                if status == 200:
                    text = text[:200_000]
                elif status in SPERRE:
                    raise HostGesperrt(f"robots.txt mit HTTP {status} verweigert")
                elif status in (0, 429) or status >= 500:
                    raise HostGesperrt(f"robots.txt nicht abrufbar (HTTP {status or 'Netzwerkfehler'})")
                else:
                    text = ""  # keine robots.txt -> keine Einschränkungen
                self._robots[host] = Robots(text)
                self.host_zustand.setdefault(host, {})["robots"] = {
                    "text": text, "geholt": _jetzt().replace(microsecond=0).isoformat()}
            cd = self._robots[host].crawl_delay
            if cd:
                self._abstand[host] = max(self._abstand.get(host, 4.0), min(cd, 60.0))
        return self._robots[host]

    def _roh(self, url: str, host: str) -> tuple[int, dict, str]:
        warte = self._abstand.get(host, 4.0) - (time.monotonic() - self._letzte_anfrage.get(host, -1e9))
        if warte > 0:
            self.schlafen(warte)
        self._anfragen[host] = self._anfragen.get(host, 0) + 1
        self._letzte_anfrage[host] = time.monotonic()
        kopf = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9",
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
                # Lieferland DE / Währung EUR wählen (öffentliche Shopify-Länderauswahl, keine Umgehung)
                "Cookie": "localization=DE; cart_currency=EUR"}
        try:
            return self.transport(url, kopf, 30.0)
        except Exception as e:  # Netzwerkfehler
            return 0, {}, f"{type(e).__name__}: {e}"

    # -- Öffentliche Methode -----------------------------------------------------
    def hole(self, url: str) -> Antwort:
        host = urlparse(url).netloc
        grund = self.host_pausiert(host)
        if grund:
            return Antwort(False, None, fehler=f"Host übersprungen: {grund}", url=url)
        try:
            robots = self._robots_fuer(url)
        except HostGesperrt as e:
            stunden = 6 if "verweigert" in str(e) else 0.5
            self._pausiere(host, stunden, str(e))
            return Antwort(False, None, fehler=str(e), url=url)
        if not robots.erlaubt(url):
            return Antwort(False, None, fehler="robots.txt erlaubt diesen Abruf nicht – wird respektiert", url=url)

        pausen = list(self.pausen)
        drossel = 0
        start = time.monotonic()
        for versuch in range(len(pausen) + 1):
            if self._anfragen.get(host, 0) >= self._limit.get(host, 60):
                return Antwort(False, None, fehler="Anfrage-Obergrenze für diesen Lauf erreicht", url=url)
            status, kopf, text = self._roh(url, host)
            kopf = {k.lower(): v for k, v in kopf.items()}
            if status == 200:
                if _BOT_SCHUTZ.search(text[:5000]) and not text.lstrip().startswith(("{", "[")):
                    self._pausiere(host, 6, "Bot-Schutz/Captcha erkannt – wird nicht umgangen")
                    return Antwort(False, 200, fehler="Bot-Schutz/Captcha erkannt", url=url)
                return Antwort(True, 200, text=text, url=url, url_final=kopf.get("x-final-url", url),
                               dauer_ms=int((time.monotonic() - start) * 1000))
            if status == 404:
                return Antwort(False, 404, fehler="Seite nicht gefunden (404)", url=url)
            if status in SPERRE or (status == 503 and _BOT_SCHUTZ.search(text[:5000])):
                self._pausiere(host, 6, f"Zugriff verweigert (HTTP {status}) – wird nicht umgangen")
                return Antwort(False, status, fehler=f"Zugriff verweigert (HTTP {status})", url=url)
            if status in WIEDERHOLBAR or status == 0:
                if status == 429:
                    drossel += 1
                    self._abstand[host] = min(self._abstand.get(host, 4.0) * 2, 60.0)
                if versuch >= len(pausen) or drossel >= 2:
                    if status == 429:
                        self._pausiere(host, 2, "wiederholt gedrosselt (HTTP 429)")
                    return Antwort(False, status or None,
                                   fehler=f"Abruf fehlgeschlagen nach {versuch + 1} Versuchen ({status or text[:80]})",
                                   url=url)
                warte = pausen[versuch]
                ra = kopf.get("retry-after")
                if ra and ra.strip().isdigit():
                    warte = max(warte, min(float(ra), 300.0))
                self.log(f"  … {host}: HTTP {status or 'Netzwerkfehler'}, warte {warte:.0f}s")
                self.schlafen(warte)
                continue
            return Antwort(False, status, fehler=f"unerwarteter HTTP-Status {status}", url=url)
        return Antwort(False, None, fehler="Abruf fehlgeschlagen", url=url)


class TestdatenAbrufer:
    """Liefert gespeicherte Antworten aus tests/fixtures (KEIN Netzwerkzugriff).

    Die Datei manifest.json ordnet URLs den Dateien zu. Nicht hinterlegte URLs
    liefern 404 – so werden auch Abruffehler realistisch durchgespielt.
    """

    def __init__(self, verzeichnis: Path):
        self.verzeichnis = Path(verzeichnis)
        self.manifest = json.loads((self.verzeichnis / "manifest.json").read_text(encoding="utf-8"))
        self.host_zustand: dict = {}

    def setze_host_regeln(self, host: str, min_abstand: float, max_anfragen: int) -> None:
        pass

    def host_pausiert(self, host: str) -> Optional[str]:
        return None

    def hole(self, url: str) -> Antwort:
        eintrag = self.manifest.get("urls", {}).get(url)
        if eintrag is None:
            return Antwort(False, 404, fehler="nicht in Testdaten hinterlegt (404)", url=url)
        status = eintrag.get("status", 200)
        if status != 200:
            return Antwort(False, status, fehler=eintrag.get("fehler", f"HTTP {status} (Testdaten)"), url=url)
        text = (self.verzeichnis / eintrag["datei"]).read_text(encoding="utf-8")
        return Antwort(True, 200, text=text, url=url)
