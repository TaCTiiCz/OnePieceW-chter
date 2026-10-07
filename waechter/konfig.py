"""Lädt und prüft die Konfigurationsdateien in config/."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

PROJEKT = Path(__file__).resolve().parent.parent
KONFIG_DIR = PROJEKT / "config"


class KonfigFehler(ValueError):
    pass


@dataclass
class Versand:
    status: str  # "bekannt" / "unbekannt"
    staffel: list[tuple[int, int]]  # (ab_cent, kosten_cent), aufsteigend
    hinweis: str
    quelle: str
    geprueft_am: str

    def kosten_cent(self, bestellwert_cent: Optional[int]) -> Optional[int]:
        """Versandkosten nach DE für einen Bestellwert. None = unbekannt.

        Unbekannte Versandkosten werden NIE als 0 behandelt (Anforderung 4).
        """
        if self.status != "bekannt" or not self.staffel or bestellwert_cent is None:
            return None
        passend = [k for ab, k in self.staffel if bestellwert_cent >= ab]
        return passend[-1] if passend else None


@dataclass
class Shop:
    id: str
    name: str
    basis_url: str
    land: str
    plattform: str
    waehrung: str
    kollektionen: list[str]
    max_seiten: int
    min_abstand_sekunden: float
    max_anfragen_pro_lauf: int
    kaufalarm_freigegeben: bool
    versand_de: Versand
    pruefung: dict = field(default_factory=dict)

    @property
    def host(self) -> str:
        return urlparse(self.basis_url).netloc.lower()


@dataclass
class Konfig:
    shops: list[Shop]
    produkte: dict
    ausschluss_domains: list[str]
    ausschluss_namen: list[str]


def _cent(euro: float) -> int:
    return int(round(float(euro) * 100))


def ist_ausgeschlossen(url_oder_name: str, domains: list[str], namen: list[str]) -> bool:
    """True, wenn URL/Name zu einem ausgeschlossenen Händler gehört (Anforderung 7)."""
    text = (url_oder_name or "").lower()
    host = urlparse(text).netloc if "://" in text else text
    host = host.split("@")[-1].split(":")[0]
    for d in domains:
        d = d.lower()
        if host == d or host.endswith("." + d):
            return True
    kompakt = text.replace(" ", "").replace("-", "").replace("_", "").replace(".", "")
    for n in namen:
        n2 = n.lower().replace(" ", "").replace("-", "").replace("_", "").replace(".", "")
        if n2 and n2 in kompakt:
            return True
    return False


def lade_konfig(shops_datei: Path | None = None, produkte_datei: Path | None = None) -> Konfig:
    shops_datei = shops_datei or KONFIG_DIR / "shops.toml"
    produkte_datei = produkte_datei or KONFIG_DIR / "products.toml"
    with open(shops_datei, "rb") as f:
        roh = tomllib.load(f)
    with open(produkte_datei, "rb") as f:
        produkte = tomllib.load(f)

    aus = roh.get("ausschluss", {})
    domains = [d.lower() for d in aus.get("domains", [])]
    namen = [n.lower() for n in aus.get("namensmuster", [])]
    # Die Pflicht-Ausschlüsse gelten immer, auch wenn jemand sie aus der Datei löscht.
    for d in ("tcgdistro.com", "tcgdistronline.com", "tcgzenith.com"):
        if d not in domains:
            domains.append(d)
    for n in ("tcgdistro", "tcg distro", "tcgzenith", "tcg zenith"):
        if n not in namen:
            namen.append(n)

    shops: list[Shop] = []
    for sid, s in roh.get("shops", {}).items():
        for pflicht in ("name", "basis_url", "plattform", "waehrung", "versand_de"):
            if pflicht not in s:
                raise KonfigFehler(f"Shop '{sid}': Feld '{pflicht}' fehlt")
        if ist_ausgeschlossen(s["basis_url"], domains, namen) or ist_ausgeschlossen(s["name"], domains, namen) \
                or ist_ausgeschlossen(sid, domains, namen):
            raise KonfigFehler(f"Shop '{sid}' ({s['basis_url']}) ist ausgeschlossen und darf nicht überwacht werden")
        if s["plattform"] != "shopify":
            raise KonfigFehler(f"Shop '{sid}': Plattform '{s['plattform']}' wird noch nicht unterstützt")
        v = s["versand_de"]
        status = v.get("status", "unbekannt")
        if status not in ("bekannt", "unbekannt"):
            raise KonfigFehler(f"Shop '{sid}': versand_de.status muss 'bekannt' oder 'unbekannt' sein")
        staffel = sorted((_cent(t["ab"]), _cent(t["kosten"])) for t in v.get("staffel", []))
        if status == "bekannt" and not staffel:
            raise KonfigFehler(f"Shop '{sid}': Versand 'bekannt', aber keine Staffel angegeben")
        if status == "bekannt" and staffel[0][0] != 0:
            raise KonfigFehler(f"Shop '{sid}': Versandstaffel muss bei ab = 0 beginnen")
        shops.append(Shop(
            id=sid,
            name=s["name"],
            basis_url=s["basis_url"].rstrip("/"),
            land=s.get("land", "?"),
            plattform=s["plattform"],
            waehrung=s["waehrung"],
            kollektionen=list(s.get("kollektionen", ["all"])),
            max_seiten=int(s.get("max_seiten", 3)),
            min_abstand_sekunden=max(2.0, float(s.get("min_abstand_sekunden", 4))),
            max_anfragen_pro_lauf=int(s.get("max_anfragen_pro_lauf", 60)),
            kaufalarm_freigegeben=bool(s.get("kaufalarm_freigegeben", False)),
            versand_de=Versand(status, staffel, v.get("hinweis", ""), v.get("quelle", ""), v.get("geprueft_am", "")),
            pruefung=dict(s.get("pruefung", {})),
        ))
    if not shops:
        raise KonfigFehler("Keine Shops konfiguriert")
    return Konfig(shops=shops, produkte=produkte, ausschluss_domains=domains, ausschluss_namen=namen)
