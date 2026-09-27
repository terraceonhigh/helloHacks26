"""Run the Canvas adapter over the SYNTHETIC fixtures and save fixtures/snapshots/canvas.json.

Not an oracle in the usual sense: there's no live Canvas to compare against.
Usage: uv run python oracles/canvas_fixture_snapshot.py
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fusion.adapters import canvas  # noqa: E402
from fusion.snapshot_io import save  # noqa: E402
from tests.canvas_fake import FakeCanvas  # noqa: E402

# fixed fetched_at so the saved snapshot is reproducible
FETCHED_AT = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)

if __name__ == "__main__":
    fake = FakeCanvas()
    snap = canvas.fetch(fake, fake.base, now=FETCHED_AT)
    out = ROOT / "fixtures" / "snapshots" / "canvas.json"
    save(snap, out)
    print(f"wrote {out}: {len(snap.courses)} course(s), {len(snap.items)} item(s), notes={list(snap.notes)}")
    for i in snap.items:
        print(f"  {i.source_id:18} {i.kind:10} {i.due.isoformat() if i.due else '-':25} {i.title}  links_out={list(i.links_out)}")
