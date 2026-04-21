#!/bin/bash
# PHOTONForge app launcher — run on Yoga 910
# Usage: ./launch_app.sh [--bg]
set -euo pipefail

REPO_DIR="${HOME}/PHOTONFORGE_Photo-Workflow"
APP_DIR="$REPO_DIR/photonforge-gui"
LOG_FILE="/tmp/tauri-dev.log"
PID_FILE="/tmp/tauri-dev.pid"

# Load nvm so node/npm are available
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
if [ -d "$NVM_DIR" ]; then
  # shellcheck source=/dev/null
  source "$NVM_DIR/nvm.sh" 2>/dev/null || true
fi

# Ensure PATH includes nvm node and cargo/rust binaries
export PATH="$HOME/.nvm/versions/node/v20.20.2/bin:$HOME/.cargo/bin:$PATH"

cd "$APP_DIR"

# ---------------------------------------------------------------------------
# 1. Kill any existing dev session
# ---------------------------------------------------------------------------
if [ -f "$PID_FILE" ]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null)"
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "Killing previous dev server (PID $OLD_PID)..."
    kill "$OLD_PID" 2>/dev/null || true
    sleep 2
  fi
fi

# Kill any stray Tauri/Vite processes holding port 1420
echo "Cleaning up stray processes..."
for pid in $(ps aux | grep -v grep | grep -E 'tauri|vite|photonforge' | awk '{print $2}'); do
  kill "$pid" 2>/dev/null || true
done
sleep 2

# Free port 1420 if something's still holding it
for pid in $(lsof -ti:1420 2>/dev/null || true); do
  kill -9 "$pid" 2>/dev/null || true
done

# ---------------------------------------------------------------------------
# 2. Rebuild sidecar binary
# ---------------------------------------------------------------------------
echo "Rebuilding sidecar binary..."
bash "$REPO_DIR/scripts/build_sidecar.sh"

# ---------------------------------------------------------------------------
# 3. Pull latest commits
# ---------------------------------------------------------------------------
echo "Pulling latest commits..."
git pull --ff-only 2>&1 || echo "WARNING: git pull failed — continuing with current checkout"

# ---------------------------------------------------------------------------
# 4. Install any new npm deps
# ---------------------------------------------------------------------------
echo "Installing npm dependencies..."
npm install --silent 2>&1 | tail -3 || true

# ---------------------------------------------------------------------------
# 5. Start Tauri dev server
# ---------------------------------------------------------------------------
rm -f "$LOG_FILE"
echo "Starting Tauri dev server..."

if [ "${1:-}" = "--bg" ]; then
  nohup npm run tauri dev > "$LOG_FILE" 2>&1 &
  DEV_PID=$!
  echo "$DEV_PID" > "$PID_FILE"
  echo "Started with PID $DEV_PID — logs at $LOG_FILE"

  # Wait for app to be ready (look for "Running" or a cargo process)
  echo "Waiting for app to start (up to 60s)..."
  for i in $(seq 1 30); do
    if grep -qE 'Running|error|Error' "$LOG_FILE" 2>/dev/null; then
      sleep 2
      if grep -q 'Running' "$LOG_FILE" 2>/dev/null; then
        echo "App is ready!"
        tail -10 "$LOG_FILE"
        exit 0
      fi
    fi
    sleep 2
    echo "  ...waiting ($i/30)"
  done
  echo "WARNING: App may not have started cleanly — check $LOG_FILE"
  tail -20 "$LOG_FILE"
else
  echo "Starting Tauri dev server (foreground)..."
  npm run tauri dev 2>&1
fi
