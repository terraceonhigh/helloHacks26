#!/usr/bin/env bash
# Standalone downloader for hub/sync_cli.py: no `git clone`, no full repo -
# just the 4 files a real Canvas/PrairieLearn login actually needs
# (hub/site.py, hub/models.py, hub/canvas.py, hub/prairielearn.py,
# hub/sync_cli.py itself), fetched straight from GitHub into a scratch dir.
# Usage: curl -fsSL <raw-url-to-this-file> | bash
set -euo pipefail

REPO="${HUB_SYNC_REPO:-terraceonhigh/helloHacks26}"
BRANCH="${HUB_SYNC_BRANCH:-main}"
RAW="https://raw.githubusercontent.com/$REPO/$BRANCH"
DIR="$(mktemp -d)/ubc-hub-sync"
mkdir -p "$DIR/hub"

for f in hub/__init__.py hub/site.py hub/models.py hub/canvas.py hub/prairielearn.py hub/sync_cli.py; do
  curl -fsSL "$RAW/$f" -o "$DIR/$f"
done

cd "$DIR"
uv run --with requests,beautifulsoup4,"playwright>=1.63.0" python -m playwright install chromium
uv run --with requests,beautifulsoup4,"playwright>=1.63.0" hub/sync_cli.py "$@"
