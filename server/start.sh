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

# Laufende/wartende GitHub-Abschnitte auslaufen lassen. Läuft GitHub nach ~18 Min. immer noch, ist BETRIEB=server
# nicht gesetzt: dann startet der Server NICHT (systemd versucht es erneut) – Server und GitHub laufen nie parallel.
github_aktiv() {
  local tok auth=()
  tok=$(sed -nE 's#https://x-access-token:([^@]*)@github.com#\1#p' "$BASIS/.git-credentials" 2>/dev/null | head -1)
  [ -n "$tok" ] && auth=(-H "Authorization: Bearer $tok")   # mit Token 5000 statt 60 Abfragen pro Stunde
  curl -fsS --max-time 20 "${auth[@]}" "https://api.github.com/repos/${WAECHTER_REPO}/actions/workflows/waechter.yml/runs?per_page=10" \
    | python3 -c 'import json,sys; print(sum(r["status"] in ("in_progress","queued","pending","waiting","requested") for r in json.load(sys.stdin)["workflow_runs"]))' \
    2>/dev/null || echo -1
}
frei=false
for _ in $(seq 1 "${WAECHTER_WARTE_MAX:-18}"); do
  n=$(github_aktiv)
  if [ "$n" = "0" ]; then frei=true; break; fi
  if [ "$n" = "-1" ]; then   # GitHub-API nicht erreichbar: am Alter der letzten GitHub-Meldung orientieren
    als git -C "$DATEN" fetch -q origin waechter-daten || { frei=true; break; }
    q=$(als git -C "$DATEN" show origin/waechter-daten:status.json 2>/dev/null | quelle)
    a=$(als git -C "$DATEN" show origin/waechter-daten:status.json 2>/dev/null | alter_min -)
    if ! { [ "$q" = "github" ] && [ "$a" -lt 12 ]; }; then frei=true; break; fi
  fi
  log "Auf GitHub läuft noch ein Abschnitt – warte, bis er fertig ist …"
  sleep "${WAECHTER_WARTE_SEK:-60}"
  uebernehmen && zustand_sichern >/dev/null 2>&1 || true   # neueren GitHub-Stand zuerst übernehmen, dann Herzschlag erneuern
done
if [ "$frei" != true ]; then
  # GitHub prüft nach ~18 Min. immer noch: dann ist BETRIEB=server (noch) nicht gesetzt. Nicht parallel laufen –
  # systemd versucht es nach 30 Sekunden erneut.
  log "GitHub prüft weiter. Ist auf GitHub die Variable BETRIEB=server gesetzt? Neuer Versuch gleich."
  exit 1
fi
uebernehmen
log "Start frei."
