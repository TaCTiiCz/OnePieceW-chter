"""Vergleicht neue Beobachtungen mit dem gespeicherten Stand und erkennt Ereignisse.

Schutzregeln gegen Fehlalarme (Anforderungen 5 und 6):
- Erster erfolgreicher Abruf eines Shops = Ausgangsbasis. Es wird NICHTS gemeldet.
- Abruffehler und UNCLEAR-Status lösen nie ein Ereignis aus und überschreiben
  nicht den letzten sicheren Status. Ein Restock wird immer gegen den letzten
  SICHEREN Status geprüft (z. B. SOLD OUT -> Fehler -> IN STOCK ist ein Restock,
  aber IN STOCK -> Fehler -> IN STOCK ist keiner).
- Preisrückgänge nur bei gleicher Währung und über einer Mindestschwelle.
- Identische Meldungen werden innerhalb der Wiederholsperre nicht erneut verschickt.
- Kaufalarme nur für freigegebene Händler und sichere Treffer.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Optional

from . import modelle as m


def _fp(*teile) -> str:
    return hashlib.sha1("|".join(str(t) for t in teile).encode()).hexdigest()[:16]


def _euro(cent: Optional[int], waehrung: Optional[str] = "EUR") -> str:
    if cent is None:
        return "unbekannt"
    s = f"{cent / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} {'€' if waehrung == 'EUR' else (waehrung or '?')}"


VERGLEICHSFELDER = ("abruf_ok", "status", "preis_cent", "waehrung", "versand_cent", "gesamt_cent", "fehler",
                    "sicherheit", "sprache", "typ")


def verarbeite(b: m.Beobachtung, zustand: dict, *, shop_basis_erfasst: bool, shop_freigegeben: bool,
               einstellungen: dict, jetzt: dt.datetime) -> tuple[list[m.Ereignis], bool]:
    """Aktualisiert zustand['angebote'] und liefert (Ereignisse, ins_verlauf_schreiben)."""
    ts = jetzt.replace(microsecond=0).isoformat()
    angebote = zustand["angebote"]
    alt = angebote.get(b.angebot_id)
    neu_eintrag = alt is None
    if alt is None:
        alt = {"erstmals_gesehen": ts, "nach_basis_entdeckt": shop_basis_erfasst,
               "letzter_sicherer_status": None, "letzter_sicherer_preis_cent": None,
               "letzte_sichere_waehrung": None, "letzte": None}
    letzte = alt.get("letzte") or {}
    geaendert = neu_eintrag or any(letzte.get(f) != getattr(b, f) for f in VERGLEICHSFELDER)

    ereignisse: list[m.Ereignis] = []
    sicher_beobachtet = b.abruf_ok and b.status in m.SICHERE_STATUS
    vorher = alt.get("letzter_sicherer_status")
    vorher_preis = alt.get("letzter_sicherer_preis_cent")
    vorher_waehrung = alt.get("letzte_sichere_waehrung")

    def neues(typ: str, text: str, daten: dict) -> None:
        alarm = shop_freigegeben and b.sicherheit == m.SICHER and typ in m.ALARM_TYPEN
        if not shop_freigegeben:
            grund = "Händler nicht für Kaufalarme freigegeben"
        elif b.sicherheit != m.SICHER:
            grund = "unsicherer Treffer (Sprache/Typ/Identität unklar)"
        else:
            grund = "freigegeben"
        ereignisse.append(m.Ereignis(
            typ=typ, angebot_id=b.angebot_id, shop_id=b.shop_id, zeitpunkt=ts, text=text, url=b.url,
            alarm=alarm, alarm_grund=grund, fingerabdruck=_fp(b.angebot_id, typ, b.status, b.preis_cent),
            daten=daten))

    if sicher_beobachtet:
        basis_daten = {"status": b.status, "preis": _euro(b.preis_cent, b.waehrung),
                       "versand": _euro(b.versand_cent, b.waehrung) if b.versand_cent is not None else "unbekannt",
                       "gesamt": _euro(b.gesamt_cent, b.waehrung) if b.gesamt_cent is not None else "unbekannt"}
        if vorher is None:
            if alt.get("nach_basis_entdeckt") and shop_basis_erfasst:
                if b.status == m.PREORDER:
                    neues(m.NEUE_VORBESTELLUNG, f"Neue Vorbestellung: {b.ziel_anzeige} bei {b.shop_name}", basis_daten)
                elif b.status == m.IN_STOCK:
                    neues(m.NEU_LIEFERBAR, f"Neu gelistet und lieferbar: {b.ziel_anzeige} bei {b.shop_name}", basis_daten)
            # sonst: Ausgangsbasis – keine Meldung
        else:
            if vorher in (m.SOLD_OUT, m.WAITLIST) and b.status == m.IN_STOCK:
                neues(m.RESTOCK, f"Restock: {b.ziel_anzeige} bei {b.shop_name} (vorher {vorher})",
                      {**basis_daten, "vorher": vorher})
            elif vorher in (m.SOLD_OUT, m.WAITLIST) and b.status == m.PREORDER:
                neues(m.NEUE_VORBESTELLUNG, f"Vorbestellung (wieder) möglich: {b.ziel_anzeige} bei {b.shop_name}",
                      {**basis_daten, "vorher": vorher})
            if (b.status in m.KAUFBAR and b.preis_cent is not None and vorher_preis
                    and b.waehrung and b.waehrung == vorher_waehrung and b.waehrung_bestaetigt):
                diff = vorher_preis - b.preis_cent
                prozent = diff / vorher_preis * 100
                if diff >= einstellungen.get("preisrueckgang_min_euro", 2.0) * 100 and \
                        prozent >= einstellungen.get("preisrueckgang_min_prozent", 3.0):
                    neues(m.PREISRUECKGANG,
                          f"Preisrückgang: {b.ziel_anzeige} bei {b.shop_name}: {_euro(vorher_preis, b.waehrung)} → "
                          f"{_euro(b.preis_cent, b.waehrung)} (−{prozent:.1f} %)",
                          {**basis_daten, "vorher_preis": _euro(vorher_preis, b.waehrung)})

        alt["letzter_sicherer_status"] = b.status
        if vorher != b.status:
            alt["letzter_sicherer_status_seit"] = ts
        if b.preis_cent is not None and b.waehrung_bestaetigt:
            alt["letzter_sicherer_preis_cent"] = b.preis_cent
            alt["letzte_sichere_waehrung"] = b.waehrung

    # Wiederholsperre
    sperre = dt.timedelta(hours=float(einstellungen.get("wiederholsperre_stunden", 24)))
    for e in ereignisse:
        zuletzt = zustand["meldungen"].get(e.fingerabdruck)
        if zuletzt and jetzt - dt.datetime.fromisoformat(zuletzt) < sperre:
            e.unterdrueckt = True
        else:
            zustand["meldungen"][e.fingerabdruck] = ts

    alt["zuletzt_geprueft"] = ts
    if geaendert:
        alt["letzte_aenderung"] = ts
    alt["letzte"] = {k: v for k, v in b.als_dict().items()}
    angebote[b.angebot_id] = alt
    return ereignisse, geaendert


def aufraeumen(zustand: dict, jetzt: dt.datetime, tage: int = 30) -> None:
    grenze = jetzt - dt.timedelta(days=tage)
    zustand["meldungen"] = {fp: t for fp, t in zustand["meldungen"].items()
                            if dt.datetime.fromisoformat(t) >= grenze}
