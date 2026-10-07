"""Befehlszeile:

  python -m waechter pruefen               Live-Prüflauf (braucht Internet; in GitHub Actions)
  python -m waechter pruefen --testdaten   Probelauf mit gespeicherten Beispieldaten (ohne Internet)
  python -m waechter bericht               Bericht aus gespeichertem Stand neu erzeugen
  python -m waechter konfig                Konfiguration prüfen und anzeigen
  python -m waechter telegram-test         Testnachricht an Telegram senden
  python -m waechter haendler-pruefen      Händlerdatenbank live prüfen
  python -m waechter lauf                  EIN Naruto-Prüflauf (fällige Aufgaben, danach Ende) + One Piece, wenn fällig
  python -m waechter dauerlauf             Dauerbetrieb für einen eigenen Server (prüft alle 1-3 Minuten)
  python -m waechter simulation            Simulierter Restock bis zur Test-Pushmeldung, misst die Verzögerung
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
import time
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
    for name, hilfe in (("lauf", "ein Naruto-Prüflauf"), ("dauerlauf", "Dauerbetrieb (eigener Server)")):
        lp = sub.add_parser(name, help=hilfe)
        lp.add_argument("--daten", default=str(PROJEKT / "laufzeit"), help="Verzeichnis für Zustand/Verlauf")
        lp.add_argument("--db", default=str(PROJEKT / "data" / "haendler_db.json"))
        lp.add_argument("--dashboard", default=None, help="Dashboard-Datei (Standard: <daten>/dashboard.md)")
        lp.add_argument("--ohne-onepiece", action="store_true")
        lp.add_argument("--ohne-push", action="store_true")
        lp.add_argument("--alle", action="store_true", help="alle Aufgaben ausführen, nicht nur fällige (Erstlauf)")
        lp.add_argument("--max-sekunden", type=int, default=0, help="Zeitlimit dieses Laufs (Standard aus betrieb.toml)")
        if name == "dauerlauf":
            lp.add_argument("--sekunden", type=int, default=0, help="Laufzeit begrenzen (0 = unbegrenzt)")
    sub.add_parser("haendler-suchen", help="neue Händler über die Brave-Search-API suchen (optional)")
    si = sub.add_parser("simulation", help="simulierter Restock bis zur Test-Pushmeldung")
    si.add_argument("--telegram-echt", action="store_true", help="echte Telegram-API benutzen (Nachricht ist als TEST markiert)")
    si.add_argument("--intervall", type=float, default=5.0)
    si.add_argument("--daten", default=None, help="Ergebnis im Zustand dieses Verzeichnisses vermerken (Dashboard)")
    args = p.parse_args(argv)

    if args.befehl == "simulation":
        from .simulation import simuliere
        e = simuliere(telegram_echt=args.telegram_echt, intervall=args.intervall)
        print("\n".join(e.get("schritte", [])))
        print(json.dumps({k: v for k, v in e.items() if k not in ("schritte", "pushtext")}, ensure_ascii=False, indent=1))
        if e.get("pushtext"):
            print("--- Test-Pushmeldung ---\n" + e["pushtext"])
        if args.daten:
            zd = Path(args.daten) / "zustand.json"
            z = json.loads(zd.read_text(encoding="utf-8")) if zd.exists() else {}
            z.setdefault("push", {})["letzter_test"] = {k: e.get(k) for k in ("zeit", "ok", "wechsel_bis_push_s",
                                                                               "erkennung_bis_push_ms", "kanal")}
            zd.parent.mkdir(parents=True, exist_ok=True)
            zd.write_text(json.dumps(z, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        return 0 if e.get("ok") else 1

    if args.befehl == "haendler-suchen":
        from .suche import suche
        suche()
        return 0

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

    if args.befehl in ("lauf", "dauerlauf"):
        daten = Path(args.daten)
        dash = Path(args.dashboard) if args.dashboard else daten / "dashboard.md"
        ende = time.monotonic() + args.sekunden if getattr(args, "sekunden", 0) else None
        while True:
            naechste = naruto_lauf(konfig, daten, Path(args.db), dash, onepiece=not args.ohne_onepiece,
                                   ohne_push=args.ohne_push, alle=args.alle, max_sekunden=args.max_sekunden)
            if args.befehl == "lauf":
                return 0
            warte = max(20.0, min(60.0, naechste))
            if ende and time.monotonic() + warte > ende:
                return 0
            time.sleep(warte)

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


def naruto_lauf(konfig, daten: Path, db: Path, dash: Path, onepiece: bool = True, ohne_push: bool = False,
                log=print, alle: bool = False, max_sekunden: int = 0) -> float:
    """Ein Lauf. Gibt die Sekunden bis zur nächsten fälligen Aufgabe zurück."""
    from . import dashboard as dashmod
    from . import push as pushmod
    from .naruto_lauf import Lauf, erledigt, lade_haendler

    kanal = pushmod.Kanal("Telegram", False, None, "für diesen Lauf abgeschaltet") if ohne_push else None
    # kurze Wiederholung im Lauf; längere, wachsende Abstände übernimmt der Planer über mehrere Läufe
    abrufer = Abrufer({}, protokoll=log, pausen=(5.0,))
    l = Lauf(konfig, abrufer, daten, db_datei=db, push_kanal=kanal, log=log, onepiece=onepiece)
    if max_sekunden:
        l.betrieb["grenzen"]["max_laufzeit_sekunden"] = max_sekunden
    info = l.ausfuehren(nur_faellige=not alle)
    jetzt = dt.datetime.now(dt.timezone.utc)
    if onepiece and info.get("onepiece_faellig") and "onepiece" in l.zustand["aufgaben"]:
        log("One-Piece-Prüfung ist fällig …")
        sp = Speicher(daten / "onepiece")
        try:
            fuehre_aus(konfig, Abrufer({}, protokoll=log, pausen=(5.0,)), sp, telegram_senden=not ohne_push, log=log)
            (daten / "onepiece_bericht.md").write_text(erzeuge_bericht(konfig, sp.lade_zustand()), encoding="utf-8")
            erledigt(l.zustand["aufgaben"]["onepiece"], True, jetzt, l.betrieb)
        except Exception as ex:
            erledigt(l.zustand["aufgaben"]["onepiece"], False, jetzt, l.betrieb, f"{type(ex).__name__}: {ex}")
    l.speichern()
    db_json = json.loads(db.read_text(encoding="utf-8")) if db.exists() else {}
    dash.parent.mkdir(parents=True, exist_ok=True)
    import os
    op = os.path.relpath(daten / "onepiece_bericht.md", dash.parent) if (daten / "onepiece_bericht.md").exists() else None
    dash.write_text(dashmod.erzeuge(l.zustand, lade_haendler(konfig, db), db_json, l.ncfg, l.betrieb,
                                    dt.datetime.now(dt.timezone.utc), op), encoding="utf-8")
    faellig = [dt.datetime.fromisoformat(a["faellig"]) for a in l.zustand["aufgaben"].values()]
    return max(0.0, (min(faellig) - dt.datetime.now(dt.timezone.utc)).total_seconds()) if faellig else 60.0


if __name__ == "__main__":
    sys.exit(main())
