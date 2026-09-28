#!/usr/bin/env bash
# Lauds with your own data, on this laptop only. Run it from a checkout of main:
#   bash tools/real-data.sh        then open http://localhost:3000 (not 127.0.0.1)
# Logins open a real browser window you sign in to yourself. Sessions and data
# stay in ~/.ubc-hub/ (mode 600), never in the repo.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
uv sync
uv run playwright install chromium        # no-op if already installed
(cd web && npm ci)   # always: a node_modules from an older checkout breaks next dev
uv run python -m hub.api & API=$!
trap 'kill $API 2>/dev/null' EXIT
cd web && NEXT_PUBLIC_HUB_API=http://localhost:8000 npm run dev
