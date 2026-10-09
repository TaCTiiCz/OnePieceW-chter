"""Alarm-Test: löst für Naruto und/oder One Piece einen deutlich markierten TEST-Alarm aus.

- Telegram: je Wächter eine Nachricht „🧪 TEST …“ (nur wenn Telegram eingerichtet ist).
- Dojo: die Test-Ereignisse landen im Zustand, die Statusdatei wird neu geschrieben. Das Dojo zeigt den Alarm
  etwa 15 Minuten lang (Ninja bzw. Seemann springen auf, bei One Piece schwenkt die Katze die Piratenfahne).
Es werden keine Shops abgerufen, und echte Zustände (Angebote, Alarm-Sperren) bleiben unberührt.
"""

from __future__ import annotations

import datetime as dt
import html
import json
from pathlib import Path
from typing import Callable, Optional

from . import dojo, telegram

TESTS = {
    "naruto": ("KAUFALARM", "Naruto Card Game Booster Display (EN) jetzt vorbestellbar",
               "🚨 <b>🧪 TEST – NARUTO-KAUFALARM</b>\nDas ist nur ein Test des Wächters. Es ist nichts bestellbar."),
    "onepiece": ("OP_RESTOCK", "One Piece OP16 Display (EN) wieder lieferbar",
                 "🟢 <b>🧪 TEST – ONE-PIECE-RESTOCK</b>\nDas ist nur ein Test des Wächters. Es ist nichts bestellbar."),
}


def ausfuehren(daten: Path, ziel_dir: Path, *, welche=("naruto", "onepiece"), senden: bool = True,
               jetzt: Optional[dt.datetime] = None, sender: Callable[[str], tuple[bool, str]] = telegram.sende,
               log: Callable[[str], None] = print) -> bool:
    jetzt = jetzt or dt.datetime.now(dt.timezone.utc)
    zd = Path(daten) / "zustand.json"
    z = json.loads(zd.read_text(encoding="utf-8")) if zd.exists() else {}
    z.setdefault("aufgaben", {})
    if "onepiece" in welche:
        z["aufgaben"].setdefault("onepiece", {"art": "onepiece", "shop": "onepiece", "url": "", "zuletzt_ok": jetzt.isoformat(),
                                              "fehlerserie": 0})
    kurz = z.setdefault("ereignisse_kurz", [])
    alles_ok = True
    aktiv, info = telegram.konfiguration()
    for name in welche:
        typ, text, nachricht = TESTS[name]
        kurz.append({"zeit": jetzt.replace(microsecond=0).isoformat(), "typ": typ, "text": "🧪 TEST: " + text,
                     "testmodus": True})
        if not senden:
            log(f"{name}: Test-Alarm im Dojo, Telegram nicht verlangt")
        elif not aktiv:
            log(f"{name}: Test-Alarm im Dojo, aber {info}")
            alles_ok = False
        else:
            ok, i = sender(nachricht + "\n" + html.escape(text))
            log(f"{name}: Telegram {'gesendet' if ok else 'FEHLGESCHLAGEN'} ({i})")
            alles_ok = alles_ok and ok
    zd.parent.mkdir(parents=True, exist_ok=True)
    zd.write_text(json.dumps(z, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    dojo.schreibe(z, Path(ziel_dir), jetzt)
    log("Dojo-Status geschrieben.")
    return alles_ok
