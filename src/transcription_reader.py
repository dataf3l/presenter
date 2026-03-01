#!/usr/bin/env python3
"""
transcription_reader.py

Reads transcription text from stdin (line by line).
Every 3 lines, sends the text to the LLM API which generates a Wikipedia-backed
HTML slide saved to current_slide.html.

Usage:
    your_transcription_tool | python transcription_reader.py --topic "Machine Learning"

The LLM API endpoint is the one running on port 5006.
"""

import sys
import argparse
import requests
import json
import re
import os
import urllib.request
import urllib.parse

SLIDE_PATH = os.path.join(os.path.dirname(__file__), "current_slide.html")
LLM_API_URL = "http://localhost:5006/generate"
LLM_MODEL = "groq"          # change to whichever model you want
LINES_PER_BATCH = 3


# ---------------------------------------------------------------------------
# Wikipedia helpers
# ---------------------------------------------------------------------------

def wikipedia_summary(query: str) -> dict:
    """Return {'title', 'extract', 'image_url'} or empty dict on failure."""
    try:
        encoded = urllib.parse.quote(query.replace(" ", "_"))
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}"
        req = urllib.request.Request(url, headers={"User-Agent": "LiveSlideBot/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        return {
            "title": data.get("title", query),
            "extract": data.get("extract", ""),
            "image_url": data.get("thumbnail", {}).get("source", ""),
        }
    except Exception as e:
        print(f"[wikipedia] error: {e}", file=sys.stderr)
        return {}


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """You are a live-lecture slide generator.
The general topic of the lecture is: {topic}

The user will give you a few sentences of live speech transcription.
Your job:
1. Identify the single most relevant Wikipedia search query (2-4 words) that best represents what is being discussed.
2. Output ONLY a JSON object with exactly this shape (no markdown, no extra text):
{{"wikipedia_query": "<your query here>", "headline": "<short 5-8 word slide title>", "bullets": ["point 1", "point 2", "point 3"]}}

Rules:
- wikipedia_query must be a clean noun phrase suitable for the Wikipedia REST API.
- headline is a very short title for the slide.
- bullets are 3 concise facts (one sentence each) that complement the Wikipedia article.
- Return ONLY valid JSON. No explanation, no markdown fences.
"""


def ask_llm(transcription_batch: str, topic: str) -> dict | None:
    """Call LLM API, return parsed JSON dict or None."""
    prompt = (
        SYSTEM_PROMPT_TEMPLATE.format(topic=topic)
        + "\n\nTranscription:\n"
        + transcription_batch
    )
    payload = {"document": prompt, "model_name": LLM_MODEL}
    try:
        resp = requests.post(LLM_API_URL, json=payload, timeout=30)
        resp.raise_for_status()
        raw = resp.json().get("response", "")
        # Strip potential markdown fences
        raw = re.sub(r"```[a-z]*\n?", "", raw).strip()
        return json.loads(raw)
    except Exception as e:
        print(f"[llm] error: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Slide writer
# ---------------------------------------------------------------------------

def write_slide(wiki: dict, llm_data: dict):
    """Write a minimal HTML slide to current_slide.html."""
    title = llm_data.get("headline", wiki.get("title", "Slide"))
    bullets = llm_data.get("bullets", [])
    extract = wiki.get("extract", "")[:300]
    image_url = wiki.get("image_url", "")
    wiki_title = wiki.get("title", "")
    wiki_link = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(wiki_title.replace(' ', '_'))}"

    bullet_html = "\n".join(f"<li>{b}</li>" for b in bullets)
    image_html = f'<img src="{image_url}" alt="{wiki_title}">' if image_url else ""
    source_html = (
        f'<p class="source">Source: <a href="{wiki_link}" target="_blank">Wikipedia – {wiki_title}</a></p>'
        if wiki_title else ""
    )

    html = f"""<!DOCTYPE html>
<html>
<head><title>{title}</title></head>
<body>
<h1>{title}</h1>
<ul>
{bullet_html}
</ul>
<p>{extract}</p>
{image_html}
{source_html}
</body>
</html>"""

    with open(SLIDE_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[slide] written: {title}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    global LLM_MODEL
    parser = argparse.ArgumentParser(description="Live transcription → slide generator")
    parser.add_argument("--topic", default="General Knowledge",
                        help="Overall lecture topic (default: 'General Knowledge')")
    parser.add_argument("--lines", type=int, default=LINES_PER_BATCH,
                        help="Number of transcription lines per LLM call (default: 3)")
    parser.add_argument("--model", default=LLM_MODEL,
                        help="LLM model name passed to the API (default: groq)")
    args = parser.parse_args()

    LLM_MODEL = args.model

    print(f"[transcription_reader] topic='{args.topic}', batch={args.lines} lines", file=sys.stderr)
    print(f"[transcription_reader] writing slides to: {SLIDE_PATH}", file=sys.stderr)

    buffer = []
    for raw_line in sys.stdin:
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue
        if "Partial" in line:
            continue
        buffer.append(line)
        print(f"[line {len(buffer)}] {line}", file=sys.stderr)

        if len(buffer) >= args.lines:
            batch_text = " ".join(buffer)
            buffer = []

            llm_data = ask_llm(batch_text, args.topic)
            if not llm_data:
                print("[pipeline] LLM returned nothing, skipping slide.", file=sys.stderr)
                continue

            query = llm_data.get("wikipedia_query", args.topic)
            wiki = wikipedia_summary(query)

            write_slide(wiki, llm_data)


if __name__ == "__main__":
    main()