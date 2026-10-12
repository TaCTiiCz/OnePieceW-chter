# shellcheck shell=bash disable=SC2034
# Gemeinsame Helfer für start.sh / sync.sh / status.sh (wird per "source" geladen).
BASIS=${WAECHTER_BASIS:-/opt/waechter}
CODE=$BASIS/code
DATEN=$BASIS/daten
SEITE=$BASIS/seite
WAECHTER_REPO=${WAECHTER_REPO:-TaCTiiCz/OnePieceW-chter}

# Führt einen Befehl als Benutzer "waechter" aus (oder direkt, wenn wir das schon sind).
als() {
  if [ "$(id -un)" = "waechter" ]; then "$@"; else runuser -u waechter -- "$@"; fi
}

log() { echo "[$(date -u +%H:%M:%S)] $*"; }

# Minuten seit dem Zeitstempel "updated" in einer status.json (Datei oder "-" für stdin); 99999 = unbekannt.
alter_min() {
  python3 -c '
import datetime as d, json, sys
q = sys.argv[1]
j = json.load(sys.stdin if q == "-" else open(q, encoding="utf-8"))
t = d.datetime.fromisoformat(str(j.get("updated") or j.get("heartbeat")).replace("Z", "+00:00"))
t = t if t.tzinfo else t.replace(tzinfo=d.timezone.utc)
print(int((d.datetime.now(d.timezone.utc) - t).total_seconds() // 60))
' "$1" 2>/dev/null || echo 99999
}

# Quelle ("server"/"github") einer status.json
quelle() {
  python3 -c 'import json,sys; print(json.load(sys.stdin).get("quelle","github"))' 2>/dev/null || echo "?"
}

# Zustand (Zweig waechter-daten) sichern: ein Commit pro Tag, im Tagesverlauf ergänzt, dann force-push.
zustand_sichern() {
  local heute; heute=$(date -u +%Y-%m-%d)
  printf '{"heartbeat": "%s", "host": "%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(hostname)" > "$DATEN/server.json"
  [ "$(id -un)" = "waechter" ] || chown waechter:waechter "$DATEN/server.json"
  als git -C "$DATEN" add -A
  if als git -C "$DATEN" diff --cached --quiet; then return 0; fi
  if als git -C "$DATEN" log -1 --format=%s 2>/dev/null | grep -q "Wächter-Daten $heute"; then
    als git -C "$DATEN" commit -q --amend -m "Wächter-Daten $heute"
  else
    als git -C "$DATEN" commit -q -m "Wächter-Daten $heute"
  fi
  als git -C "$DATEN" push -q --force origin waechter-daten || { log "Zustand konnte nicht hochgeladen werden"; return 1; }
}
