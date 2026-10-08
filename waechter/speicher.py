"""Dauerhafte Speicherung (Anforderung 5) – einfache Textdateien im Repository.

data/zustand.json            letzter bekannter Stand je Angebot, Wiederholsperre, Host-Pausen
data/verlauf/JJJJ-MM.jsonl   Preis-/Bestandsverlauf: ein Eintrag je Änderung (und je Abruffehler),
                             immer mit Zeitstempel und Quellenlink
data/ereignisse.jsonl        erkannte Ereignisse (Restock, Vorbestellung, Preisrückgang)
data/laeufe.jsonl            Zusammenfassung jedes Prüflaufs

JSON-Lines-Dateien werden nur ergänzt, nie überschrieben.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ZUSTAND_VERSION = 1


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
        self._anhaengen(self.dir / "laeufe.jsonl", [eintrag])

    def lies_jsonl(self, name: str) -> list[dict]:
        pfad = self.dir / name
        if not pfad.exists():
            return []
        return [json.loads(z) for z in pfad.read_text(encoding="utf-8").splitlines() if z.strip()]
