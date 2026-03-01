#!/usr/bin/env python3
"""
transcription_reader.py

Reads transcription text from stdin (line by line).
Every N lines, sends the text to the LLM API which generates a Wikipedia-backed
HTML slide saved to current_slide.html.

Improvements:
  - LLM generates 3 Wikipedia queries; tries each until one returns an image
  - Tries large (1200px) image first, falls back to thumbnail
  - Processing runs in a background thread so stdin never blocks
  - Filters "Partial" transcription lines

Usage:
    your_transcription_tool | python transcription_reader.py --topic "Machine Learning"
"""

import sys
import argparse
import requests
import json
import re
import os
import urllib.request
import urllib.parse
import threading
from typing import Optional

SLIDE_PATH = os.path.join(os.path.dirname(__file__), "current_slide.html")
LLM_API_URL = "http://localhost:5006/generate"
LLM_MODEL = "groq"
LINES_PER_BATCH = 3


# ---------------------------------------------------------------------------
# Wikipedia helpers — tries multiple queries, prefers large images
# ---------------------------------------------------------------------------

def wikipedia_large_image(wiki_title: str) -> str:
    """
    Fetch the highest-res thumbnail (up to 1200px wide) via the Action API.
    Returns URL string or empty string.
    """
    try:
        encoded = urllib.parse.quote(wiki_title)
        url = (
            "https://en.wikipedia.org/w/api.php"
            f"?action=query&titles={encoded}&prop=pageimages"
            "&format=json&pithumbsize=1200"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "LiveSlideBot/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            src = page.get("thumbnail", {}).get("source", "")
            if src:
                return src
    except Exception as e:
        print(f"[wiki/large] '{wiki_title}': {e}", file=sys.stderr)
    return ""


def wikipedia_summary_single(query: str) -> Optional[dict]:
    """
    Fetch summary + best-available image for one query.
    Returns dict with title/extract/image_url, or None on failure.
    """
    try:
        encoded = urllib.parse.quote(query.replace(" ", "_"))
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}"
        req = urllib.request.Request(url, headers={"User-Agent": "LiveSlideBot/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())

        page_type = data.get("type", "")
        if "disambiguation" in page_type or "missing" in page_type:
            print(f"[wiki] '{query}' → disambiguation/missing, skipping", file=sys.stderr)
            return None

        title = data.get("title", query)
        extract = data.get("extract", "")
        small_image = data.get("thumbnail", {}).get("source", "")

        # Try to get a larger image via the Action API
        large_image = wikipedia_large_image(title) if small_image else ""
        image_url = large_image or small_image

        return {"title": title, "extract": extract, "image_url": image_url}

    except Exception as e:
        print(f"[wiki/summary] '{query}': {e}", file=sys.stderr)
        return None


def wikipedia_best(queries: list) -> dict:
    """
    Try each query in order.
    Return the first result that has an image.
    If none have images, return the first successful result.
    Fallback: empty dict.
    """
    first_ok = None
    for query in queries:
        print(f"[wiki] trying: '{query}'", file=sys.stderr)
        result = wikipedia_summary_single(query)
        if result is None:
            continue
        if first_ok is None:
            first_ok = result
        if result.get("image_url"):
            print(f"[wiki] ✓ image found via '{query}'", file=sys.stderr)
            return result
        print(f"[wiki] no image for '{query}', trying next...", file=sys.stderr)

    if first_ok:
        print("[wiki] no query returned an image — using first result without image", file=sys.stderr)
    return first_ok or {}


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """You are a live-lecture slide generator.
The general topic of the lecture is: {topic}

The user will give you a few sentences of live speech transcription.
Your job:
1. Identify THREE different Wikipedia search queries (each 2-4 words) for closely related concepts that best represent what is being discussed. Prefer specific topics (species, inventions, people, places, biological processes) that are likely to have photos on Wikipedia.
2. Output ONLY a JSON object with exactly this shape (no markdown, no extra text):
{{"wikipedia_queries": ["query 1", "query 2", "query 3"], "headline": "<short 5-8 word slide title>", "bullets": ["point 1", "point 2", "point 3"]}}

Rules:
- wikipedia_queries: array of 3 noun phrases, ordered by preference. The system tries each until it finds one with an image.
- headline: very short slide title (5-8 words).
- bullets: 3 concise one-sentence facts.
- Return ONLY valid JSON. No explanation, no markdown fences.
"""


def ask_llm(transcription_batch: str, topic: str) -> Optional[dict]:
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
        # Strip markdown fences if model adds them
        raw = re.sub(r"```[a-z]*\n?", "", raw).strip().strip("`").strip()
        return json.loads(raw)
    except Exception as e:
        print(f"[llm] error: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Slide writer
# ---------------------------------------------------------------------------

def write_slide(wiki: dict, llm_data: dict, slide_path: str):
    """Write a minimal no-CSS HTML slide."""
    title = llm_data.get("headline", wiki.get("title", "Slide"))
    bullets = llm_data.get("bullets", [])
    extract = wiki.get("extract", "")[:400]
    image_url = wiki.get("image_url", "")
    wiki_title = wiki.get("title", "")
    wiki_link = (
        f"https://en.wikipedia.org/wiki/{urllib.parse.quote(wiki_title.replace(' ', '_'))}"
        if wiki_title else ""
    )

    bullet_html = "\n".join(f"<li>{b}</li>" for b in bullets)
    image_html = f'<img src="{image_url}" alt="{wiki_title}">' if image_url else ""
    source_html = (
        f'<p class="source">Source: <a href="{wiki_link}" target="_blank">'
        f"Wikipedia – {wiki_title}</a></p>"
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

    with open(slide_path, "w", encoding="utf-8") as f:
        f.write(html)
    has_img = "✓ image" if image_url else "✗ no image"
    print(f"[slide] written: {title}  [{has_img}]", file=sys.stderr)


# ---------------------------------------------------------------------------
# Pipeline (runs in background thread)
# ---------------------------------------------------------------------------

def process_batch(batch_text: str, topic: str, slide_path: str):
    llm_data = ask_llm(batch_text, topic)
    if not llm_data:
        print("[pipeline] LLM returned nothing, skipping.", file=sys.stderr)
        return

    queries = llm_data.get("wikipedia_queries", [])
    if not queries:
        # Backwards compat with old single-query format
        q = llm_data.get("wikipedia_query", topic)
        queries = [q]

    wiki = wikipedia_best(queries)
    write_slide(wiki, llm_data, slide_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global LLM_MODEL

    parser = argparse.ArgumentParser(description="Live transcription → slide generator")
    parser.add_argument("--topic", default="General Knowledge",
                        help="Lecture topic shown to the LLM  (default: 'General Knowledge')")
    parser.add_argument("--lines", type=int, default=LINES_PER_BATCH,
                        help="Lines to batch before each LLM call  (default: 3)")
    parser.add_argument("--model", default=LLM_MODEL,
                        help="LLM model name passed to the API  (default: groq)")
    parser.add_argument("--slide", default=SLIDE_PATH,
                        help="Output slide path  (default: ./current_slide.html)")
    args = parser.parse_args()

    LLM_MODEL = args.model
    slide_path = args.slide

    print(
        f"[transcription_reader] topic='{args.topic}' | "
        f"batch={args.lines} lines | model={args.model}",
        file=sys.stderr,
    )
    print(f"[transcription_reader] output → {slide_path}", file=sys.stderr)

    buffer = []
    for raw_line in sys.stdin:
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue
        if "Partial" in line:
            continue

        buffer.append(line)
        print(f"[buf {len(buffer)}/{args.lines}] {line}", file=sys.stderr)

        if len(buffer) >= args.lines:
            batch_text = " ".join(buffer)
            buffer = []
            t = threading.Thread(
                target=process_batch,
                args=(batch_text, args.topic, slide_path),
                daemon=True,
            )
            t.start()


if __name__ == "__main__":
    main()
