#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

command -v python3 >/dev/null || { echo "python3 is required"; exit 1; }
command -v ffmpeg >/dev/null || { echo "ffmpeg is required. Install with: sudo apt install ffmpeg"; exit 1; }
command -v ffprobe >/dev/null || { echo "ffprobe is required. Install with: sudo apt install ffmpeg"; exit 1; }
command -v node >/dev/null || { echo "Node.js 20+ is required"; exit 1; }
command -v npm >/dev/null || { echo "npm is required"; exit 1; }

NODE_MAJOR="$(node -p 'Number(process.versions.node.split(".")[0])')"
if (( NODE_MAJOR < 20 )); then
  echo "Node.js 20+ is required; found $(node --version)"
  exit 1
fi

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"

(
  cd remotion
  npm install
)

mkdir -p var/work var/logs
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env. Add Google Drive service-account path and mailbox folder ID."
fi

echo
echo "Bootstrap complete. Next:"
echo "  nano .env"
echo "  source .venv/bin/activate"
echo "  render-worker doctor"
echo "  render-worker setup-drive"
