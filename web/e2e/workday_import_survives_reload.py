"""E2E oracle: imported Workday courses must survive load() (Sample toggle).

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
        expect(page.get_by_text("(Sample data.)")).to_be_visible()

        page.locator('input[type="file"]').set_input_files(str(FIXTURE))
        expect(page.get_by_text("Imported 3 courses.")).to_be_visible()
        page.get_by_role("button", name="Courses", exact=True).click()
        expect(page.locator(".course-card h2", has_text="FAKE 100")).to_be_visible()
        expect(page.locator(".course-card h2", has_text="CPSC 121")).to_be_visible()

        toggle = page.get_by_label("Sample data")
        toggle.uncheck()
        expect(page.get_by_text("(Local mode")).to_be_visible()
        toggle.check()
        expect(page.get_by_text("(Sample data.)")).to_be_visible()
        # Wait for the Sample load() to land before judging the Workday rows.
        expect(page.locator(".course-card h2", has_text="CPSC 121")).to_be_visible()
        page.wait_for_timeout(500)

        codes = page.locator(".course-card h2").all_inner_texts()
        browser.close()
    missing = [c for c in ("FAKE 100", "FAKE 200", "FAKE 300") if not any(t.startswith(c) for t in codes)]
    print("course cards after Sample off/on:", codes)
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
        print(f"FAIL: imported Workday courses wiped by load(): {missing}")
        return 1
    print("PASS: imported Workday courses survived Sample off/on")
    return 0


if __name__ == "__main__":
    sys.exit(main())
