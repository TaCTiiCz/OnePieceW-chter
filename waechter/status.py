"""Bestimmt den Bestandsstatus eines Angebots aus den Daten der Produktseite.

Bekannte Fallen, die hier abgefangen werden:
- Shopify meldet "available: true" auch für Vorbestellungen  -> Vorbestell-Signale prüfen.
- Shopify meldet "available: true" immer, wenn der Shop keinen Bestand führt
  (inventory_management = null)                              -> UNCLEAR.
- Preis 0,00 ist meist ein Platzhalter                        -> Preis unbekannt.
- Beschreibung sagt "Pre-Order", Erscheinungsdatum liegt aber in der
  Vergangenheit (veralteter Text)                             -> UNCLEAR.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Iterable, Optional

from . import modelle as m
from .klassifizierung import normalisiere

VORBESTELL_MUSTER = re.compile(
    r"pre[\s\-]?order|vorbestell|vorverkauf|preordine|pre[\s\-]?ordine|preventa|pre[\s\-]?venta|"
    r"précommande|precommande|prevendita|reservierung|\breserva\b")
WARTELISTE_MUSTER = re.compile(r"waitlist|wait list|warteliste|notify me|benachrichtig|lista d'attesa|lista de espera")

_MONATE = {
    # englisch
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    # deutsch
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "mai": 5, "juni": 6, "juli": 7, "oktober": 10, "dezember": 12,
    # italienisch
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
    # spanisch
    "enero": 1, "febrero": 2, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "septiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
_MONATSNAMEN = "|".join(sorted(_MONATE, key=len, reverse=True))


def finde_daten(text: str) -> list[dt.date]:
    """Findet Kalenderdaten in einem Text (verschiedene Sprachen/Formate)."""
    n = normalisiere(text)
    gefunden: list[dt.date] = []

    def add(j: int, mo: int, t: int) -> None:
        try:
            gefunden.append(dt.date(j, mo, t))
        except ValueError:
            pass

    for t, mo, j in re.findall(r"\b(\d{1,2})\.(\d{1,2})\.(20\d\d)\b", n):
        add(int(j), int(mo), int(t))
    for j, mo, t in re.findall(r"\b(20\d\d)-(\d{2})-(\d{2})\b", n):
        add(int(j), int(mo), int(t))
    for mon, t, j in re.findall(rf"\b({_MONATSNAMEN})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d\d)\b", n):
        add(int(j), _MONATE[mon], int(t))
    for t, mon, j in re.findall(rf"\b(\d{{1,2}})\.?\s+(?:de\s+)?({_MONATSNAMEN})\s+(?:de\s+)?(20\d\d)\b", n):
        add(int(j), _MONATE[mon], int(t))
    return gefunden


def bestimme_status(*, verfuegbar: Optional[bool], bestand_verfolgt: Optional[bool], titel: str, variante: str,
                    tags: Iterable[str], beschreibung: str, verkaufsplaene: Iterable[str] = (),
                    schema_verfuegbarkeit: Optional[str] = None, heute: dt.date | None = None) -> tuple[str, list[str]]:
    heute = heute or dt.date.today()
    gruende: list[str] = []
    kurz = normalisiere(" ".join([titel, variante, " ".join(tags), " ".join(verkaufsplaene)]))
    schema = (schema_verfuegbarkeit or "").lower().rsplit("/", 1)[-1]

    if verfuegbar is None:
        return m.UNCLEAR, ["Verfügbarkeit nicht in den Produktdaten enthalten"]

    if verfuegbar is False:
        if WARTELISTE_MUSTER.search(kurz):
            return m.WAITLIST, ["nicht bestellbar, Warteliste/Benachrichtigung angeboten"]
        if schema in ("instock", "preorder", "presale"):
            return m.UNCLEAR, [f"widersprüchlich: Produktdaten 'nicht verfügbar', Seite meldet '{schema}'"]
        return m.SOLD_OUT, ["Produktdaten: nicht verfügbar"]

    # verfuegbar is True
    if bestand_verfolgt is False:
        return m.UNCLEAR, ["Shop führt für diesen Artikel keinen Bestand – 'verfügbar' ist nicht aussagekräftig"]
    if schema in ("outofstock", "soldout", "discontinued"):
        return m.UNCLEAR, [f"widersprüchlich: Produktdaten 'verfügbar', Seite meldet '{schema}'"]

    if VORBESTELL_MUSTER.search(kurz) or schema in ("preorder", "presale"):
        gruende.append("Vorbestellung laut Titel/Tags/Verkaufsplan/Seite")
        return m.PREORDER, gruende

    daten = finde_daten(beschreibung)
    if VORBESTELL_MUSTER.search(normalisiere(beschreibung)):
        if daten and max(daten) < heute:
            return m.UNCLEAR, [f"Beschreibung sagt Vorbestellung, Erscheinungsdatum {max(daten).isoformat()} liegt "
                               "aber in der Vergangenheit (Text vermutlich veraltet)"]
        return m.PREORDER, ["Vorbestellung laut Beschreibung"]
    if daten and min(daten) > heute and len(set(daten)) == 1:
        return m.PREORDER, [f"bestellbar vor Erscheinungsdatum {daten[0].isoformat()}"]

    if bestand_verfolgt is None:
        gruende.append("Bestandsführung unbekannt")
    return m.IN_STOCK, gruende + ["Produktdaten: verfügbar, keine Vorbestell-Hinweise"]
