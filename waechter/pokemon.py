"""Erkennung der Pokémon-Produkte „30 Jahre“ / „30th Celebration“ (englisch und deutsch).

Gleiche Schnittstelle wie `naruto.pruefe`, damit der Prüflauf (naruto_lauf.Lauf) beide Themen bedienen kann.
Gemeldet werden soll später nur ein Angebot zum Normalpreis – die Preisgrenze je Produktart kommt aus
config/pokemon.toml ([[produkte]] normalpreis/grenze).
"""

from __future__ import annotations

import re
import tomllib
import unicodedata
from pathlib import Path
from typing import Optional

from . import modelle as m
from .klassifizierung import erkenne_sprache, normalisiere
from .konfig import KONFIG_DIR
from .naruto import NarutoTreffer as Treffer

POKEMON_DATEI = KONFIG_DIR / "pokemon.toml"

# Suchwort für die Entdeckung (Shopify-/WooCommerce-Listen, Sitemaps, Links): nur grob vorfiltern
SUCHWORT = re.compile(r"30th[\s\-_+]*(celebration|anniversary)|30[\s\-_+]*jahre|30thcelebration|pokemon.*30|30.*pok[eé]mon",
                      re.I)

# Einzelkarten: Kartennummer wie "151/128" oder "#151"
_KARTENNUMMER = re.compile(r"(?<![0-9])\d{1,3}\s?/\s?\d{2,3}(?![0-9])|#\s?\d{2,3}\b")

# Sprache aus dem Produktnamen ableiten, wenn keine Sprachangabe im Titel steht
_DE_WOERTER = re.compile(r"top[\s\-]*trainer|kollektion|ordner|kampf[\s\-]*deck|mini[\s\-]*tin[\s\-]*box|2er[\s\-]*pack|"
                         r"feelinara|quajutsu|psiana|nachtara|mewtu\b|30[\s\-]*jahre|sammelkartenspiel")
_EN_WOERTER = re.compile(r"elite[\s\-]*trainer|collection|battle[\s\-]*deck|sylveon|greninja|espeon|umbreon|mewtwo|"
                         r"binder|30th[\s\-]*celebration|trading card game|\btcg\b")


def lade_pokemon(datei: Path = POKEMON_DATEI) -> dict:
    """Lädt die Konfiguration und leitet die Preisgrenzen je Produktart ab (Format wie bei Naruto)."""
    with open(datei, "rb") as f:
        cfg = tomllib.load(f)
    v = cfg.setdefault("vorbestellung", {})
    v["fair_bis_euro"] = {p["id"]: p["normalpreis"] for p in cfg.get("produkte", [])}
    v["max_euro"] = {p["id"]: p["grenze"] for p in cfg.get("produkte", [])}
    cfg.setdefault("offizielle_quellen", [])
    cfg["thema"] = "pokemon"
    return cfg


def _ohne_akzente(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _wortgrenze(begriff: str, text: str) -> bool:
    b = begriff.strip()
    muster = r"(?<![a-z0-9])" + re.escape(b) + (r"(?![a-z0-9])" if b[-1:].isalnum() else "")
    return re.search(muster, text) is not None


def produktart(text: str, cfg: dict) -> Optional[dict]:
    """Erste passende Produktart aus [[produkte]] (Reihenfolge = Priorität)."""
    for p in cfg.get("produkte", []):
        if any(re.search(mu, text) for mu in p.get("muster", [])):
            return p
    return None


def pruefe(titel: str, url: str = "", tags: tuple = (), hersteller: str = "", cfg: Optional[dict] = None) -> Treffer:
    """Ist das ein Angebot für ein Produkt der Pokémon-Erweiterung „30 Jahre“ (EN/DE)? Unklares bleibt UNSICHER."""
    cfg = cfg or lade_pokemon()
    er = cfg["erkennung"]
    handle = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1] if url else ""
    handle_text = handle.replace("-", " ").replace("_", " ").replace(".html", "")
    roh = f"{titel} {handle_text} {' '.join(tags)}"
    text = _ohne_akzente(normalisiere(roh))
    titel_text = _ohne_akzente(normalisiere(f"{titel} {handle_text}"))
    gruende: list[str] = []

    def nein(grund: str) -> Treffer:
        return Treffer(False, m.UNSICHER, m.UNBEKANNT, False, m.TYP_UNBEKANNT, ausschluss=grund)

    phrase = next((p for p in er["set_phrasen"] if p in titel_text), None)
    if phrase is None:
        return nein("kein '30th Celebration'/'30 Jahre' im Titel")
    if phrase in er.get("braucht_pokemon", []) and "pokemon" not in text:
        return nein("'30 Jahre' ohne 'Pokémon' – anderes Produkt")
    for a in er.get("ausschluss", []):
        if _wortgrenze(_ohne_akzente(normalisiere(a)), titel_text):
            return nein(f"ausgeschlossen: '{a.strip()}'")
    if er.get("kartennummer_ausschliessen", True) and _KARTENNUMMER.search(titel_text):
        return nein("Einzelkarte (Kartennummer im Titel)")
    gruende.append(f"Titel enthält '{phrase}'")

    art = produktart(titel_text, cfg)
    if art is None:
        return nein("Produktart unbekannt (kein versiegeltes 30-Jahre-Produkt erkannt)")
    if art["id"] == "BOOSTER" and re.search(r"display|box|\d+\s*x|x\s*\d+", titel_text):
        return nein("Booster-Menge unklar (Display/Mehrfachpack)")
    gruende.append(f"Produktart {art['name']}")

    sprache, hinweise = erkenne_sprache(titel, "", handle, [t for t in tags if len(t) <= 20])
    abgeleitet = False
    if sprache == m.UNBEKANNT:
        de, en = bool(_DE_WOERTER.search(titel_text)), bool(_EN_WOERTER.search(titel_text))
        if de and not en:
            sprache, abgeleitet = "DE", True
        elif en and not de:
            sprache, abgeleitet = m.EN, True
    erlaubt = er.get("sprache_prioritaet", ["EN", "DE"])
    erlaubt = list(erlaubt) if isinstance(erlaubt, list) else [erlaubt]
    if sprache in ("JP", "CN", "KR", "FR", "IT", "ES", "PT", "TC", m.EN_ASIA):
        return nein(f"Sprache {sprache} (nur Englisch und Deutsch werden beobachtet)")
    if sprache in erlaubt:
        sicherheit = m.SICHER
        gruende.append(f"Sprache {sprache}" + (" (aus dem Produktnamen abgeleitet)" if abgeleitet else ""))
    else:
        sicherheit = m.UNSICHER
        gruende.append(f"Sprache {sprache} – unklar")
    if art["id"] == "PC_ETB" and sprache == "DE":
        sicherheit = m.UNSICHER
        gruende.append("Pokémon-Center-Box gibt es nur auf Englisch")
    return Treffer(True, sicherheit, sprache, sprache in erlaubt, art["id"], gruende)


def grenze_text(variante: str, cfg: dict) -> str:
    def eur(x: float) -> str:
        return f"{x:.2f}".replace(".", ",") + " €"
    for p in cfg.get("produkte", []):
        if p["id"] == variante:
            return f"{p['name']}: Normalpreis ca. {eur(p['normalpreis'])}, gemeldet bis {eur(p['grenze'])}"
    return ""
