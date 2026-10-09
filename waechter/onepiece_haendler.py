"""One-Piece-Händlerliste: handverlesene Shops (config/shops.toml) plus geprüfte Shopify-Händler der Datenbank.

Aus der Datenbank kommen nur Shops, die Shopify nutzen und den Eignungstest bestanden haben. Kaufalarme gibt es nur
für handverlesene (freigegeben) und für „vorgeprüfte“ Händler. Alle anderen werden beobachtet und erscheinen im Bericht,
lösen aber keinen Alarm aus. Versandkosten bleiben „unbekannt“, wenn sie nicht belegt sind.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse

from .haendlerdb import ausschlussgrund
from .konfig import Konfig, Shop, Versand, ist_ausgeschlossen

ALARM_VERTRAUEN = ("vorgeprueft", "freigegeben")


def mit_datenbank(konfig: Konfig, db_datei: Path, *, max_seiten: int = 4, max_anfragen_pro_shop: int = 40) -> Konfig:
    """Gibt eine erweiterte Konfiguration zurück. Die übergebene bleibt unverändert."""
    db_datei = Path(db_datei)
    if not db_datei.exists():
        return konfig
    try:
        db = json.loads(db_datei.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return konfig
    vorhanden = {urlparse(s.basis_url).netloc.lower().removeprefix("www.") for s in konfig.shops}
    ids = {s.id for s in konfig.shops}
    neu: list[Shop] = []
    for h in (db.get("haendler") or {}).values():
        if not isinstance(h, dict) or h.get("status") != "geeignet" or h.get("plattform") != "shopify":
            continue
        basis = (h.get("basis_url") or f"https://{h.get('domain', '')}").rstrip("/")
        dom = urlparse(basis).netloc.lower().removeprefix("www.")
        name = h.get("name") or dom
        if not dom or dom in vorhanden or h.get("id") in ids:
            continue
        if ausschlussgrund(dom, name) or ist_ausgeschlossen(basis, konfig.ausschluss_domains, konfig.ausschluss_namen) \
                or ist_ausgeschlossen(name, konfig.ausschluss_domains, konfig.ausschluss_namen):
            continue
        vorhanden.add(dom)
        neu.append(Shop(
            id=h["id"], name=name, basis_url=basis, land=h.get("land", "?"), plattform="shopify",
            waehrung=h.get("waehrung") or "EUR", kollektionen=["all"], max_seiten=max_seiten,
            min_abstand_sekunden=3.0, max_anfragen_pro_lauf=max_anfragen_pro_shop,
            kaufalarm_freigegeben=h.get("vertrauen") in ALARM_VERTRAUEN,
            versand_de=Versand("unbekannt", [], "Versandkosten nach DE nicht belegt", "", ""),
            pruefung={"quelle": "Händlerdatenbank", "vertrauen": h.get("vertrauen", "ungeprueft")}))
    return replace(konfig, shops=list(konfig.shops) + sorted(neu, key=lambda s: s.id))
