"""Capture real screenshots of the running dashboard (and API docs) with Playwright/Chromium.

Usage: python scripts/capture_screenshots.py --dashboard http://127.0.0.1:8501 --api http://127.0.0.1:8000 \
       --out docs/screenshots
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGES = [
    ("overview", ""),
    ("activity", "activity"),
    ("diagnoses", "diagnoses"),
    ("observations", "observations"),
    ("quality", "quality"),
    ("pipeline", "pipeline"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dashboard", default="http://127.0.0.1:8501")
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--out", default="docs/screenshots")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=2000)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    exe = os.environ.get("CHROMIUM_PATH")
    with sync_playwright() as p:
        browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
        # Streamlit scrolls inside its own container, so a tall viewport is what captures the whole page.
        page = browser.new_page(viewport={"width": a.width, "height": a.height}, device_scale_factor=1)
        for name, path in PAGES:
            page.goto(f"{a.dashboard}/{path}", wait_until="networkidle")
            page.wait_for_selector("text=Release", timeout=30000)
            page.wait_for_function("() => !document.querySelector('[data-testid=\"stStatusWidget\"]')", timeout=30000)
            page.wait_for_timeout(2500)  # let Vega charts finish drawing
            page.screenshot(path=str(out / f"dashboard-{name}.png"), full_page=True)
            print(f"captured dashboard-{name}.png")
        page.goto(f"{a.api}/docs", wait_until="networkidle")
        page.wait_for_selector("text=HealthLake API", timeout=30000)
        page.wait_for_timeout(1500)
        page.screenshot(path=str(out / "api-docs.png"), full_page=False)
        print("captured api-docs.png")
        browser.close()


if __name__ == "__main__":
    main()
