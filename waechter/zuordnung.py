"""Ordnet klassifizierte Angebote den Ziel-Produkten aus config/products.toml zu."""

from __future__ import annotations

import re
from typing import Optional

from . import modelle as m
from .klassifizierung import normalisiere

_ANNI_NUMMER = re.compile(r"(?<![a-z0-9])(\d{1,2})\s*(?:st|nd|rd|th|\.)?\s*(?:year\s+)?anniversary")
_ANNI_WORT = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6}
_JP_WOERTER = re.compile(r"(?<![a-z0-9])(japanese|japanisch\w*|japonais\w*|japon[eé]s\w*|giapponese|jpn|jap|jp)(?![a-z0-9])")
_ORDINAL = {1: "st", 2: "nd", 3: "rd"}


def _anniversary(titeltext: str, k: m.Klassifizierung, produkte: dict) -> Optional[tuple[Optional[m.Treffer], str]]:
    """Alle Anniversary-Sets: bekannte aus [anniversary.sets], künftige automatisch ("<n>th Anniversary Set")."""
    cfg = produkte.get("anniversary")
    if not cfg or k.typ != m.ANNIVERSARY_SET:
        return None
    n = normalisiere(titeltext)
    verboten = [b for b in cfg.get("darf_nicht_enthalten", []) if normalisiere(b) in n]
    if verboten:
        return None, f"Anniversary: Verwechslungsgefahr ('{verboten[0]}' im Titel)"
    t = _ANNI_NUMMER.search(n)
    nummer = int(t.group(1)) if t else next((z for w, z in _ANNI_WORT.items() if re.search(rf"\b{w}\s+anniversary", n)), None)
    if nummer is not None and nummer > 10:
        return None, f"{nummer}. Anniversary ist kein One-Piece-Card-Game-Set (z. B. Anime-Jubiläum)"
    jp = bool(_JP_WOERTER.search(n))
    if k.sprache not in (m.EN, m.UNBEKANNT, m.WIDERSPRUCH, "JP"):
        return None, f"Anniversary: Sprache {k.sprache}"
    if nummer is None:
        return m.Treffer("anniversary-unbekannt", "Anniversary Set (Nummer unklar)", "sonder", m.UNSICHER, False,
                         ["Anniversary Set erkannt, aber welches (1st/2nd/…)? – bitte prüfen"]), ""
    edition = "JP" if jp else "EN"
    kandidaten = [s for s in cfg.get("sets", []) if int(s.get("nummer", 0)) == nummer]
    sp = next((s for s in kandidaten if s.get("edition") == edition), None) or \
        next((s for s in kandidaten if s.get("edition") == "ALLE"), None)
    gruende = []
    if sp:
        treffer = m.Treffer(sp["id"], sp["anzeige"], "sonder", m.SICHER, False, [f"Titel passt zu '{sp['anzeige']}'"])
    elif cfg.get("automatisch_kuenftige", True):
        name = f"{nummer}{_ORDINAL.get(nummer, 'th')} Anniversary Set" + (" (Japanese)" if jp else "")
        treffer = m.Treffer(f"{nummer}{_ORDINAL.get(nummer, 'th')}-anniversary-set-{edition.lower()}-auto", name, "sonder",
                            m.SICHER, False, [f"'{name}' automatisch erkannt (noch nicht in der Produktliste – Inhalt/UVP prüfen)"])
    else:
        return None, f"{nummer}. Anniversary Set ({edition}) nicht in der Produktliste"
    if edition == "JP":
        gruende.append("Japanese-Ausgabe (offiziell so benannt, Kartentext Englisch)")
    elif k.sprache == m.EN:
        gruende.append("Sprache Englisch erkannt")
    elif sp is not None and sp.get("edition") == "ALLE":
        gruende.append("Ausgabe/Sprache noch nicht offiziell festgelegt")
    else:
        treffer.sicherheit = m.UNSICHER
        gruende.append(f"Sprache {k.sprache} – englische oder japanische Ausgabe?")
    unsicher = [b for b in cfg.get("unsichere_begriffe", []) if normalisiere(b) in n]
    if unsicher:
        treffer.sicherheit = m.UNSICHER
        gruende.append(f"Bezeichnung '{unsicher[0]}' ist offiziell nicht belegt – Identität prüfen")
    treffer.gruende += gruende
    return treffer, ""


def _set_nummer(code: str) -> int:
    return int(code[2:])


