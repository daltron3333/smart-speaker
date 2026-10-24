#!/usr/bin/env bash
# Installs (or updates) the speaker on a Raspberry Pi 5 running Raspberry Pi OS Lite 64-bit.
# Run it on the Pi from the copied project folder:  bash deploy/setup_pi.sh
# Safe to run again after changing the code; it keeps the API key, logs and models.
set -euo pipefail

APP=/opt/pi-speaker
SRC="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE=/etc/pi-speaker/env

echo "== System packages"
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev libportaudio2 espeak-ng alsa-utils rsync

echo "== Service user"
if ! id speaker >/dev/null 2>&1; then
  sudo useradd --system --home-dir "$APP" --shell /usr/sbin/nologin --groups audio speaker
fi

echo "== Code"
sudo mkdir -p "$APP/logs" "$APP/models"
sudo rsync -a --delete --exclude .venv --exclude .git --exclude .env --exclude logs --exclude models \
  --exclude __pycache__ "$SRC/" "$APP/app/"

echo "== Python packages (this takes a while the first time)"
[ -d "$APP/venv" ] || sudo python3 -m venv "$APP/venv"
sudo "$APP/venv/bin/pip" install --upgrade pip
sudo "$APP/venv/bin/pip" install -r "$APP/app/requirements-pi.txt"
# --no-deps skips tflite-runtime, which has no wheels for newer Pythons; we use ONNX instead.
sudo "$APP/venv/bin/pip" install --no-deps openwakeword

echo "== Models"
sudo env SPEAKER_DATA_DIR="$APP" HF_HOME="$APP/models/hf" PYTHONPATH="$APP/app" \
  "$APP/venv/bin/python" -m speaker setup-models
sudo chown -R speaker:speaker "$APP/logs" "$APP/models"

echo "== API key file"
sudo mkdir -p "$(dirname "$ENV_FILE")"
if [ ! -f "$ENV_FILE" ]; then
  echo "ANTHROPIC_API_KEY=" | sudo tee "$ENV_FILE" >/dev/null
fi
sudo chown root:root "$ENV_FILE"
sudo chmod 600 "$ENV_FILE"

echo "== Service and the 'speaker' test command"
sudo install -m 755 "$APP/app/deploy/speaker" /usr/local/bin/speaker
sudo cp "$APP/app/deploy/pi-speaker.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable pi-speaker

if sudo grep -q '^ANTHROPIC_API_KEY=$' "$ENV_FILE"; then
  echo
  echo "Almost done. Add your API key, then start the speaker:"
  echo "  sudo nano $ENV_FILE"
  echo "  sudo systemctl restart pi-speaker"
else
  sudo systemctl restart pi-speaker
  echo "Speaker restarted. Follow it with:  journalctl -u pi-speaker -f"
fi
