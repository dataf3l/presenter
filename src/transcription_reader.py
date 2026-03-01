#!/usr/bin/env python3
"""
transcription_reader.py

Reads transcription text from stdin (line by line).
Every N lines (default: 5), sends text + previous context to the LLM,
which generates a Wikipedia-backed HTML slide saved to current_slide.html.

Usage:
    your_transcription_tool | python transcription_reader.py \
        --topic "Cell Biology" \
        --objective "Teach undergrads the basics of cell structure" \
        --lines 5 \
        --overlap 1 \
        --model cohere
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
LLM_MODEL = "cohere"
LINES_PER_BATCH = 5
DEFAULT_OVERLAP = 1
LANGUAGE = "English"

# ---------------------------------------------------------------------------
# Wikipedia helpers
# ---------------------------------------------------------------------------

def wikipedia_large_image(wiki_title: str) -> str:
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
        for page in data.get("query", {}).get("pages", {}).values():
            src = page.get("thumbnail", {}).get("source", "")
            if src:
                return src
    except Exception as e:
        print(f"[wiki/large] '{wiki_title}': {e}", file=sys.stderr)
    return ""


def wikipedia_summary_single(query: str) -> Optional[dict]:
    try:
        encoded = urllib.parse.quote(query.replace(" ", "_"))
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}"
        req = urllib.request.Request(url, headers={"User-Agent": "LiveSlideBot/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())

        page_type = data.get("type", "")
        if "disambiguation" in page_type or "missing" in page_type:
            return None

        title = data.get("title", query)
        extract = data.get("extract", "")
        small_image = data.get("thumbnail", {}).get("source", "")
        large_image = wikipedia_large_image(title) if small_image else ""

        return {
            "title": title,
            "extract": extract,
            "image_url": large_image or small_image,
        }
    except Exception as e:
        print(f"[wiki] '{query}': {e}", file=sys.stderr)
        return None


def wikipedia_best(queries: list, language: str) -> dict:
    """Try each query; return first result with image, or first result, or {}."""
    first_ok = None
    for query in queries:
        print(f"[wiki] trying: '{query}'", file=sys.stderr)
        result = wikipedia_summary_single(query)
        if result is None:
            continue
        if first_ok is None:
            first_ok = result
        if result.get("image_url"):
            print(f"[wiki] ✓ image: '{query}'", file=sys.stderr)
            return result
        print(f"[wiki] no image for '{query}'", file=sys.stderr)
    return first_ok or {}


# ---------------------------------------------------------------------------
# Prompt  (~250 tokens — kept short for fast inference)
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE = """\
You are a live lecture slide generator.
Topic: {topic}
Objective: {objective}

Previous context: {previous}

New speech: {current}

Output ONLY this JSON (no markdown, no extra text):
{{"wikipedia_queries":["<noun 1>","<noun 2>","<noun 3>"],"headline":"<5-8 word title>","bullets":["<fact>","<fact>","<fact>"]}}

Rules:
- wikipedia_queries: 3 specific noun phrases (species, concepts, people, places, events) that are likely to have a photo on Wikipedia. Ordered by relevance to the speech.
- headline: specific and punchy, directly about what was just said.
- bullets: 3 to 5 one-sentence facts directly tied to the speech. Vary length and angle. No fluff.
- JSON only.\
"""

PROMPT_TEMPLATE_ES = """\
Eres un generador de slides en vivo

Tema: {topic}
Objetivo: {objective}

Contexto Previo: {previous}

Nuevo Audio: {current}

Genera SOLO este JSON (no markdown, no texto estra):
{{"wikipedia_queries":["<noun 1>","<noun 2>","<noun 3>"],"headline":"<titulo de 5-8 palabras>","bullets":["<fact>","<fact>","<fact>"]}}

