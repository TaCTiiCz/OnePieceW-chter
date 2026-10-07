"""Erkennt Sprache, Produkttyp, Set, Versiegelung und Vollständigkeit eines Angebots.

Grundsatz: Was nicht eindeutig erkennbar ist, bleibt UNBEKANNT. Es wird nichts geraten.
Die Sprache wird nur aus Titel, Variantenname, URL-Handle und Tags gelesen –
NICHT aus der Beschreibung (dort steht z. B. bei italienischen Produkten oft
"English: Chaos Rising" als Übersetzungshinweis).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

from . import modelle as m


def normalisiere(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("’", "'").replace("‘", "'").replace("´", "'").replace("`", "'")
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"<[^>]+>", " ", text)  # HTML-Tags entfernen
    text = re.sub(r"&nbsp;|&amp;", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def woerter(text: str) -> list[str]:
    return re.findall(r"[a-z0-9äöüßéèàíóúñç']+", normalisiere(text))


# --- Sprache -------------------------------------------------------------------
_SPRACH_WOERTER = {
    m.EN: {"en", "eng", "english", "englisch", "englische", "englischer", "inglese", "ingles", "inglés", "anglais"},
    "JP": {"jp", "jpn", "jap", "japanese", "japanisch", "japanische", "giapponese", "japones", "japonés", "japonais"},
    "CN": {"cn", "chn", "chinese", "chinesisch", "chinesische", "cinese", "chino"},
    "KR": {"kr", "kor", "korean", "koreanisch", "coreano"},
    "FR": {"fr", "french", "französisch", "franzosisch", "francais", "français", "francese"},
    "DE": {"deutsch", "deutsche", "german"},
    "IT": {"ita", "italiano", "italian", "italienisch"},
    "ES": {"spanish", "español", "espanol", "spanisch", "spagnolo"},
}
# Mehrdeutige Kurzcodes (it/de/es/pt sind auch normale Wörter) zählen nur in Klammern oder als Titelende "- DE"
_KURZCODE = re.compile(r"[\(\[]\s*(it|de|es|pt)\s*[\)\]]|\s-\s*(it|de|es|pt)\s*$")
_KURZCODE_SPRACHE = {"it": "IT", "de": "DE", "es": "ES", "pt": "PT"}
_ASIA_MUSTER = re.compile(r"\b(asia(n)?[\s\-]*(english|en|eng)|(english|en|eng)[\s\-]*asia(n)?|asia version|asian version)\b")


def erkenne_sprache(titel: str, variante: str = "", handle: str = "", tags: Iterable[str] = ()) -> tuple[str, list[str]]:
    """Gibt (Sprache, Hinweise) zurück. Mehrdeutig -> WIDERSPRÜCHLICH, nichts -> UNBEKANNT."""
    quellen = {
        "Titel": titel,
        "Variante": "" if (variante or "").lower() == "default title" else variante,
        "URL": (handle or "").replace("-", " ").replace("_", " "),
        "Tags": " ".join(t.replace("lang-", "") for t in tags if t and len(t) <= 20),
    }
    gefunden: dict[str, list[str]] = {}
    for quelle, text in quellen.items():
        norm = normalisiere(text)
        if _ASIA_MUSTER.search(norm):
            gefunden.setdefault(m.EN_ASIA, []).append(quelle)
            norm = _ASIA_MUSTER.sub(" ", norm)
        if quelle in ("Titel", "Variante"):
            for treffer in _KURZCODE.finditer(norm):
                code = treffer.group(1) or treffer.group(2)
                gefunden.setdefault(_KURZCODE_SPRACHE[code], []).append(quelle)
        w = set(woerter(norm))
        for sprache, marker in _SPRACH_WOERTER.items():
            if w & marker:
                gefunden.setdefault(sprache, []).append(quelle)
    hinweise = [f"{s} ({', '.join(q)})" for s, q in gefunden.items()]
    if not gefunden:
        return m.UNBEKANNT, ["keine Sprachangabe gefunden"]
    if m.EN_ASIA in gefunden:
        andere = set(gefunden) - {m.EN_ASIA, m.EN}
        return (m.WIDERSPRUCH if andere else m.EN_ASIA), hinweise
    if len(gefunden) > 1:
        return m.WIDERSPRUCH, hinweise
    return next(iter(gefunden)), hinweise


# --- Set-Code ------------------------------------------------------------------
# OP13, OP-13, OP 13, OP-013 – aber NICHT Kartennummern wie OP13-045
_SET_MUSTER = re.compile(r"(?<![a-z0-9])op\s?-?\s?0?(\d{1,2})(?!\d)(?!\s?-\s?\d{3})")
_KARTENNUMMER = re.compile(r"(?<![a-z0-9])(op|eb|st|prb|p)\s?-?\d{2,3}\s?-\s?\d{3}(?!\d)")


def erkenne_set(text: str, setnamen: dict[str, list[str]] | None = None) -> tuple[Optional[str], str]:
    norm = normalisiere(text)
    codes = sorted({f"OP{int(n):02d}" for n in _SET_MUSTER.findall(norm) if int(n) > 0})
    if len(codes) == 1:
        return codes[0], "Set-Code im Titel"
    if len(codes) > 1:
        return None, f"mehrere Set-Codes ({', '.join(codes)})"
    if setnamen:
        namen_treffer = sorted({code for code, namen in setnamen.items() for n in namen if n in norm})
        if len(namen_treffer) == 1:
            return namen_treffer[0], "Set-Name im Titel"
        if len(namen_treffer) > 1:
            return None, f"mehrere Set-Namen ({', '.join(namen_treffer)})"
    return None, "kein Set erkannt"


# --- Produkttyp ----------------------------------------------------------------
def _hat(norm: str, *phrasen: str) -> bool:
    return any(re.search(r"(?<![a-z0-9])" + re.escape(p) + r"(?![a-z0-9])", norm) for p in phrasen)


def erkenne_typ(text: str) -> tuple[str, str]:
    """Reihenfolge ist wichtig: spezifische Typen vor allgemeinen."""
    n = normalisiere(text)
    if _KARTENNUMMER.search(n) or _hat(n, "psa", "bgs", "cgc", "aog", "graded", "gradata", "gradiert", "slab",
                                         "alternate art", "alt. art", "alt art", "manga rare", "einzelkarte", "single card"):
        return m.EINZELKARTE, "Kartennummer/Grading/Einzelkarte"
    if _hat(n, "premium card collection"):
        return m.PREMIUM_CARD_COLLECTION, "'Premium Card Collection'"
    if _hat(n, "anniversary set") or (_hat(n, "anniversary") and _hat(n, "limited collection", "collection set")):
        return m.ANNIVERSARY_SET, "'Anniversary Set/Collection'"
    if _hat(n, "playmat", "play mat", "spielmatte", "deck box", "deckbox", "binder", "binders", "sammelalbum", "card sleeves", "sleeves",
            "kartenhüllen", "toploader", "squaroes", "collectors case", "storage box", "figur", "figure"):
        return m.ZUBEHOER, "Zubehör-Begriff"
    if _hat(n, "case", "cases", "12 boxes", "12 displays", "12x booster box", "12 x booster box",
            "12 booster boxes", "12er case", "case da", "caja de 12", "karton"):
        return m.CASE, "Case-Begriff (mehrere Displays)"
    if _hat(n, "sleeved booster", "sleeved boosters", "sleeved"):
        return m.SLEEVED_BOOSTER, "'Sleeved Booster'"
    if _hat(n, "double pack", "double pack set"):
        return m.DOUBLE_PACK, "'Double Pack'"
    if _hat(n, "starter deck", "ultimate deck", "starter deck ex", "deck"):
        return m.STARTER_DECK, "Deck"
    if _hat(n, "booster display", "display", "booster box", "boosterbox", "booster-box", "box da 24",
            "24 packs", "24 pack", "24 booster", "24 bustine", "24 buste", "24 sobres", "24er"):
        return m.DISPLAY, "Display/Booster Box"
    if _hat(n, "booster pack", "single pack", "1 pack", "bustina", "booster", "pack"):
        return m.BOOSTER_PACK, "einzelner Booster"
    return m.TYP_UNBEKANNT, "kein Produkttyp erkannt"


# --- Versiegelung / Vollständigkeit -------------------------------------------
_NICHT_VERSIEGELT = re.compile(
    r"(?<!un)opened|(?<!un)geöffnet|(?<!un)geoeffnet|\bused\b|gebraucht|resealed|repack|re-sealed|"
    r"ohne folie|ohne schweißfolie|no shrink|without shrink|aperto|abierto")
_VERSIEGELT = re.compile(
    r"factory[\s\-]sealed|\bsealed\b|versiegelt|originalverpackt|\bovp\b|sigillat|sellad|scelle|scellé|"
    r"ungeöffnet|unopened|neu und ungeöffnet")
_UNVOLLSTAENDIG = re.compile(r"incomplete|unvollständig|unvollstaendig|\bmissing\b|\bfehlt\b|\bfehlen\b|ohne\s+\d+\s+booster")
_VOLLSTAENDIG = re.compile(r"\b24\s*(x\s*)?(packs?|booster(s|packs?)?|bustine|buste|sobres|boosterpacks?)\b|\b24er\b")


def erkenne_versiegelung(titel: str, tags: Iterable[str], beschreibung: str) -> tuple[str, str]:
    kurz = normalisiere(titel + " " + " ".join(tags))
    lang = normalisiere(beschreibung)
    if _NICHT_VERSIEGELT.search(kurz):
        return m.NEIN, "Titel/Tags deuten auf geöffnet/gebraucht/repack"
    if _VERSIEGELT.search(kurz):
        return m.JA, "Titel/Tags: versiegelt/OVP"
    if _VERSIEGELT.search(lang) and not _NICHT_VERSIEGELT.search(lang):
        return m.JA, "Beschreibung: versiegelt/OVP"
    return m.UNBEKANNT, "keine Angabe zur Versiegelung"


def erkenne_vollstaendigkeit(titel: str, beschreibung: str, typ: str) -> tuple[str, str]:
    text = normalisiere(titel + " " + beschreibung)
    if _UNVOLLSTAENDIG.search(text):
        return m.NEIN, "Hinweis auf fehlende Inhalte"
    if typ == m.DISPLAY and _VOLLSTAENDIG.search(text):
        return m.JA, "24 Packs angegeben"
    return m.UNBEKANNT, "keine Angabe zum Inhalt"


def ist_one_piece(text: str, set_code: Optional[str]) -> bool:
    n = normalisiere(text)
    return "one piece" in n or "onepiece" in n or set_code is not None


def klassifiziere(titel: str, variante: str = "", handle: str = "", tags: Iterable[str] = (),
                  beschreibung: str = "", hersteller: str = "", produktart: str = "",
                  setnamen: dict | None = None) -> m.Klassifizierung:
    tags = [t for t in (tags or []) if isinstance(t, str)]
    var = "" if (variante or "").lower() == "default title" else (variante or "")
    titeltext = f"{titel} {var}".strip()
    sprache, hinweise = erkenne_sprache(titel, var, handle, tags)
    typ, typgrund = erkenne_typ(titeltext)
    set_code, setgrund = erkenne_set(titeltext, setnamen)
    versiegelt, vgrund = erkenne_versiegelung(titeltext, tags, beschreibung)
    vollst, vollgrund = erkenne_vollstaendigkeit(titeltext, beschreibung, typ)
    op = ist_one_piece(f"{titeltext} {handle} {' '.join(tags)} {hersteller} {produktart}", set_code)
    return m.Klassifizierung(
        ist_one_piece=op, sprache=sprache, sprach_hinweise=hinweise, typ=typ, set_code=set_code,
        versiegelt=versiegelt, vollstaendig=vollst,
        gruende=[f"Typ: {typgrund}", f"Set: {setgrund}", f"Versiegelung: {vgrund}", f"Inhalt: {vollgrund}"],
    )
