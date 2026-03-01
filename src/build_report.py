#!/usr/bin/env python3
"""
build_report.py

Takes a folder of numbered HTML slides (produced by slide_watcher.py)
and combines them into:
  1. A single styled HTML report with print page-breaks  → report.html
  2. A PDF of that report                                → report.pdf
     (requires playwright OR wkhtmltopdf on PATH)

The slides are embedded in the same visual style as the presenter,
so the report looks identical to what was on screen.

Usage:
    python build_report.py --versions ./lecture/versions --images ./lecture/images --out ./lecture

Options:
    --versions   Folder containing slide_NNNN_*.html files
    --images     Folder containing slide_NNNN.png files  (optional, for embedding)
    --out        Output folder for report.html / report.pdf  (default: same as --versions)
    --title      Report title  (default: "Lecture Report")
    --no-pdf     Skip PDF generation
"""

import argparse
import os
import re
import sys
import base64
import subprocess
from datetime import datetime

# ---------------------------------------------------------------------------
# CSS — same look as presenter, but with page breaks for print
# ---------------------------------------------------------------------------

REPORT_CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap');

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Georgia', serif;
    background: #0d1117;
    color: #e6edf3;
  }

  .report-title {
    text-align: center;
    padding: 64px 48px 32px;
    font-size: 2.2rem;
    color: #58a6ff;
    border-bottom: 2px solid #21262d;
    margin-bottom: 0;
  }

  .report-meta {
    text-align: center;
    font-size: 0.85rem;
    color: #484f58;
    padding: 12px 0 48px;
  }

  /* ── Each slide block ── */
  .slide-page {
    page-break-after: always;
    break-after: page;
    min-height: 96vh;
    display: flex;
    flex-direction: column;
    border-bottom: 1px solid #21262d;
  }

  .slide-page:last-child {
    page-break-after: avoid;
    break-after: avoid;
    border-bottom: none;
  }

  .slide-number {
    font-size: 0.7rem;
    color: #30363d;
    text-align: right;
    padding: 8px 64px 0;
  }

  .slide-wrapper {
    display: flex;
    flex: 1;
    padding: 36px 64px 20px 64px;
    gap: 48px;
    align-items: flex-start;
  }

  .slide-left {
    flex: 1 1 55%;
    display: flex;
    flex-direction: column;
    gap: 24px;
  }

  h1 {
    font-size: 2.2rem;
    font-weight: 700;
    line-height: 1.2;
    color: #58a6ff;
    border-bottom: 3px solid #58a6ff44;
    padding-bottom: 14px;
  }

  ul {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  ul li {
    font-size: 1.15rem;
    line-height: 1.5;
    padding-left: 28px;
    position: relative;
    color: #cdd9e5;
  }

  ul li::before {
    content: '▸';
    position: absolute;
    left: 0;
    color: #58a6ff;
    font-size: 0.9rem;
    top: 3px;
  }

  p {
    font-size: 0.95rem;
    color: #8b949e;
    line-height: 1.6;
    font-style: italic;
  }

  .slide-right {
    flex: 0 0 36%;
    display: flex;
    align-items: flex-start;
    justify-content: center;
  }

  img {
    max-width: 100%;
    max-height: 400px;
    border-radius: 10px;
    border: 2px solid #30363d;
    box-shadow: 0 8px 32px #00000088;
    object-fit: cover;
  }

  .slide-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 64px;
    border-top: 1px solid #21262d;
    font-size: 0.75rem;
    color: #484f58;
  }

  .slide-footer a { color: #58a6ff; text-decoration: none; }
  .logo {
    font-weight: 700;
    font-size: 1rem;
    color: #58a6ff;
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }

  @media print {
    body { background: #0d1117 !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  }
</style>
"""


# ---------------------------------------------------------------------------
# Slide parser
# ---------------------------------------------------------------------------

def parse_slide_html(raw_html: str) -> dict:
    """Extract components from a raw minimal slide HTML."""
    body_match = re.search(r"<body[^>]*>(.*?)</body>", raw_html, re.S | re.I)
    body = body_match.group(1).strip() if body_match else raw_html

    img_match = re.search(r"(<img[^>]*>)", body, re.S | re.I)
    img_html = img_match.group(1) if img_match else ""

    source_match = re.search(r'(<p class="source">.*?</p>)', body, re.S | re.I)
    source_html = source_match.group(1) if source_match else ""

    left = body
    if img_html:
        left = left.replace(img_html, "")
    if source_html:
        left = left.replace(source_html, "")

    title_match = re.search(r"<title>(.*?)</title>", raw_html, re.I)
    title = title_match.group(1) if title_match else "Slide"

    return {
        "title": title,
        "left": left.strip(),
        "img_html": img_html,
        "source_html": source_html,
    }


def embed_local_image(img_html: str, images_dir: str, slide_num: int) -> str:
    """
    If a local screenshot PNG exists for this slide number, embed it as base64.
    Otherwise return the original img_html (which has an external URL).
    """
    if not images_dir:
        return img_html
    png_path = os.path.join(images_dir, f"slide_{slide_num:04d}.png")
    if os.path.exists(png_path):
        with open(png_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f'<img src="data:image/png;base64,{b64}" alt="Slide {slide_num} screenshot">'
    return img_html


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def find_slides(versions_dir: str) -> list:
    """
    Find all slide_NNNN_*.html files, return sorted list of (number, path).
    """
    files = []
    for name in os.listdir(versions_dir):
        m = re.match(r"slide_(\d+)_.*\.html$", name)
        if m:
            files.append((int(m.group(1)), os.path.join(versions_dir, name)))
    # Sort by slide number, then by filename (timestamp) to get last version per number
    files.sort(key=lambda x: (x[0], x[1]))
    # Deduplicate: keep only the LAST file per slide number
    seen = {}
    for num, path in files:
        seen[num] = path
    return sorted(seen.items())


def build_slide_block(num: int, path: str, images_dir: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    s = parse_slide_html(raw)
    img_html = embed_local_image(s["img_html"], images_dir, num) if images_dir else s["img_html"]
    right_col = f"<div class='slide-right'>{img_html}</div>" if img_html else ""

    return f"""
<div class="slide-page">
  <div class="slide-number">#{num:04d}</div>
  <div class="slide-wrapper">
    <div class="slide-left">
      {s["left"]}
    </div>
    {right_col}
  </div>
  <div class="slide-footer">
    <span class="logo">&#9670; Live Lecture</span>
    {s["source_html"]}
    <span>Slide {num}</span>
  </div>
</div>"""


def build_report_html(slides: list, images_dir: str, report_title: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    blocks = "\n".join(
        build_slide_block(num, path, images_dir) for num, path in slides
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{report_title}</title>
  {REPORT_CSS}
</head>
<body>
  <h1 class="report-title">{report_title}</h1>
  <p class="report-meta">Generated {now} &mdash; {len(slides)} slides</p>
  {blocks}
</body>
</html>"""


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------

def pdf_playwright(html_path: str, pdf_path: str) -> bool:
    try:
        from playwright.sync_api import sync_playwright
        abs_html = os.path.abspath(html_path)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(f"file:///{abs_html}", wait_until="networkidle")
            page.pdf(
                path=pdf_path,
                format="A4",
                landscape=True,
                print_background=True,
            )
            browser.close()
        return True
    except Exception as e:
        print(f"[pdf/playwright] {e}", file=sys.stderr)
        return False


def pdf_wkhtmltopdf(html_path: str, pdf_path: str) -> bool:
    try:
        result = subprocess.run( 
            ["c:/Program Files/wkhtmltopdf/bin/wkhtmltopdf.exe",
             "--page-size", "A4",
             "--orientation", "Landscape",
             "--enable-local-file-access",
             html_path, pdf_path],
            capture_output=True, timeout=60
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[pdf/wkhtmltopdf] {e}", file=sys.stderr)
        return False


def generate_pdf(html_path: str, pdf_path: str) -> bool:
    if pdf_playwright(html_path, pdf_path):
        return True
    if pdf_wkhtmltopdf(html_path, pdf_path):
        return True
    print("[pdf] no PDF backend available — install playwright or wkhtmltopdf", file=sys.stderr)
    return False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Combine lecture slides into HTML report + PDF")
    parser.add_argument("--versions", required=True,
                        help="Folder with slide_NNNN_*.html files")
    parser.add_argument("--images", default="",
                        help="Folder with slide_NNNN.png screenshots (optional)")
    parser.add_argument("--out", default="",
                        help="Output folder for report.html / report.pdf  (default: same as --versions)")
    parser.add_argument("--title", default="Lecture Report",
                        help="Report title  (default: 'Lecture Report')")
    parser.add_argument("--no-pdf", action="store_true",
                        help="Skip PDF generation")
    args = parser.parse_args()

    versions_dir = args.versions
    images_dir = args.images if args.images and os.path.isdir(args.images) else ""
    out_dir = args.out if args.out else versions_dir

    os.makedirs(out_dir, exist_ok=True)

    slides = find_slides(versions_dir)
    if not slides:
        print(f"[report] no slides found in {versions_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"[report] found {len(slides)} slides", file=sys.stderr)

    html_content = build_report_html(slides, images_dir, args.title)

    html_path = os.path.join(out_dir, "report.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"[report] HTML written: {html_path}", file=sys.stderr)

    if not args.no_pdf:
        pdf_path = os.path.join(out_dir, "report.pdf")
        ok = generate_pdf(html_path, pdf_path)
        if ok:
            print(f"[report] PDF  written: {pdf_path}", file=sys.stderr)
        else:
            print("[report] PDF generation failed — open report.html and Ctrl+P manually", file=sys.stderr)
    else:
        print("[report] PDF skipped (--no-pdf)", file=sys.stderr)


if __name__ == "__main__":
    main()
