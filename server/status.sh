#!/usr/bin/env bash
# Kurzer Überblick: läuft der Wächter, wann war der letzte Lauf, wann der letzte Abgleich?
source "${WAECHTER_BASIS:-/opt/waechter}/code/server/gemeinsam.sh"
echo "Wächter-Dienst:   $(systemctl is-active waechter)"
echo "Abgleich (Timer): $(systemctl is-active waechter-sync.timer)"
[ -f "$DATEN/status.json" ] && echo "Letzter Lauf:     vor $(alter_min "$DATEN/status.json") Min. (Quelle: $(quelle < "$DATEN/status.json"))"
[ -f "$DATEN/server.json" ] && echo "Letzter Abgleich: $(cat "$DATEN/server.json")"
echo "Code-Version:     $(als git -C "$CODE" log -1 --format='%h %cd %s' --date=format:'%d.%m. %H:%M')"
echo
echo "Letzte Meldungen des Wächters:"
journalctl -u waechter -n 15 --no-pager -o cat 2>/dev/null || true
