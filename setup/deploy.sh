#!/bin/bash
# ARAD Bridge + Webseiten auf den Autodarts-Rechner spielen (Linux, ohne sudo).
#   bash setup/deploy.sh benutzer@rechner
# Legt beim ersten Mal Node (LTS), Piper (Caller-Stimme) und ein TLS-Zertifikat unter ~/.local bzw.
# ~/.config an und richtet den Benutzerdienst arad-bridge ein (startet dank Linger ohne Anmeldung).
# calibration.json und der Sprach-Cache auf dem Rechner bleiben bei jedem Deploy erhalten.
#
# Optional: setup/local.env mit eigenen Standardwerten, z. B.
#   ARAD_HOST=benutzer@192.168.0.10
#   ARAD_SSH_KEY=~/.ssh/id_ed25519
#   ARAD_KNOWN_HOSTS=/pfad/zu/known_hosts
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f setup/local.env ] && . setup/local.env
HOST=${1:-${ARAD_HOST:-}}
[ -n "$HOST" ] || { echo "Aufruf: bash setup/deploy.sh benutzer@rechner   (oder ARAD_HOST in setup/local.env)"; exit 1; }
SSH=(ssh)
[ -n "${ARAD_SSH_KEY:-}" ] && SSH+=(-i "${ARAD_SSH_KEY/#\~/$HOME}" -o IdentitiesOnly=yes)
[ -n "${ARAD_KNOWN_HOSTS:-}" ] && SSH+=(-o StrictHostKeyChecking=yes -o UserKnownHostsFile="$ARAD_KNOWN_HOSTS")

rsync -az --delete --exclude calibration.json --exclude tts-cache -e "${SSH[*]}" bridge web "$HOST":arad/
rsync -az -e "${SSH[*]}" systemd/arad-bridge.user.service "$HOST":.config/systemd/user/arad-bridge.service

"${SSH[@]}" "$HOST" 'bash -s' <<'REMOTE'
set -euo pipefail
NODE=~/.local/opt/node/bin/node
if ! [ -x "$NODE" ] || [ "$("$NODE" -p 'process.versions.node.split(".")[0]')" -lt 22 ]; then
  echo "== Node LTS installieren"
  V=$(curl -fsSL https://nodejs.org/dist/index.json | python3 -c 'import json,sys; print(next(r["version"] for r in json.load(sys.stdin) if r["lts"]))')
  mkdir -p ~/.local/opt && cd ~/.local/opt
  curl -fsSL "https://nodejs.org/dist/$V/node-$V-linux-x64.tar.xz" | tar -xJ
  rm -rf node && mv "node-$V-linux-x64" node
fi
echo "Node $("$NODE" -v)"
if ! [ -x ~/.local/opt/piper/piper ]; then
  echo "== Piper (Caller-Stimme) installieren"
  curl -fsSL https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz | tar -xz -C ~/.local/opt
fi
V=~/.local/opt/piper/voices/en_GB-northern_english_male-medium.onnx
if ! [ -s "$V" ]; then
  mkdir -p ~/.local/opt/piper/voices
  B=https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/northern_english_male/medium/en_GB-northern_english_male-medium
  curl -fsSL -o "$V" "$B.onnx" && curl -fsSL -o "$V.json" "$B.onnx.json"
fi
T=~/.config/arad/tls
if ! [ -s $T/cert.pem ]; then
  echo "== TLS-Zertifikat für die Kalibrierseite erzeugen"
  mkdir -p $T
  IPS=$(hostname -I | tr ' ' '\n' | grep -E '^[0-9.]+$' | sed 's/^/IP:/' | paste -sd,)
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -keyout $T/key.pem -out $T/cert.pem \
    -subj "/CN=arad" -addext "subjectAltName=DNS:$(hostname).local,$IPS" 2>/dev/null
fi
loginctl show-user "$USER" -p Linger | grep -q yes || loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable arad-bridge >/dev/null 2>&1
systemctl --user restart arad-bridge
sleep 1
systemctl --user is-active arad-bridge
IP=$(hostname -I | awk '{print $1}')
echo "Beamer: http://$IP:8090/    Handy: http://$IP:8090/remote"
REMOTE