def _sonderprodukt(titeltext: str, k: m.Klassifizierung, produkte: dict, prio: list[str]) -> Optional[tuple[Optional[m.Treffer], str]]:
    n = normalisiere(titeltext)
    for sp in produkte.get("sonderprodukte", []):
        gruppen = sp.get("muss_enthalten", [])
        if not any(all(normalisiere(b) in n for b in gruppe) for gruppe in gruppen):
            continue
        verboten = [b for b in sp.get("darf_nicht_enthalten", []) if normalisiere(b) in n]
        if verboten:
            return None, f"{sp['anzeige']}: Verwechslungsgefahr ('{verboten[0]}' im Titel)"
        if k.typ in (m.EINZELKARTE, m.CASE):
            return None, f"{sp['anzeige']}: falscher Produkttyp ({k.typ})"
        gruende = [f"Titel passt zu '{sp['anzeige']}'"]
        sicherheit = m.SICHER
        if k.sprache == m.EN:
            gruende.append("Sprache Englisch erkannt")
        elif k.sprache in (m.UNBEKANNT, m.WIDERSPRUCH):
            sicherheit = m.UNSICHER
            gruende.append(f"Sprache {k.sprache}")
        else:
            return None, f"{sp['anzeige']}: Sprache {k.sprache}"
        if k.typ not in (sp.get("typ"), m.TYP_UNBEKANNT):
            sicherheit = m.UNSICHER
            gruende.append(f"Produkttyp {k.typ} statt {sp.get('typ')}")
        unsicher = [b for b in sp.get("unsichere_begriffe", []) if normalisiere(b) in n]
        if unsicher:
            sicherheit = m.UNSICHER
            gruende.append(f"Bezeichnung '{unsicher[0]}' ist offiziell nicht belegt – Identität prüfen")
        if sp.get("identitaet") not in ("bestaetigt", "teilweise"):
            sicherheit = m.UNSICHER
            gruende.append("Produktidentität nicht bestätigt")
        return m.Treffer(sp["id"], sp["anzeige"], "sonder", sicherheit, False, gruende), ""
    return None


def ordne_zu(titeltext: str, k: m.Klassifizierung, produkte: dict) -> tuple[Optional[m.Treffer], str]:
    """Gibt (Treffer, "") oder (None, Ausschlussgrund) zurück."""
    if not k.ist_one_piece:
        return None, "kein One-Piece-Produkt"
    prio = [p.upper() for p in produkte.get("displays", {}).get("prioritaet", [])]

    anni = _anniversary(titeltext, k, produkte)
    if anni is not None:
        return anni
    sonder = _sonderprodukt(titeltext, k, produkte, prio)
    if sonder is not None:
        return sonder

    if k.typ == m.SLEEVED_BOOSTER:
        sets = [s.upper() for s in produkte.get("sleeved", {}).get("sets", [])]
        if k.set_code not in sets:
            return None, f"Sleeved Booster für {k.set_code or 'unbekanntes Set'} (nicht beobachtet)"
        return _sprache_pruefen(m.Treffer(f"sleeved-{k.set_code}", f"{k.set_code} Sleeved Booster (EN)", "sleeved",
                                          m.SICHER, k.set_code in prio, ["Sleeved Booster erkannt"]), k)

    if k.typ in (m.DISPLAY, m.TYP_UNBEKANNT):
        if not k.set_code:
            return None, "Display ohne erkennbares OP-Set" if k.typ == m.DISPLAY else "weder Typ noch Set erkennbar"
        ab = int(produkte.get("displays", {}).get("ab_set", 1))
        if _set_nummer(k.set_code) < ab:
            return None, f"Set {k.set_code} vor OP{ab:02d}"
        if k.versiegelt == m.NEIN:
            return None, "nicht originalversiegelt (geöffnet/gebraucht/repack)"
        if k.vollstaendig == m.NEIN:
            return None, "unvollständig"
        t = m.Treffer(f"display-{k.set_code}", f"{k.set_code} Booster Display (EN, 24 Packs)", "display",
                      m.SICHER, k.set_code in prio, ["Booster Display erkannt"])
        if k.typ == m.TYP_UNBEKANNT:
            t.sicherheit = m.UNSICHER
            t.gruende = ["Produkttyp unklar (kein 'Display/Booster Box' im Titel)"]
        bis = int(produkte.get("displays", {}).get("bekannt_bis_set", 0) or 0)
        if bis and _set_nummer(k.set_code) > bis:
            t.sicherheit = m.UNSICHER
            t.gruende.append(f"Set {k.set_code} ist noch nicht angekündigt (bekannt bis OP{bis:02d}) – "
                             "spekulative Platzhalter-Vorbestellung, kein Kaufalarm")
        return _sprache_pruefen(t, k)

    return None, f"Produkttyp {k.typ} wird nicht beobachtet"


def _sprache_pruefen(t: m.Treffer, k: m.Klassifizierung) -> tuple[Optional[m.Treffer], str]:
    if k.sprache == m.EN:
        t.gruende.append("Sprache Englisch erkannt")
        return t, ""
    if k.sprache in (m.UNBEKANNT, m.WIDERSPRUCH):
        t.sicherheit = m.UNSICHER
        t.gruende.append(f"Sprache {k.sprache}: {'; '.join(k.sprach_hinweise)}")
        return t, ""
    return None, f"Sprache {k.sprache} ({'; '.join(k.sprach_hinweise)})"
