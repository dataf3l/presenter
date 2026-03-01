#!/usr/bin/env python3
"""
presenter.py

Flask app on port 5001.
- Watches current_slide.html for changes using watchdog (no more meta-refresh flicker).
- Browser polls /api/version every 500ms; only reloads when the version changes.
- Injects full CSS layout: H1 + bullets left, image right, footer with source.
- Smooth fade-in animation preserved; flicker eliminated.

Usage:
    python presenter.py [--slide path/to/current_slide.html] [--port 5001]

Requires:
    pip install flask watchdog
"""

import argparse
import os
import re
import time
import threading
from flask import Flask, Response, jsonify

app = Flask(__name__)

SLIDE_PATH = os.path.join(os.path.dirname(__file__), "current_slide.html")

# Shared state — updated by the watchdog thread
_state = {
    "version": 0,          # increments every time file changes
    "html": "",            # last raw HTML read from disk
    "lock": threading.Lock(),
}


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
INJECTED_STYLE = """
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Georgia', serif;
    background: #0d1117;
    color: #e6edf3;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }

  .slide-wrapper {
    display: flex;
    flex: 1;
    padding: 48px 64px 24px 64px;
    gap: 48px;
    align-items: flex-start;
  }

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

  .slide-right {
    flex: 0 0 36%;
    display: flex;
    align-items: flex-start;
    justify-content: center;
  }

  img {
    max-width: 100%;
    max-height: 460px;
    border-radius: 12px;
    border: 2px solid #30363d;
    box-shadow: 0 8px 32px #00000088;
    object-fit: cover;
  }

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

  .waiting {
    display: flex;
    flex: 1;
    align-items: center;
    justify-content: center;
    font-size: 1.6rem;
    color: #484f58;
    letter-spacing: 0.08em;
  }

  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(12px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  .slide-wrapper { animation: fadeIn 0.45s ease; }
</style>
"""

# JS that polls /api/version every 500 ms and only reloads on change — no flicker
POLLING_JS = """
<script>
  (function() {
    var current = null;
    function check() {
      fetch('/api/version')
        .then(function(r) { return r.json(); })
        .then(function(data) {
          if (current === null) { current = data.version; return; }
          if (data.version !== current) { location.reload(); }
        })
        .catch(function() {});
    }
    setInterval(check, 500);
  })();
</script>
"""


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

def build_page(raw_html: str) -> str:
    body_match = re.search(r"<body[^>]*>(.*?)</body>", raw_html, re.S | re.I)
    body_content = body_match.group(1).strip() if body_match else raw_html

    img_match = re.search(r"(<img[^>]*>)", body_content, re.S | re.I)
    img_html = img_match.group(1) if img_match else ""

    source_match = re.search(r'(<p class="source">.*?</p>)', body_content, re.S | re.I)
    source_html = source_match.group(1) if source_match else ""

    left_content = body_content
    if img_html:
        left_content = left_content.replace(img_html, "")
    if source_html:
        left_content = left_content.replace(source_html, "")

    title_match = re.search(r"<title>(.*?)</title>", raw_html, re.I)
    page_title = title_match.group(1) if title_match else "Live Lecture"

    right_col = f"<div class='slide-right'>{img_html}</div>" if img_html else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{page_title}</title>
  {INJECTED_STYLE}
</head>
<body>
  <div class="slide-wrapper">
    <div class="slide-left">
      {left_content}
    </div>
    {right_col}
  </div>
  <div class="slide-footer">
    <span class="logo">&#9670; Live Lecture</span>
    {source_html}
    <span>Powered by Wikipedia &amp; AI</span>
  </div>
  {POLLING_JS}
</body>
</html>"""


def waiting_page() -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Live Lecture</title>
  {INJECTED_STYLE}
</head>
<body>
  <div class="waiting">Waiting for lecture to begin…</div>
  {POLLING_JS}
</body>
</html>"""


# ---------------------------------------------------------------------------
# Watchdog thread — watches the slide file, updates shared state
# ---------------------------------------------------------------------------

def watch_slide(slide_path: str):
    """
    Poll the slide file's mtime every 200 ms.
    When it changes, read the new content and bump the version counter.
    (Uses simple mtime polling — no extra watchdog dependency needed.)
    """
    last_mtime = None
    print(f"[watcher] monitoring: {slide_path}", flush=True)
    while True:
        try:
            if os.path.exists(slide_path):
                mtime = os.path.getmtime(slide_path)
                if mtime != last_mtime:
                    last_mtime = mtime
                    with open(slide_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    with _state["lock"]:
                        _state["html"] = content
                        _state["version"] += 1
                    print(f"[watcher] slide updated → version {_state['version']}", flush=True)
        except Exception as e:
            print(f"[watcher] error: {e}", flush=True)
        time.sleep(0.2)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    with _state["lock"]:
        html = _state["html"]
    if not html:
        return Response(waiting_page(), mimetype="text/html")
    return Response(build_page(html), mimetype="text/html")


@app.route("/api/version")
def api_version():
    with _state["lock"]:
        v = _state["version"]
    return jsonify({"version": v})


@app.route("/raw")
def raw():
    with _state["lock"]:
        html = _state["html"]
    if not html:
        return "No slide yet.", 404
    return Response(html, mimetype="text/html")


@app.route("/health")
def health():
    with _state["lock"]:
        v = _state["version"]
    return jsonify({"status": "ok", "version": v,
                    "slide_path": app.config.get("SLIDE_PATH", SLIDE_PATH)})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Live lecture slide presenter")
    parser.add_argument("--slide", default=SLIDE_PATH,
                        help="Path to current_slide.html  (default: ./current_slide.html)")
    parser.add_argument("--port", type=int, default=5001,
                        help="HTTP port  (default: 5001)")
    args = parser.parse_args()

    app.config["SLIDE_PATH"] = args.slide

    # Start file watcher in background
    t = threading.Thread(target=watch_slide, args=(args.slide,), daemon=True)
    t.start()

    print(f"[presenter] slide: {args.slide}")
    print(f"[presenter] open  http://localhost:{args.port}/")
    app.run(host="0.0.0.0", port=args.port, debug=False)
