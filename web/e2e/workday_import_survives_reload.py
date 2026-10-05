"""E2E oracle: an imported Workday schedule must survive load() (Sample toggle).

Workday feeds the Schedule tab only, not the course list (no assignment
data ever comes from it, so a Workday-only course card would be
misleading) - this checks that the recurring class meetings load() a
Workday .xlsx produces aren't wiped by a Sample-mode round trip, the same
risk the courses used to carry before that changed.

Drives the real built page. Builds with NEXT_PUBLIC_HUB_API pointed at a dead
local port so the Sample-data toggle renders (it only shows in local mode);
the local fetch then fails fast, which is fine - we only assert after
switching back to Sample.

    uv run playwright install chromium   # once
    (cd web && npm ci)                   # once
    uv run python web/e2e/workday_import_survives_reload.py [--no-build]

Not named test_*.py on purpose: bare `uv run pytest` would collect it and
try to run next build. Exit 0 = pass, 1 = the bug reproduces.
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

WEB = Path(__file__).resolve().parent.parent
FIXTURE = WEB.parent / "fixtures" / "workday_view_my_courses.xlsx"
PORT = int(os.environ.get("E2E_PORT", "3917"))
ENV = {**os.environ, "NEXT_PUBLIC_HUB_API": "http://127.0.0.1:9", "NEXT_TELEMETRY_DISABLED": "1"}


def wait_for_port(port, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return
        except OSError:
            time.sleep(0.3)
    raise RuntimeError(f"next start never listened on {port}")


def run_scenario(url):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url)
        page.get_by_role("button", name="Settings", exact=True).click()
        # Checkbox state, not wording - immune to headline copy changes
        # (this script previously broke silently when that copy changed
        # elsewhere, unrelated to Workday - not what this oracle is for).
        toggle = page.get_by_label("Sample data")
        expect(toggle).to_be_checked()

        page.locator('input[type="file"]').set_input_files(str(FIXTURE))
        expect(page.get_by_text("Loaded 4 class meetings.")).to_be_visible()
        page.get_by_role("button", name="Schedule", exact=True).click()
        expect(page.locator("text=BMEG 000").first).to_be_visible()

        # Settings (and so the toggle) unmounts once we navigated to
        # Schedule above - re-open it before touching the toggle again.
        page.get_by_role("button", name="Settings", exact=True).click()
        toggle.uncheck()
        expect(toggle).not_to_be_checked()
        toggle.check()
        expect(toggle).to_be_checked()
        # Wait for the Sample load() to land, then back to Schedule to judge it.
        page.wait_for_timeout(500)
        page.get_by_role("button", name="Schedule", exact=True).click()

        courses = page.locator(".rounded-lg.border").all_inner_texts()
        browser.close()
    missing = [c for c in ("BMEG 000", "BMEG 001", "BMEG 002") if not any(c in t for t in courses)]
    print("Schedule tab contents after Sample off/on:", courses)
    return missing


def main():
    if "--no-build" not in sys.argv:
        subprocess.run(["npx", "next", "build"], cwd=WEB, env=ENV, check=True)
    server = subprocess.Popen(
        ["npx", "next", "start", "-p", str(PORT), "-H", "127.0.0.1"],
        cwd=WEB, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    try:
        wait_for_port(PORT)
        missing = run_scenario(f"http://127.0.0.1:{PORT}/")
    finally:
        server.terminate()
        server.wait(timeout=10)
    if missing:
        print(f"FAIL: imported Workday schedule wiped by load(): {missing}")
        return 1
    print("PASS: imported Workday schedule survived Sample off/on")
    return 0


if __name__ == "__main__":
    sys.exit(main())
