"""Dauerhafte Speicherung (Anforderung 5) – einfache Textdateien im Repository.

data/zustand.json            letzter bekannter Stand je Angebot, Wiederholsperre, Host-Pausen
data/verlauf/JJJJ-MM.jsonl   Preis-/Bestandsverlauf: ein Eintrag je Änderung (und je Abruffehler),
                             immer mit Zeitstempel und Quellenlink
data/ereignisse.jsonl        erkannte Ereignisse (Restock, Vorbestellung, Preisrückgang)
data/laeufe.jsonl            KURZE Zusammenfassung jedes Prüflaufs (nur die letzten MAX_LAEUFE Einträge)

JSON-Lines-Dateien werden ergänzt. laeufe.jsonl wird gekürzt: GitHub nimmt keine Dateien über 100 MB an
(am 19.10.2026 war die Datei mit vollständigen Shop-Berichten auf 104,8 MB gewachsen -> Speichern scheiterte).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ZUSTAND_VERSION = 1
MAX_LAEUFE = 5000          # ca. 1–2 Wochen Läufe, wenige MB
KUERZEN_AB_BYTES = 10_000_000


def kompakter_lauf(e: dict) -> dict:
    """Nur Kennzahlen – die vollständigen Shop-Berichte stehen im Zustand (letzter_lauf) und im Bericht."""
    if "shops_mit_fehler" in e or ("shops" not in e and "ereignisse" not in e):
        return e   # schon kompakt
    shops = e.get("shops") or {}
    fehler = {sid: str(b.get("fehler", [])[-1])[:120] for sid, b in shops.items()
              if isinstance(b, dict) and b.get("fehler")}
    ereig = e.get("ereignisse")
    return {"zeit": e.get("zeit"), "testdaten": e.get("testdaten"), "beobachtungen": e.get("beobachtungen"),
            "ereignisse": len(ereig) if isinstance(ereig, list) else ereig,
            "shops": len(shops) if isinstance(shops, dict) else shops, "shops_mit_fehler": fehler,
            "uebersprungen": len(e.get("uebersprungen") or []) if isinstance(e.get("uebersprungen"), list) else e.get("uebersprungen"),
            "telegram_gesendet": e.get("telegram_gesendet"), "telegram_fehler": e.get("telegram_fehler"),
            "telegram": e.get("telegram")}


def kuerze_laeufe(datei: Path, max_zeilen: int | None = None) -> None:
    """Alte Einträge kompakt umschreiben und nur die letzten max_zeilen behalten."""
    if not datei.exists() or datei.stat().st_size < KUERZEN_AB_BYTES:   # günstig: erst ab 10 MB umschreiben
        return
    max_zeilen = max_zeilen or MAX_LAEUFE
    zeilen = [z for z in datei.read_text(encoding="utf-8").splitlines() if z.strip()]
    neu = []
    for z in zeilen[-max_zeilen:]:
        try:
            neu.append(json.dumps(kompakter_lauf(json.loads(z)), ensure_ascii=False, sort_keys=True))
        except ValueError:
            continue
    tmp = datei.with_suffix(".tmp")
    tmp.write_text("\n".join(neu) + ("\n" if neu else ""), encoding="utf-8")
    os.replace(tmp, datei)


class Speicher:
    def __init__(self, verzeichnis: Path):
        self.dir = Path(verzeichnis)
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "verlauf").mkdir(exist_ok=True)

    @property
    def zustand_datei(self) -> Path:
        return self.dir / "zustand.json"

    def lade_zustand(self) -> dict:
        if self.zustand_datei.exists():
            z = json.loads(self.zustand_datei.read_text(encoding="utf-8"))
        else:
            z = {}
        z.setdefault("version", ZUSTAND_VERSION)
        z.setdefault("angebote", {})
        z.setdefault("shops", {})
        z.setdefault("hosts", {})
        z.setdefault("meldungen", {})
        return z

    def speichere_zustand(self, zustand: dict) -> None:
        tmp = self.zustand_datei.with_suffix(".tmp")
        tmp.write_text(json.dumps(zustand, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, self.zustand_datei)

    def _anhaengen(self, datei: Path, eintraege: list[dict]) -> None:
        if not eintraege:
            return
        with open(datei, "a", encoding="utf-8") as f:
            for e in eintraege:
                f.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")

    def verlauf(self, eintraege: list[dict], monat: str) -> None:
        self._anhaengen(self.dir / "verlauf" / f"{monat}.jsonl", eintraege)

    def ereignisse(self, eintraege: list[dict]) -> None:
        self._anhaengen(self.dir / "ereignisse.jsonl", eintraege)

    def lauf(self, eintrag: dict) -> None:
        datei = self.dir / "laeufe.jsonl"
        self._anhaengen(datei, [kompakter_lauf(eintrag)])
        kuerze_laeufe(datei)

    def lies_jsonl(self, name: str) -> list[dict]:
        pfad = self.dir / name
        if not pfad.exists():
            return []
        return [json.loads(z) for z in pfad.read_text(encoding="utf-8").splitlines() if z.strip()]
