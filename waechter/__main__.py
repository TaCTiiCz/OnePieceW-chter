"""Befehlszeile:

  python -m waechter pruefen               Live-Prüflauf (braucht Internet; in GitHub Actions)
  python -m waechter pruefen --testdaten   Probelauf mit gespeicherten Beispieldaten (ohne Internet)
  python -m waechter bericht               Bericht aus gespeichertem Stand neu erzeugen
  python -m waechter konfig                Konfiguration prüfen und anzeigen
  python -m waechter telegram-test         Testnachricht an Telegram senden
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import telegram
from .abruf import Abrufer, TestdatenAbrufer
from .bericht import erzeuge_bericht
from .konfig import PROJEKT, KonfigFehler, lade_konfig
from .lauf import fuehre_aus
from .speicher import Speicher

TESTDATEN_DIR = PROJEKT / "tests" / "fixtures"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="waechter", description="One-Piece-TCG-Wächter")
    sub = p.add_subparsers(dest="befehl", required=True)
    pr = sub.add_parser("pruefen", help="Prüflauf starten")
    pr.add_argument("--testdaten", action="store_true", help="gespeicherte Beispieldaten statt Internet verwenden")
    pr.add_argument("--daten", default=None, help="Datenverzeichnis (Standard: data/ bzw. testlauf/data)")
    pr.add_argument("--bericht", default=None, help="Berichtsdatei (Standard: reports/latest.md)")
    pr.add_argument("--ohne-telegram", action="store_true", help="in diesem Lauf nichts an Telegram senden")
    be = sub.add_parser("bericht", help="Bericht neu erzeugen")
    be.add_argument("--daten", default=str(PROJEKT / "data"))
    be.add_argument("--bericht", default=str(PROJEKT / "reports" / "latest.md"))
    sub.add_parser("konfig", help="Konfiguration prüfen")
    sub.add_parser("telegram-test", help="Testnachricht senden")
    hp = sub.add_parser("haendler-pruefen", help="Händlerkandidaten live prüfen (Händlerdatenbank)")
    hp.add_argument("--ausgabe", default=str(PROJEKT / "data" / "haendler_db.json"))
    hp.add_argument("--nur-neue", action="store_true", help="nur noch nicht geprüfte Kandidaten")
    hp.add_argument("--parallel", type=int, default=8)
    args = p.parse_args(argv)

    if args.befehl == "haendler-pruefen":
        from .haendlerdb import pruefe_alle
        abrufer = Abrufer({}, protokoll=print, pausen=(5.0, 20.0))
        z = pruefe_alle(abrufer, Path(args.ausgabe), nur_neue=args.nur_neue, parallel=args.parallel)
        print(json.dumps(z, ensure_ascii=False, indent=1))
        return 0

    try:
        konfig = lade_konfig()
    except KonfigFehler as e:
        print(f"Konfigurationsfehler: {e}", file=sys.stderr)
        return 2

    if args.befehl == "konfig":
        for s in konfig.shops:
            print(f"- {s.id}: {s.name} ({s.basis_url}), Land {s.land}, Kaufalarme "
                  f"{'freigegeben' if s.kaufalarm_freigegeben else 'NICHT freigegeben'}, Versand DE: {s.versand_de.status}")
        print(f"Ausgeschlossen: {', '.join(konfig.ausschluss_domains)}")
        print(telegram.konfiguration()[1])
        return 0

    if args.befehl == "telegram-test":
        aktiv, info = telegram.konfiguration()
        print(info)
        if not aktiv:
            return 1
        ok, info = telegram.sende("✅ Testnachricht vom One-Piece-TCG-Wächter. Telegram ist richtig eingerichtet.")
        print(info)
        return 0 if ok else 1

    if args.befehl == "bericht":
        sp = Speicher(Path(args.daten))
        Path(args.bericht).parent.mkdir(parents=True, exist_ok=True)
        Path(args.bericht).write_text(erzeuge_bericht(konfig, sp.lade_zustand()), encoding="utf-8")
        print(f"Bericht geschrieben: {args.bericht}")
        return 0

    # pruefen
    if args.testdaten:
        basis = PROJEKT / "testlauf"
        daten = Path(args.daten) if args.daten else basis / "data"
        bericht = Path(args.bericht) if args.bericht else basis / "bericht_testdaten.md"
        if not args.daten and daten.exists():
            shutil.rmtree(daten)  # Testlauf startet immer frisch und berührt nie data/
        abrufer = TestdatenAbrufer(TESTDATEN_DIR)
        print("ACHTUNG: Testdaten-Lauf – keine Live-Prüfung, kein Internet, keine echten Preise.")
    else:
        daten = Path(args.daten) if args.daten else PROJEKT / "data"
        bericht = Path(args.bericht) if args.bericht else PROJEKT / "reports" / "latest.md"
        abrufer = Abrufer({}, protokoll=print)
    sp = Speicher(daten)
    zus = fuehre_aus(konfig, abrufer, sp, testdaten=args.testdaten, telegram_senden=not args.ohne_telegram)
    bericht.parent.mkdir(parents=True, exist_ok=True)
    bericht.write_text(erzeuge_bericht(konfig, sp.lade_zustand()), encoding="utf-8")
    print(f"Fertig: {zus['beobachtungen']} Beobachtungen, {len(zus['ereignisse'])} Ereignisse. Bericht: {bericht}")
    print(zus["telegram"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
