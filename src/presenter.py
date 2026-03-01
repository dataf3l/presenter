#!/usr/bin/env python3
"""
presenter.py

Flask app on port 5001.
- Watches current_slide.html via mtime polling (background thread).
- Pushes "reload" message to all connected browsers via WebSocket (flask-sock).
- No meta-refresh, no polling from the browser — zero flicker.
- Dark / light theme via URL param: http://localhost:5001/?theme=light
- CSS lives in presenter_dark.css / presenter_light.css (same directory).
- Works over plain HTTP — no HTTPS needed for WebSocket on localhost.

Install:
    pip install flask flask-sock

Usage:
    python presenter.py [--slide current_slide.html] [--port 5001]
"""

import argparse
import os
import re
import time
import threading
import json
from flask import Flask, Response, request, send_from_directory
from flask_sock import Sock

app = Flask(__name__)
sock = Sock(app)

HERE = os.path.dirname(os.path.abspath(__file__))
SLIDE_PATH = os.path.join(HERE, "current_slide.html")

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
_state = {
    "version": 0,
    "html": "",
    "lock": threading.Lock(),
}

# Active WebSocket clients
_clients: set = set()
_clients_lock = threading.Lock()


def _broadcast(msg: str):
    """Send a message to all connected WebSocket clients."""
    dead = set()
    with _clients_lock:
        clients = set(_clients)
    for ws in clients:
        try:
            ws.send(msg)
        except Exception:
            dead.add(ws)
    if dead:
        with _clients_lock:
            _clients.difference_update(dead)


# ---------------------------------------------------------------------------
# File watcher (background thread)
# ---------------------------------------------------------------------------

def watch_slide(slide_path: str):
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
                        v = _state["version"]
                    print(f"[watcher] updated → v{v} | broadcasting to clients", flush=True)
                    _broadcast(json.dumps({"event": "reload", "version": v}))
        except Exception as e:
            print(f"[watcher] error: {e}", flush=True)
        time.sleep(0.2)


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

def _css_tag(theme: str) -> str:
    fname = "presenter_light.css" if theme == "light" else "presenter_dark.css"
    return f'<link rel="stylesheet" href="/{fname}">'


# Minimal inline WebSocket client — auto-reconnects, HTTP only
WS_CLIENT_JS = """
<script>
(function() {
  var statusEl = document.getElementById('ws-status');
  var delay = 1000;

  function connect() {
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var ws = new WebSocket(proto + '//' + location.host + '/ws');

    ws.onopen = function() {
      delay = 1000;
      if (statusEl) { statusEl.textContent = '● live'; statusEl.className = 'ws-status connected'; }
    };

    ws.onmessage = function(e) {
      try {
        var msg = JSON.parse(e.data);
        if (msg.event === 'reload') { location.reload(); }
      } catch(err) {}
    };

    ws.onclose = function() {
      if (statusEl) { statusEl.textContent = '○ reconnecting…'; statusEl.className = 'ws-status reconnecting'; }
      setTimeout(connect, delay);
      delay = Math.min(delay * 2, 10000);  // exponential back-off, max 10s
    };

    ws.onerror = function() { ws.close(); };
  }

  connect();
})();
</script>
"""


def build_page(raw_html: str, theme: str) -> str:
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
  {_css_tag(theme)}
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
  <span id="ws-status" class="ws-status reconnecting">○ connecting…</span>
  {WS_CLIENT_JS}
</body>
</html>"""


def waiting_page(theme: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Live Lecture</title>
  {_css_tag(theme)}
</head>
<body>
  <div class="waiting">Waiting for lecture to begin…</div>
  <span id="ws-status" class="ws-status reconnecting">○ connecting…</span>
  {WS_CLIENT_JS}
</body>
</html>"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    theme = request.args.get("theme", "dark")
    with _state["lock"]:
        html = _state["html"]
    if not html:
        return Response(waiting_page(theme), mimetype="text/html")
    return Response(build_page(html, theme), mimetype="text/html")


@app.route("/presenter_dark.css")
def css_dark():
    return send_from_directory(HERE, "presenter_dark.css", mimetype="text/css")


@app.route("/presenter_light.css")
def css_light():
    return send_from_directory(HERE, "presenter_light.css", mimetype="text/css")


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
    with _clients_lock:
        n = len(_clients)
    return {"status": "ok", "version": v, "connected_clients": n}


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@sock.route("/ws")
def ws_endpoint(ws):
    with _clients_lock:
        _clients.add(ws)
    # Send current version immediately on connect
    with _state["lock"]:
        v = _state["version"]
    try:
        ws.send(json.dumps({"event": "connected", "version": v}))
        # Keep alive — flask-sock closes when this function returns
        while True:
            try:
                ws.receive(timeout=30)   # heartbeat / keep-alive
            except Exception:
                break
    finally:
        with _clients_lock:
            _clients.discard(ws)


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

    t = threading.Thread(target=watch_slide, args=(args.slide,), daemon=True)
    t.start()

    print(f"[presenter] slide : {args.slide}")
    print(f"[presenter] dark  : http://localhost:{args.port}/")
    print(f"[presenter] light : http://localhost:{args.port}/?theme=light")
    app.run(host="0.0.0.0", port=args.port, debug=False)
