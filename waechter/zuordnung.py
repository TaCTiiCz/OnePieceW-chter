"""Ordnet klassifizierte Angebote den Ziel-Produkten aus config/products.toml zu."""

from __future__ import annotations

from typing import Optional

from . import modelle as m
from .klassifizierung import normalisiere


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
