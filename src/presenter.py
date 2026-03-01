#!/usr/bin/env python3
"""
presenter.py

Flask app running on port 5001.
Reads current_slide.html, injects CSS + auto-refresh meta tag, serves it.
Refreshes every 500 ms so the audience always sees the latest slide.

Usage:
    python presenter.py [--slide path/to/current_slide.html]
"""

import argparse
import os
import re
from flask import Flask, Response

app = Flask(__name__)

SLIDE_PATH = os.path.join(os.path.dirname(__file__), "current_slide.html")

# ---------------------------------------------------------------------------
# Injected CSS – clean, educational look, no external fonts/CDNs
# ---------------------------------------------------------------------------
INJECTED_STYLE = """
<style>
  /* ── Reset / base ── */
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Georgia', serif;
    background: #0d1117;
    color: #e6edf3;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }

  /* ── Main slide area ── */
  .slide-wrapper {
    display: flex;
    flex: 1;
    padding: 48px 64px 24px 64px;
    gap: 48px;
    align-items: flex-start;
  }

  /* ── Left column ── */
  .slide-left {
    flex: 1 1 55%;
    display: flex;
    flex-direction: column;
    gap: 28px;
  }

  h1 {
    font-size: 2.6rem;
    font-weight: 700;
    line-height: 1.2;
    color: #58a6ff;
    border-bottom: 3px solid #58a6ff44;
    padding-bottom: 16px;
  }

  ul {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 18px;
  }

  ul li {
    font-size: 1.25rem;
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
    font-size: 1rem;
    top: 3px;
  }

  p {
    font-size: 1rem;
    color: #8b949e;
    line-height: 1.6;
    font-style: italic;
    margin-top: 8px;
  }

  /* ── Right column – image ── */
  .slide-right {
    flex: 0 0 36%;
    display: flex;
    align-items: flex-start;
    justify-content: center;
  }

  img {
    max-width: 100%;
    max-height: 420px;
    border-radius: 12px;
    border: 2px solid #30363d;
    box-shadow: 0 8px 32px #00000088;
    object-fit: cover;
  }

  /* ── Footer bar ── */
  .slide-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 64px;
    border-top: 1px solid #21262d;
    font-size: 0.78rem;
    color: #484f58;
    flex-shrink: 0;
  }

  .slide-footer a { color: #58a6ff; text-decoration: none; }
  .slide-footer a:hover { text-decoration: underline; }

  .logo {
    font-weight: 700;
    font-size: 1.1rem;
    color: #58a6ff;
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }

  /* ── No-slide state ── */
  .waiting {
    display: flex;
    flex: 1;
    align-items: center;
    justify-content: center;
    font-size: 1.6rem;
    color: #484f58;
    letter-spacing: 0.08em;
  }

  /* ── Fade-in animation ── */
  @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
  .slide-wrapper { animation: fadeIn 0.4s ease; }
</style>
"""

AUTO_REFRESH = '<meta http-equiv="refresh" content="5">'


# ---------------------------------------------------------------------------
# HTML transformer
# ---------------------------------------------------------------------------

def build_page(raw_html: str) -> str:
    """
    Take the raw minimal HTML written by the pipeline,
    inject CSS + layout wrappers + auto-refresh, return full page HTML.
    """
    # Extract inner body content
    body_match = re.search(r"<body[^>]*>(.*?)</body>", raw_html, re.S | re.I)
    body_content = body_match.group(1).strip() if body_match else raw_html

    # Split into left content (h1 + ul + p) and right content (img)
    img_match = re.search(r"(<img[^>]*>)", body_content, re.S | re.I)
    img_html = img_match.group(1) if img_match else ""

    # Source link
    source_match = re.search(r'(<p class="source">.*?</p>)', body_content, re.S | re.I)
    source_html = source_match.group(1) if source_match else ""

    # Strip img and source from left column
    left_content = body_content
    if img_html:
        left_content = left_content.replace(img_html, "")
    if source_html:
        left_content = left_content.replace(source_html, "")

    title_match = re.search(r"<title>(.*?)</title>", raw_html, re.I)
    page_title = title_match.group(1) if title_match else "Live Lecture"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  {AUTO_REFRESH}
  <title>{page_title}</title>
  {INJECTED_STYLE}
</head>
<body>
  <div class="slide-wrapper">
    <div class="slide-left">
      {left_content}
    </div>
    {"<div class='slide-right'>" + img_html + "</div>" if img_html else ""}
  </div>
  <div class="slide-footer">
    <span class="logo">&#9670; Live Lecture</span>
    {source_html}
    <span>Powered by Wikipedia &amp; AI</span>
  </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    slide_file = app.config.get("SLIDE_PATH", SLIDE_PATH)
    if not os.path.exists(slide_file):
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  {AUTO_REFRESH}
  <title>Live Lecture</title>
  {INJECTED_STYLE}
</head>
<body>
  <div class="waiting">Waiting for lecture to begin…</div>
</body>
</html>"""
        return Response(html, mimetype="text/html")

    with open(slide_file, "r", encoding="utf-8") as f:
        raw = f.read()

    return Response(build_page(raw), mimetype="text/html")


@app.route("/raw")
def raw():
    """Serve the raw HTML file for debugging."""
    slide_file = app.config.get("SLIDE_PATH", SLIDE_PATH)
    if not os.path.exists(slide_file):
        return "No slide yet.", 404
    with open(slide_file, "r", encoding="utf-8") as f:
        return Response(f.read(), mimetype="text/html")


@app.route("/health")
def health():
    return {"status": "ok", "slide_path": app.config.get("SLIDE_PATH", SLIDE_PATH)}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Live lecture slide presenter")
    parser.add_argument("--slide", default=SLIDE_PATH,
                        help="Path to current_slide.html (default: ./current_slide.html)")
    parser.add_argument("--port", type=int, default=5001,
                        help="Port to run on (default: 5001)")
    args = parser.parse_args()

    app.config["SLIDE_PATH"] = args.slide
    print(f"[presenter] serving slide: {args.slide}")
    print(f"[presenter] open http://localhost:{args.port}/ in your browser")
    app.run(host="0.0.0.0", port=args.port, debug=False)