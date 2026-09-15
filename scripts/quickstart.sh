#!/usr/bin/env bash
# One-command local quickstart: creates a venv, installs deps, and runs the
# historian with SQLite storage. For a container-based deploy, use
# `docker compose up -d` instead — see README.md.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

mkdir -p data
export ACKIOLOGS_DATABASE_URL="${ACKIOLOGS_DATABASE_URL:-sqlite+aiosqlite:///./data/ackiologs.db}"

echo "Starting Ackiologs at http://localhost:8000 (Ctrl+C to stop)"
echo "First run creates a default admin user — watch the log for its generated password."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
