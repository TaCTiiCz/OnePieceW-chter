"""Erkennung des Bandai NARUTO CARD GAME und Abgrenzung gegen Verwechslungen."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import modelle as m
from .klassifizierung import erkenne_sprache, erkenne_typ, normalisiere
from .konfig import KONFIG_DIR

NARUTO_DATEI = KONFIG_DIR / "naruto.toml"


def lade_naruto(datei: Path = NARUTO_DATEI) -> dict:
    with open(datei, "rb") as f:
        return tomllib.load(f)


@dataclass
class NarutoTreffer:
    passend: bool
    sicherheit: str  # SICHER / UNSICHER
    sprache: str
    sprache_offiziell: bool
    variante: str
    gruende: list[str] = field(default_factory=list)
    ausschluss: Optional[str] = None


_TC = re.compile(r"traditional chinese|trad\.? chinese|繁體|繁体|\btc\b|\bzh-?tw\b|chinese \(traditional\)")


def _wortgrenze(begriff: str, text: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(begriff) + r"(?![a-z0-9])", text) is not None


def pruefe(titel: str, url: str = "", tags: tuple = (), hersteller: str = "", cfg: Optional[dict] = None) -> NarutoTreffer:
    """Ist das ein Angebot für das Bandai NARUTO CARD GAME? Unklares bleibt UNSICHER."""
    cfg = cfg or lade_naruto()
    er = cfg["erkennung"]
    handle = url.rsplit("/", 1)[-1] if url else ""
    text = normalisiere(f"{titel} {handle.replace('-', ' ').replace('_', ' ')} {' '.join(tags)}")
    gruende: list[str] = []

    if "naruto" not in text:
        return NarutoTreffer(False, m.UNSICHER, m.UNBEKANNT, False, m.TYP_UNBEKANNT, ausschluss="kein Naruto-Produkt")
    for a in er["ausschluss"]:
        if _wortgrenze(normalisiere(a), text):
            return NarutoTreffer(False, m.UNSICHER, m.UNBEKANNT, False, m.TYP_UNBEKANNT,
                                 ausschluss=f"Verwechslung: '{a}' (nicht das Bandai NARUTO CARD GAME)")
    pflicht = any(normalisiere(p.replace("-", " ")) in text for p in er["pflicht_phrasen"])
    if not pflicht:
        # "Naruto" + Booster/Display ohne "Card Game"/"TCG": z. B. Kayou-Packs, Figuren, Manga
        return NarutoTreffer(False, m.UNSICHER, m.UNBEKANNT, False, m.TYP_UNBEKANNT,
                             ausschluss="kein 'NARUTO CARD GAME'/'Naruto TCG' im Titel")
    sicherheit = m.SICHER
    if "naruto card game" in text or "naruto cardgame" in text:
        gruende.append("Titel enthält 'NARUTO CARD GAME'")
    else:
        gruende.append("Titel enthält 'Naruto TCG'")
    hersteller_text = normalisiere(f"{hersteller} {titel} {' '.join(tags)}")
    if any(h in hersteller_text for h in er.get("hersteller_woerter", ["bandai"])):
        gruende.append("Hersteller Bandai genannt")
    elif "naruto card game" not in text:
        sicherheit = m.UNSICHER
        gruende.append("Hersteller nicht genannt – könnte ein anderes Naruto-Kartenspiel sein")

    # Sprache
    sprache, hinweise = erkenne_sprache(titel, "", handle, [t for t in tags if len(t) <= 20])
    if _TC.search(text):
        sprache, hinweise = ("TC" if sprache in (m.UNBEKANNT, "CN") else m.WIDERSPRUCH), hinweise + ["TC (Titel)"]
    erlaubt = [er.get("sprache_prioritaet", "EN")] + list(er.get("weitere_sprachen", []))
    offiziell = sprache in erlaubt
    if sprache in (m.UNBEKANNT, m.WIDERSPRUCH):
        sicherheit = m.UNSICHER
        gruende.append(f"Sprache {sprache}")
    elif not offiziell:
        sicherheit = m.UNSICHER
        gruende.append(f"Sprache {sprache} ist offiziell nicht bestätigt")
    else:
        gruende.append(f"Sprache {sprache}")

    # Variante
    variante, vgrund = erkenne_typ(titel)
    if variante == m.ZUBEHOER or variante == m.EINZELKARTE:
        return NarutoTreffer(False, sicherheit, sprache, offiziell, variante,
                             ausschluss=f"Produktart {variante} (kein versiegeltes Spielprodukt)")
    if variante not in er.get("varianten", []):
        sicherheit = m.UNSICHER
        gruende.append(f"Produktart unklar ({variante})")
    else:
        gruende.append(f"Produktart {variante}")
    return NarutoTreffer(True, sicherheit, sprache, offiziell, variante, gruende)
