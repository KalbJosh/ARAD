#!/bin/bash
# Auf dem Fujitsu unter Linux Mint ausführen, solange der Bildschirm dran ist.
# Internet ist erst beim folgenden Start mit angeschlossenem LAN nötig.
set -euo pipefail

if [ "$(uname -s)" != Linux ] || ! command -v systemctl >/dev/null 2>&1 || ! command -v apt-get >/dev/null 2>&1; then
    echo "Dieses Skript bitte auf dem Fujitsu unter Linux Mint starten, nicht auf dem Mac."
    exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "Bitte jetzt dein Linux-Mint-Passwort eingeben (beim Tippen unsichtbar)."
    exec sudo bash "$0" "$@"
fi

trap 'echo "FEHLER: Vorbereitung nicht abgeschlossen. Bitte die Fehlermeldung oben prüfen und das Skript erneut starten." >&2' ERR

install -d -m 755 /usr/local/sbin
cat > /usr/local/sbin/setup-ssh-once.sh <<'SSH_SCRIPT'
#!/bin/bash
until apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20 update &&
      env DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server &&
      systemctl enable --now ssh &&
      systemctl is-active --quiet ssh
do
    echo "SSH noch nicht bereit. Neuer Versuch in 20 Sekunden."
    sleep 20
done
systemctl disable setup-ssh-once.service
SSH_SCRIPT
chmod 755 /usr/local/sbin/setup-ssh-once.sh

cat > /etc/systemd/system/setup-ssh-once.service <<'SSH_SERVICE'
[Unit]
Description=Install SSH when network becomes available
After=NetworkManager.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/setup-ssh-once.sh
TimeoutStartSec=infinity
Restart=on-failure
RestartSec=20

[Install]
WantedBy=multi-user.target
SSH_SERVICE

systemctl daemon-reload
systemctl enable setup-ssh-once.service
systemctl is-enabled setup-ssh-once.service
echo
echo "FERTIG: Die Vorbereitung ist auf dem Fujitsu gespeichert."
echo "Der USB-Stick wird beim nächsten Start nicht mehr benötigt."
echo "Dein Benutzername für SSH: ${SUDO_USER:-root}"
echo
echo "1. Jetzt mit 'sudo poweroff' herunterfahren."
echo "2. LAN-Kabel mit Internetzugang anschließen und den Fujitsu einschalten."
echo "3. Einige Minuten warten. SSH wird automatisch mit Root-Rechten installiert."
echo "   Es ist keine weitere Eingabe am Fujitsu nötig."
echo "4. IP-Adresse des Fujitsu in der Geräteliste des Routers nachsehen."
echo "5. Am Mac: ssh ${SUDO_USER:-BENUTZERNAME}@IP-ADRESSE"
echo "   Dafür das Linux-Mint-Passwort verwenden."
