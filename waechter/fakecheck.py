"""Fake-Shop-Überwachung: zusätzliche Prüfung aller Händler.

Zwei Stufen:
1. Händlerprüfung (``bewerte_shop``): Risikopunkte aus Domain-Alter (RDAP), Impressum/USt-ID, Rechtstexten, Zahlungsarten,
   Kontaktdaten, Reißer-Phrasen und Domain-Endung. Bei hohem Risiko verliert der Shop sein Kaufalarm-Recht
   (Vertrauen bleibt „ungeprueft"), bei mittlerem Risiko wird eine „vorgeprüft"-Einstufung zurückgenommen.
2. Laufzeit (``preis_verdacht``): Ist ein lieferbares Angebot deutlich billiger als derselbe Artikel bei anderen
   Händlern (Median), bekommt der Alarm eine deutliche Warnung. Echte Schnäppchen werden also gemeldet, aber markiert.

Alle Signale sind Hinweise, keine Beweise. Fehlende Daten (z. B. RDAP nicht erreichbar) geben KEINE Punkte.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import statistics
from typing import Optional
from urllib.parse import urlparse

from . import modelle as m

RISIKO_TLDS = (".top", ".xyz", ".icu", ".vip", ".cc", ".click", ".site", ".online", ".buzz", ".cfd", ".sbs", ".shop")
SICHERE_ZAHLUNG = re.compile(r"paypal|klarna|kreditkarte|credit card|visa|mastercard|shop ?pay|apple ?pay|google ?pay|"
                             r"sofort|ideal|bancontact|giropay|rechnung|stripe|mollie|adyen", re.I)
RISIKO_ZAHLUNG = re.compile(r"vorkasse|nur überweisung|bank ?transfer only|western union|krypto|bitcoin|usdt|"
                            r"prepayment only|moneygram", re.I)
REISSER = re.compile(r"bis zu\s*\d{2}\s?%\s*rabatt|up to\s*\d{2}\s?%\s*off|räumungsverkauf|geschäftsaufgabe|"
                     r"closing down|liquidation|-\s?[789]\d\s?%|nur noch heute|last chance sale", re.I)
RECHT = {"agb": r"agb|terms|bedingungen|conditions", "widerruf": r"widerruf|rückgabe|return|refund|retour",
         "datenschutz": r"datenschutz|privacy|privacidad|confidentialit"}
GUETESIEGEL = re.compile(r"trusted ?shops|ekomi|trustpilot|händlerbund|handlerbund|excellent\.|provenexpert|"
                         r"kundenbewertungen|verified reviews", re.I)
KONTAKT = re.compile(r"[\w.+-]+@[\w-]+\.[a-z]{2,}|\+?\d[\d /().-]{7,}\d", re.I)


def domain_alter_tage(domain: str, abrufer, jetzt: Optional[dt.datetime] = None) -> Optional[int]:
    """Alter der Domain laut RDAP in Tagen. None = nicht ermittelbar (kein Verdachtspunkt)."""
    jetzt = jetzt or dt.datetime.now(dt.timezone.utc)
    try:
        a = abrufer.hole(f"https://rdap.org/domain/{domain}")
        if not a.ok:
            return None
        for ev in (a.json().get("events") or []):
            if ev.get("eventAction") == "registration" and ev.get("eventDate"):
                t = dt.datetime.fromisoformat(ev["eventDate"].replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=dt.timezone.utc)
                return max(0, (jetzt - t).days)
    except Exception:
        return None
    return None


def bewerte_shop(domain: str, land: str, startseite: str, alle_links: list[tuple[str, str]], impressum: Optional[dict],
                 abrufer=None, jetzt: Optional[dt.datetime] = None) -> dict:
    """Risikopunkte + lesbare Signale. Stufe: gering (0-2), mittel (3-4), hoch (>=5)."""
    punkte, signale = 0, []
    text = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", startseite or "", flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    linkblob = " ".join(f"{u} {t}" for u, t in alle_links).lower()

    alter = domain_alter_tage(domain, abrufer, jetzt) if abrufer is not None else None
    if alter is not None:
        if alter < 90:
            punkte += 3
            signale.append(f"Domain erst {alter} Tage alt")
        elif alter < 365:
            punkte += 1
            signale.append(f"Domain jünger als 1 Jahr ({alter} Tage)")
    imp = impressum or {}
    deutschsprachig = land in ("DE", "AT", "CH")
    if not imp or imp.get("fehler"):
        punkte += 3 if deutschsprachig else 1
        signale.append("kein Impressum auffindbar")
    elif deutschsprachig and not (imp.get("ust_id") or imp.get("register")):
        punkte += 2
        signale.append("Impressum ohne USt-ID/Handelsregister")
    fehlend = [n for n, mu in RECHT.items() if not re.search(mu, linkblob)]
    if fehlend:
        punkte += min(2, len(fehlend))
        signale.append("Rechtstexte fehlen: " + ", ".join(fehlend))
    if RISIKO_ZAHLUNG.search(text) and not SICHERE_ZAHLUNG.search(text):
        punkte += 2
        signale.append("nur Vorkasse/Überweisung/Krypto als Zahlungsart genannt")
    if len(REISSER.findall(text)) >= 1:
        punkte += 1
        signale.append("Reißer-Werbung (Totalverkauf, extreme Rabatte)")
    if domain.lower().endswith(RISIKO_TLDS):
        punkte += 1
        signale.append(f"Domain-Endung häufig bei Fake-Shops ({domain.rsplit('.', 1)[-1]})")
    if not KONTAKT.search(text + " " + (imp.get("beleg", "") if imp else "")):
        punkte += 1
        signale.append("keine Kontaktdaten auf Startseite/Impressum")
    if GUETESIEGEL.search(text + " " + linkblob):
        punkte -= 1
        signale.append("Bewertungs-/Gütesiegel-Hinweis (positiv, nicht überprüft)")
    punkte = max(0, punkte)
    stufe = "hoch" if punkte >= 5 else ("mittel" if punkte >= 3 else "gering")
    return {"punkte": punkte, "stufe": stufe, "signale": signale, "domain_alter_tage": alter}


def anwenden(e: dict, bewertung: dict) -> None:
    """Trägt das Ergebnis in den Händlereintrag ein und nimmt bei Risiko das Kaufalarm-Recht zurück."""
    e["fake_check"] = bewertung
    if bewertung["stufe"] == "hoch" or (bewertung["stufe"] == "mittel" and e.get("vertrauen") == "vorgeprueft"):
        if e.get("vertrauen") in ("vorgeprueft", "freigegeben"):
            e["vertrauen"] = "ungeprueft"
        e.setdefault("gruende", []).append(
            f"Fake-Shop-Verdacht ({bewertung['stufe']}, {bewertung['punkte']} Punkte): " + "; ".join(bewertung["signale"][:4]))


def preis_verdacht(zustand: dict, ziel_id: str, shop_id: str, preis_cent: Optional[int], waehrung: Optional[str],
                   faktor: float = 0.5, min_proben: int = 3) -> Optional[str]:
    """Warntext, wenn der Preis weniger als `faktor` x Median anderer Händler (gleicher Artikel, EUR) beträgt."""
    if not preis_cent or waehrung != "EUR":
        return None
    preise = []
    gesehen = set()
    for a in zustand.get("angebote", {}).values():
        l = a.get("letzte") or {}
        if l.get("ziel_id") != ziel_id or l.get("shop_id") == shop_id or l.get("shop_id") in gesehen:
            continue
        if l.get("abruf_ok") and l.get("status") in m.KAUFBAR and l.get("waehrung") == "EUR" and (l.get("preis_cent") or 0) > 0:
            preise.append(l["preis_cent"])
            gesehen.add(l.get("shop_id"))
    if len(preise) < min_proben:
        return None
    med = statistics.median(preise)
    if preis_cent < faktor * med:
        return (f"⚠️ PREIS VERDÄCHTIG NIEDRIG: {100 - preis_cent / med * 100:.0f} % unter dem Median von "
                f"{len(preise)} anderen Händlern – Fake-Shop-Risiko, Shop vor dem Kauf prüfen!")
    return None
