#!/usr/bin/env python3
"""
slide_watcher.py

Monitors current_slide.html for changes.
On each change:
  1. Saves a timestamped copy to  ./versions/slide_NNNN_YYYYMMDD_HHMMSS.html
  2. Takes a screenshot → ./images/slide_NNNN.png  (requires playwright or wkhtmltoimage)

Usage:
    python slide_watcher.py [--slide current_slide.html] [--lecture my_lecture]

Options:
    --slide    Path to watch            (default: ./current_slide.html)
    --lecture  Lecture name / folder    (default: lecture)
                  versions saved to ./<lecture>/versions/
                  images   saved to ./<lecture>/images/

Screenshot backend (tries in order):
  1. Playwright  (pip install playwright && playwright install chromium)
  2. wkhtmltoimage  (must be on PATH)
  3. No screenshot (just saves HTML versions)
"""

import argparse
import os
import sys
import time
import shutil
import subprocess
import threading
from datetime import datetime

# ---------------------------------------------------------------------------
# Screenshot helpers
# ---------------------------------------------------------------------------

def screenshot_playwright(html_path: str, png_path: str) -> bool:
    """Take a screenshot using Playwright (headless Chromium)."""
    try:
        from playwright.sync_api import sync_playwright
        abs_html = os.path.abspath(html_path)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.goto(f"file:///{abs_html}")
            # Wait for images to load
            page.wait_for_timeout(1500)
            page.screenshot(path=png_path, full_page=False)
            browser.close()
        return True
    except Exception as e:
        print(f"[screenshot/playwright] {e}", file=sys.stderr)
        return False


def screenshot_wkhtmltoimage(html_path: str, png_path: str) -> bool:
    """Take a screenshot using wkhtmltoimage."""
    try:
        # todo if windows if linux
        result = subprocess.run(
            ["c:/Program Files/wkhtmltopdf/bin/wkhtmltoimage.exe", "--width", "1280", html_path, png_path],
            capture_output=True, timeout=15
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[screenshot/wkhtmltoimage] {e}", file=sys.stderr)
        return False


def take_screenshot(html_path: str, png_path: str) -> bool:
    """Try all screenshot backends in order."""
    if screenshot_playwright(html_path, png_path):
        return True
    if screenshot_wkhtmltoimage(html_path, png_path):
        return True
    print("[screenshot] no backend available — install playwright or wkhtmltoimage", file=sys.stderr)
    return False


# ---------------------------------------------------------------------------
# Watcher
# ---------------------------------------------------------------------------

class SlideWatcher:
    def __init__(self, slide_path: str, lecture_name: str):
        self.slide_path = slide_path
        self.lecture_name = lecture_name

        base = os.path.join(os.path.dirname(slide_path), lecture_name)
        self.versions_dir = os.path.join(base, "versions")
        self.images_dir = os.path.join(base, "images")
        os.makedirs(self.versions_dir, exist_ok=True)
        os.makedirs(self.images_dir, exist_ok=True)

        self.counter = self._find_next_counter()
        self.last_mtime = None
        self._lock = threading.Lock()

        print(f"[watcher] slide   : {slide_path}", file=sys.stderr)
        print(f"[watcher] versions: {self.versions_dir}", file=sys.stderr)
        print(f"[watcher] images  : {self.images_dir}", file=sys.stderr)
        print(f"[watcher] next #  : {self.counter:04d}", file=sys.stderr)

    def _find_next_counter(self) -> int:
        """Resume numbering from where we left off."""
        existing = [
            f for f in os.listdir(self.versions_dir)
            if f.startswith("slide_") and f.endswith(".html")
        ]
        if not existing:
            return 1
        nums = []
        for name in existing:
            parts = name.split("_")
            if len(parts) >= 2:
                try:
                    nums.append(int(parts[1]))
                except ValueError:
                    pass
        return max(nums) + 1 if nums else 1

    def _on_change(self, html_content: str):
        with self._lock:
            n = self.counter
            self.counter += 1

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        html_name = f"slide_{n:04d}_{ts}.html"
        png_name = f"slide_{n:04d}.png"

        html_dest = os.path.join(self.versions_dir, html_name)
        png_dest = os.path.join(self.images_dir, png_name)

        # Save HTML version
        with open(html_dest, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"[watcher] saved version: {html_name}", file=sys.stderr)

        # Take screenshot (in a thread so watcher loop stays fast)
        def _shoot():
            ok = take_screenshot(html_dest, png_dest)
            if ok:
                print(f"[watcher] screenshot : {png_name}", file=sys.stderr)

        threading.Thread(target=_shoot, daemon=True).start()

    def run(self, poll_interval: float = 0.3):
        print("[watcher] running… (Ctrl+C to stop)", file=sys.stderr)
        while True:
            try:
                if os.path.exists(self.slide_path):
                    mtime = os.path.getmtime(self.slide_path)
                    if mtime != self.last_mtime:
                        self.last_mtime = mtime
                        with open(self.slide_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        self._on_change(content)
            except KeyboardInterrupt:
                print("\n[watcher] stopped.", file=sys.stderr)
                break
            except Exception as e:
                print(f"[watcher] error: {e}", file=sys.stderr)
            time.sleep(poll_interval)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Watch current_slide.html and archive versions + screenshots")
    parser.add_argument("--slide", default="current_slide.html",
                        help="Path to the slide file to watch  (default: ./current_slide.html)")
    parser.add_argument("--lecture", default="lecture",
                        help="Lecture name — used as the folder name for versions/images  (default: lecture)")
    args = parser.parse_args()

    watcher = SlideWatcher(slide_path=args.slide, lecture_name=args.lecture)
    watcher.run()
