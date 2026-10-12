#!/usr/bin/env bash
# Alle 5 Minuten (waechter-sync.timer, als root):
#  1. Zustand + Herzschlag in den Zweig waechter-daten hochladen (für Ausfallsicherung und Verlauf),
#  2. alle 10 Minuten das Dojo (index.html + status.json) in den Zweig dojo-seite (GitHub Pages),
#  3. Code-Updates von main holen und den Wächter bei Bedarf neu starten.
# Alles steht in main(), damit ein Code-Update dieses Skript nicht mitten im Lauf verändert.
set -uo pipefail
main() {
  source "${WAECHTER_BASIS:-/opt/waechter}/code/server/gemeinsam.sh"

  # 1) Zustand
  if systemctl is-active --quiet waechter; then
    zustand_sichern || true
  fi

  # 2) Dojo-Seite (höchstens ~6 Veröffentlichungen pro Stunde, GitHub-Pages-Grenze ist 10)
  if { [ $(( 10#$(date -u +%M) % 10 )) -lt 5 ] || [ "${WAECHTER_DOJO_SOFORT:-0}" = 1 ]; } && [ -f "$DATEN/status.json" ]; then
    for f in index.html status.json icon.png .nojekyll; do
      [ -f "$DATEN/$f" ] && cp "$DATEN/$f" "$SEITE/$f"
    done
    chown -R waechter:waechter "$SEITE"
    als git -C "$SEITE" add -A
    if ! als git -C "$SEITE" diff --cached --quiet; then
      als git -C "$SEITE" commit -q --amend -m "Dojo" 2>/dev/null || als git -C "$SEITE" commit -q -m "Dojo"
      als git -C "$SEITE" push -q --force origin dojo-seite || log "Dojo konnte nicht veröffentlicht werden"
    fi
  fi

  # 3) Code-Updates
  als git -C "$CODE" fetch -q origin main || { log "GitHub nicht erreichbar"; return 0; }
  local alt neu
  alt=$(als git -C "$CODE" rev-parse HEAD); neu=$(als git -C "$CODE" rev-parse origin/main)
  [ "$alt" = "$neu" ] && return 0
  local geaendert; geaendert=$(als git -C "$CODE" diff --name-only "$alt" "$neu")
  als git -C "$CODE" reset -q --hard origin/main
  if echo "$geaendert" | grep -qE '^server/.*\.(service|timer)$'; then
    cp "$CODE"/server/*.service "$CODE"/server/*.timer /etc/systemd/system/
    systemctl daemon-reload
  fi
  # Neustart nur bei Programm- oder Einstellungsänderungen (nicht bei der täglichen Händlerdatenbank)
  if echo "$geaendert" | grep -qE '^(waechter|server)/|^config/.*\.toml$'; then
    log "Neue Version ($neu) – Wächter wird neu gestartet"
    zustand_sichern || true
    systemctl restart waechter
  fi
}
main "$@"
exit 0
