#!/usr/bin/env bash
# =====================================================================
#  TCG-Wächter: Einrichtung auf einem eigenen Linux-Server (Ubuntu 22.04/24.04, z. B. Oracle Cloud Free Tier)
#
#  Aufruf auf dem Server:
#    curl -fsSL https://raw.githubusercontent.com/TaCTiiCz/OnePieceW-chter/main/server/install.sh -o install.sh
#    sudo bash install.sh
#
#  Fragt nach: Telegram-Bot-Token, Telegram-Chat-ID, GitHub-Token (fine-grained, nur dieses Repository,
#  Contents: Read and write). Kann gefahrlos erneut ausgeführt werden (z. B. um einen Token zu tauschen).
# =====================================================================
set -euo pipefail
REPO="${REPO:-TaCTiiCz/OnePieceW-chter}"
BASIS=/opt/waechter

rot() { printf '\033[31m%s\033[0m\n' "$*"; }
gruen() { printf '\033[32m%s\033[0m\n' "$*"; }
schritt() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

[ "$(id -u)" = 0 ] || { rot "Bitte mit sudo starten: sudo bash install.sh"; exit 1; }

schritt "1/7 Pakete installieren (git, Python)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git python3 ca-certificates curl >/dev/null
python3 -c 'import sys; assert sys.version_info >= (3, 11)' || { rot "Python 3.11 oder neuer nötig (Ubuntu 24.04 verwenden)."; exit 1; }
gruen "Python $(python3 -c 'import platform; print(platform.python_version())') ist bereit."

schritt "2/7 Benutzer 'waechter' anlegen"
if ! id waechter >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "$BASIS" --shell /usr/sbin/nologin waechter
fi
mkdir -p "$BASIS" /etc/waechter
chown waechter:waechter "$BASIS"
timedatectl set-timezone Europe/Berlin 2>/dev/null || true

schritt "3/7 Zugangsdaten (Eingaben werden nicht angezeigt)"
ALT=/etc/waechter/waechter.env
alt_wert() {
  if [ "$1" = GITHUB_TOKEN ]; then
    [ -f "$BASIS/.git-credentials" ] && sed -E 's#https://x-access-token:([^@]*)@github.com#\1#' "$BASIS/.git-credentials" | head -1 || true
  else
    [ -f "$ALT" ] && grep -E "^$1=" "$ALT" | head -1 | cut -d= -f2- || true
  fi
}
frage() {  # frage VARIABLE "Text" [geheim]
  local vorhanden; vorhanden=$(alt_wert "$1")
  local hinweis=""; [ -n "$vorhanden" ] && hinweis=" (Enter = bisherigen Wert behalten)"
  local wert
  if [ "${3:-}" = geheim ]; then read -rsp "$2$hinweis: " wert; echo; else read -rp "$2$hinweis: " wert; fi
  wert="${wert:-$vorhanden}"
  [ -n "$wert" ] || { rot "Ohne $1 geht es nicht."; exit 1; }
  printf -v "$1" '%s' "$wert"
}
frage TELEGRAM_BOT_TOKEN "Telegram-Bot-Token (von @BotFather, Form 123456:ABC…)" geheim
frage TELEGRAM_CHAT_ID   "Telegram-Chat-ID (Zahl, z. B. 123456789)"
frage GITHUB_TOKEN       "GitHub-Token (beginnt mit github_pat_)" geheim

curl -fsS --max-time 15 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" >/dev/null \
  && gruen "Telegram-Token ist gültig." || { rot "Telegram-Token wird abgelehnt – bitte prüfen."; exit 1; }
