"""Gemeinsame Konstanten und Datenklassen."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

# --- Bestandsstatus (Anforderung 2) -------------------------------------------
IN_STOCK = "IN STOCK"
PREORDER = "PREORDER"
WAITLIST = "WAITLIST"
SOLD_OUT = "SOLD OUT"
UNCLEAR = "UNCLEAR"
ALLE_STATUS = (IN_STOCK, PREORDER, WAITLIST, SOLD_OUT, UNCLEAR)
# Nur diese Status gelten als "sicher" und dürfen Vergleiche auslösen
SICHERE_STATUS = (IN_STOCK, PREORDER, WAITLIST, SOLD_OUT)
KAUFBAR = (IN_STOCK, PREORDER)

# --- Sprache ------------------------------------------------------------------
EN = "EN"
EN_ASIA = "EN-ASIA"
UNBEKANNT = "UNBEKANNT"
WIDERSPRUCH = "WIDERSPRÜCHLICH"

# --- Produkttypen -------------------------------------------------------------
DISPLAY = "DISPLAY"
CASE = "CASE"
BOOSTER_PACK = "BOOSTER_PACK"
SLEEVED_BOOSTER = "SLEEVED_BOOSTER"
DOUBLE_PACK = "DOUBLE_PACK"
STARTER_DECK = "STARTER_DECK"
EINZELKARTE = "EINZELKARTE"
ZUBEHOER = "ZUBEHOER"
PREMIUM_CARD_COLLECTION = "PREMIUM_CARD_COLLECTION"
ANNIVERSARY_SET = "ANNIVERSARY_SET"
TYP_UNBEKANNT = "UNBEKANNT"

# --- Ja/Nein/Unbekannt (Versiegelung, Vollständigkeit) -------------------------
JA = "JA"
NEIN = "NEIN"

# --- Treffer-Sicherheit -------------------------------------------------------
SICHER = "SICHER"
UNSICHER = "UNSICHER"

# --- Ereignistypen ------------------------------------------------------------
BASIS = "BASIS"
RESTOCK = "RESTOCK"
NEU_LIEFERBAR = "NEU_LIEFERBAR"
NEUE_VORBESTELLUNG = "NEUE_VORBESTELLUNG"
PREISRUECKGANG = "PREISRUECKGANG"
ALARM_TYPEN = (RESTOCK, NEU_LIEFERBAR, NEUE_VORBESTELLUNG, PREISRUECKGANG)


@dataclass
class Klassifizierung:
    """Was der Wächter aus Titel/Tags eines Angebots herausliest."""

    ist_one_piece: bool
    sprache: str
    sprach_hinweise: list[str]
    typ: str
    set_code: Optional[str]
    versiegelt: str  # JA / NEIN / UNBEKANNT
    vollstaendig: str  # JA / NEIN / UNBEKANNT
    gruende: list[str] = field(default_factory=list)


@dataclass
class Treffer:
    """Zuordnung eines Angebots zu einem Ziel-Produkt."""

    ziel_id: str
    anzeige: str
    kategorie: str  # display / sleeved / sonder
    sicherheit: str  # SICHER / UNSICHER
    prioritaet: bool
    gruende: list[str] = field(default_factory=list)


@dataclass
class Beobachtung:
    """Ein einzelner Prüf-Datensatz für ein Angebot (eine Shop-Variante)."""

    angebot_id: str
    shop_id: str
    shop_name: str
    ziel_id: str
    ziel_anzeige: str
    kategorie: str
    sicherheit: str
    prioritaet: bool
    titel: str
    variante: str
    url: str
    zeitpunkt: str
    abruf_ok: bool
    status: str
    status_gruende: list[str]
    sprache: str
    typ: str
    set_code: Optional[str]
    versiegelt: str
    vollstaendig: str
    preis_cent: Optional[int]
    waehrung: Optional[str]
    waehrung_bestaetigt: bool
    versand_cent: Optional[int]
    versand_hinweis: str
    gesamt_cent: Optional[int]
    fehler: Optional[str] = None
    treffer_gruende: list[str] = field(default_factory=list)

    def als_dict(self) -> dict:
        return asdict(self)


@dataclass
class Ereignis:
    typ: str
    angebot_id: str
    shop_id: str
    zeitpunkt: str
    text: str
    url: str
    alarm: bool  # darf per Telegram gemeldet werden
    alarm_grund: str
    fingerabdruck: str
    gemeldet: bool = False
    unterdrueckt: bool = False
    daten: dict = field(default_factory=dict)

    def als_dict(self) -> dict:
        return asdict(self)
