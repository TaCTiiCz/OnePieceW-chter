#!/usr/bin/env bash
# Läuft vor jedem Start des Wächters (ExecStartPre, als Benutzer "waechter"):
#  1. neuesten Zustand übernehmen – falls GitHub eingesprungen ist, während der Server stand,
#  2. Herzschlag setzen, damit GitHub keine neuen Abschnitte mehr startet,
#  3. einen gerade laufenden GitHub-Abschnitt auslaufen lassen (sonst kämen Meldungen doppelt).
set -uo pipefail
source "$(dirname "$0")/gemeinsam.sh"

uebernehmen() {
  als git -C "$DATEN" fetch -q origin waechter-daten || { log "GitHub nicht erreichbar – starte mit lokalem Zustand"; return 0; }
  local fern lokal
  fern=$(als git -C "$DATEN" show origin/waechter-daten:status.json 2>/dev/null | alter_min -)
  lokal=$( [ -f "$DATEN/status.json" ] && alter_min "$DATEN/status.json" || echo 99999)
  if [ "$fern" -lt "$lokal" ]; then
    log "Zustand auf GitHub ist neuer ($fern Min. gegenüber $lokal Min.) – wird übernommen"
    als git -C "$DATEN" reset -q --hard origin/waechter-daten
  fi
}

uebernehmen
zustand_sichern || true

# Laufende/wartende GitHub-Abschnitte auslaufen lassen (höchstens ~15 Min.). Das Repository ist öffentlich,
# die Abfrage braucht keinen Token.
github_aktiv() {
  curl -fsS --max-time 20 "https://api.github.com/repos/${WAECHTER_REPO}/actions/workflows/waechter.yml/runs?per_page=10" \
    | python3 -c 'import json,sys; print(sum(r["status"] in ("in_progress","queued","pending","waiting","requested") for r in json.load(sys.stdin)["workflow_runs"]))' \
    2>/dev/null || echo -1
}
for _ in $(seq 1 15); do
  n=$(github_aktiv)
  if [ "$n" = "0" ]; then break; fi
  if [ "$n" = "-1" ]; then   # GitHub-API nicht erreichbar: am Alter der letzten GitHub-Meldung orientieren
    als git -C "$DATEN" fetch -q origin waechter-daten || break
    q=$(als git -C "$DATEN" show origin/waechter-daten:status.json 2>/dev/null | quelle)
    a=$(als git -C "$DATEN" show origin/waechter-daten:status.json 2>/dev/null | alter_min -)
    { [ "$q" = "github" ] && [ "$a" -lt 12 ]; } || break
  fi
  log "Auf GitHub läuft noch ein Abschnitt – warte, bis er fertig ist …"
  sleep 60
done
uebernehmen
log "Start frei."