recht=$(curl -fsS --max-time 15 -H "Authorization: Bearer ${GITHUB_TOKEN}" "https://api.github.com/repos/${REPO}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("permissions",{}).get("push", False))' 2>/dev/null || echo "Fehler")
if [ "$recht" = "True" ]; then gruen "GitHub-Token darf in $REPO schreiben."
else rot "GitHub-Token passt nicht (Ergebnis: $recht). Nötig: Zugriff auf $REPO, Contents: Read and write."; exit 1; fi

umask 077
cat > "$ALT" <<ENV
TELEGRAM_AKTIV=true
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
WAECHTER_QUELLE=server
WAECHTER_REPO=${REPO}
WAECHTER_BETRIEB=/opt/waechter/code/config/betrieb_server.toml
PYTHONUNBUFFERED=1
ENV
chmod 600 "$ALT"
umask 022

# Git-Zugang für den Benutzer waechter (Token liegt nur hier, nicht in der Umgebung des Wächters)
printf 'https://x-access-token:%s@github.com\n' "$GITHUB_TOKEN" > "$BASIS/.git-credentials"
chown waechter:waechter "$BASIS/.git-credentials"; chmod 600 "$BASIS/.git-credentials"
runuser -u waechter -- git config --global credential.helper store
runuser -u waechter -- git config --global user.name "onepiece-waechter[server]"
runuser -u waechter -- git config --global user.email "41898282+github-actions[bot]@users.noreply.github.com"
runuser -u waechter -- git config --global init.defaultBranch main

schritt "4/7 Programm und Daten von GitHub holen"
URL="https://github.com/${REPO}.git"
if [ -d "$BASIS/code/.git" ]; then
  runuser -u waechter -- git -C "$BASIS/code" fetch -q origin main
  runuser -u waechter -- git -C "$BASIS/code" reset -q --hard origin/main
else
  runuser -u waechter -- git clone -q "$URL" "$BASIS/code"
fi
if [ ! -d "$BASIS/daten/.git" ]; then
  if runuser -u waechter -- git ls-remote --exit-code --heads "$URL" waechter-daten >/dev/null; then
    runuser -u waechter -- git clone -q --branch waechter-daten --single-branch "$URL" "$BASIS/daten"
  else
    runuser -u waechter -- git init -q -b waechter-daten "$BASIS/daten"
    runuser -u waechter -- git -C "$BASIS/daten" remote add origin "$URL"
  fi
fi
if [ ! -d "$BASIS/seite/.git" ]; then
  runuser -u waechter -- git init -q -b dojo-seite "$BASIS/seite"
  runuser -u waechter -- git -C "$BASIS/seite" remote add origin "$URL"
fi
gruen "Code: $(runuser -u waechter -- git -C "$BASIS/code" log -1 --format='%h %s')"

schritt "5/7 Kurztest (Testdaten, ohne Internet-Abrufe bei Händlern)"
( cd "$BASIS/code" && runuser -u waechter -- python3 -m unittest discover -s tests -q 2>&1 | tail -3 )

schritt "6/7 Dienste einrichten und starten"
cp "$BASIS/code/server/waechter.service" "$BASIS/code/server/waechter-sync.service" "$BASIS/code/server/waechter-sync.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now waechter-sync.timer >/dev/null
systemctl enable waechter >/dev/null
systemctl restart waechter --no-block
gruen "Dienste eingerichtet. Der Wächter startet, sobald GitHub pausiert (Variable BETRIEB=server, laufender Abschnitt endet)."

schritt "7/7 Telegram-Bestätigung"
curl -fsS --max-time 15 -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d chat_id="${TELEGRAM_CHAT_ID}" \
  --data-urlencode text="🖥️ Wächter-Server ist eingerichtet ($(hostname)). Er startet, sobald GitHub pausiert (Variable BETRIEB=server) – das dauert bis zu 15 Minuten." >/dev/null \
  && gruen "Testnachricht an Telegram geschickt." || rot "Telegram-Nachricht fehlgeschlagen – Chat-ID prüfen."

echo
gruen "Fertig. Nächster Schritt laut Anleitung: auf GitHub die Variable BETRIEB=server anlegen."
echo "Status jederzeit:  sudo bash /opt/waechter/code/server/status.sh"
echo "Live-Protokoll:    sudo journalctl -u waechter -f"