Reglas:
- wikipedia_queries: 3 frases nominales (specie, conceptos, personas, lugares, eventos) los cuales probablemente tengan una foto en Wikipedia. Ordenados por relevancia al Audio actual.
- headline: específico e impactactante, directamente acerca de lo que es esta diciendo.
- bullets: de 3 a 5 hechos, de una frase, directamente relacionados con el audio, varia el angulo y la longitud (No fluff).
- Unicamente JSON.\
"""

def build_prompt(topic: str, objective: str, previous: str, current: str, language: str) -> str:
    prompt_template = PROMPT_TEMPLATE
    if language == "spanish" or language == "es":
        prompt_template = PROMPT_TEMPLATE_ES
    prev = previous.strip() or "(first slide)"
    return prompt_template.format(
        topic=topic,
        objective=objective,
        previous=prev,
        current=current.strip(),
    )


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def ask_llm(topic: str, objective: str, previous: str, current: str, language: str) -> Optional[dict]:
    prompt = build_prompt(topic, objective, previous, current, language)
    print(prompt)
    print(language)
    payload = {"document": prompt, "model_name": LLM_MODEL}
    try:
        resp = requests.post(LLM_API_URL, json=payload, timeout=30)
        resp.raise_for_status()
        raw = resp.json().get("response", "")
        raw = re.sub(r"```[a-z]*\n?", "", raw).strip().strip("`").strip()
        # Extract first valid JSON object in case model adds prose
        match = re.search(r"\{.*\}", raw, re.S)
        if match:
            raw = match.group(0)
        return json.loads(raw)
    except Exception as e:
        print(f"[llm] error: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Slide writer
# ---------------------------------------------------------------------------

def write_slide(wiki: dict, llm_data: dict, slide_path: str, language: str):
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
    flag = "✓ img" if image_url else "✗ no img"
    print(f"[slide] {title}  [{flag}]", file=sys.stderr)


# ---------------------------------------------------------------------------
# Pipeline worker (background thread)
# ---------------------------------------------------------------------------

def process_batch(topic: str, objective: str, previous: str,
                  current: str, slide_path: str, language: str):
    llm_data = ask_llm(topic, objective, previous, current, language)
    if not llm_data:
        print("[pipeline] LLM returned nothing, skipping.", file=sys.stderr)
        return

    queries = llm_data.get("wikipedia_queries", [])
    if not queries:
        queries = [llm_data.get("wikipedia_query", topic)]

    wiki = wikipedia_best(queries, language)
    write_slide(wiki, llm_data, slide_path, language)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global LLM_MODEL

    parser = argparse.ArgumentParser(description="Live transcription → slide generator")
    parser.add_argument("--topic", default="General Knowledge",
                        help="Subject matter of the lecture  (default: 'General Knowledge')")
    parser.add_argument("--objective", default="Educate the audience on the topic",
                        help="Goal of the lecture — gives the AI directional context  (default: generic)")
    parser.add_argument("--lines", type=int, default=LINES_PER_BATCH,
                        help="Transcription lines per batch  (default: 5)")
    parser.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP,
                        help="Lines carried over into the next batch for coherence  (default: 1)")
    parser.add_argument("--model", default=LLM_MODEL,
                        help="LLM model name passed to the API  (default: cohere)")
    parser.add_argument("--slide", default=SLIDE_PATH,
                        help="Output slide path  (default: ./current_slide.html)")
    parser.add_argument("--language", default=LANGUAGE,
                        help="Language for Slides  (default: English)")
    args = parser.parse_args()

    LLM_MODEL = args.model
    overlap = max(0, min(args.overlap, args.lines - 1))

    print(
        f"[reader] topic='{args.topic}'\n"
        f"[reader] objective='{args.objective}'\n"
        f"[reader] lines={args.lines} | overlap={overlap} | model={args.model}",
        file=sys.stderr,
    )
    print(f"[reader] output → {args.slide}", file=sys.stderr)

    buffer: list = []
    previous_batch: str = ""

    for raw_line in sys.stdin:
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue
        if "Partial" in line:
            continue

        buffer.append(line)
        print(f"[buf {len(buffer)}/{args.lines}] {line}", file=sys.stderr)

        if len(buffer) >= args.lines:
            current_text = " ".join(buffer)

            t = threading.Thread(
                target=process_batch,
                args=(args.topic, args.objective, previous_batch,
                      current_text, args.slide, args.language),
                daemon=True,
            )
            t.start()

            # Carry overlap lines forward
            previous_batch = " ".join(buffer[-overlap:]) if overlap > 0 else ""
            buffer = buffer[-overlap:] if overlap > 0 else []


if __name__ == "__main__":
    main()
