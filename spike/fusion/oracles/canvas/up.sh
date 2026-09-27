#!/usr/bin/env bash
# Canvas has no oracle server in this spike (no published image; a source build
# does not fit the machine). Nothing to bring up. This script only regenerates
# the fixture snapshot from the SYNTHETIC fixtures, so it stays idempotent.
set -euo pipefail
cd "$(dirname "$0")/../.."
echo "canvas: no live server (see oracles/canvas/README.md); regenerating fixtures/snapshots/canvas.json"
uv run python oracles/canvas_fixture_snapshot.py
