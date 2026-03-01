# Future Features

Ideas logged during development. Not yet implemented.

---

## High Priority

### Vector-based topic change detection
Use sentence embeddings (e.g. `sentence-transformers`) to detect when the speaker shifts to a new topic mid-batch. When cosine similarity between consecutive sentences drops below a threshold, flush the buffer early and trigger a new slide. This would make topic transitions much crisper without waiting for a full line batch.

### Previous slide navigation
Add left/right keyboard arrow support in `presenter.py` to cycle through the version history (`./versions/`). The presenter already archives every slide — just needs a UI layer. Could be a separate "review" page at `/history`.

---

## Medium Priority

### Unsplash API integration (module ready: `unsplash_helper.py`)
`unsplash_helper.py` is written and ready. Wire it into `transcription_reader.py` as a fallback image source when all 3 Wikipedia queries return no image.

Integration point in `transcription_reader.py → wikipedia_best()`:
```python
if not wiki.get("image_url"):
    from unsplash_helper import get_unsplash_image
    fallback = get_unsplash_image(queries[0])
    if fallback:
        wiki["image_url"] = fallback
```

### Slide confidence scoring
Ask the LLM to include a `confidence` field (0–1) indicating how well the Wikipedia query matches the speech. Skip low-confidence slides or show a visual indicator.

### Multi-language support
Pass a `--language` param to fetch Wikipedia in other languages (`fr.wikipedia.org`, `es.wikipedia.org`, etc.). Useful for non-English lectures.

### Smart deduplication
Track the last N Wikipedia titles used. If the new slide would use the same article as a recent slide, force the LLM to pick a different query.

---

## Low Priority / Exploratory

### GPT-4 Vision slide review
After a slide is generated, send the screenshot + transcript to a vision model to rate visual relevance. Log ratings to help tune the prompts over time.

### QR code on slide
Embed a small QR code in the footer linking to the Wikipedia article so students can scan and read more.

### Export to Google Slides
After the lecture, use the Google Slides API to push all archived slides into a real presentation deck.

### Audience question overlay
A second browser tab where students type questions. Questions appear as a ticker at the bottom of the presenter slide.

### Automatic subtitle overlay
Pipe the live transcription text directly onto the slide as a live subtitle strip at the bottom.

---

## Known Limitations / Tech Debt

- `build_report.py` PDF generation requires Playwright or wkhtmltopdf — document install steps more clearly.
- `slide_watcher.py` screenshots also require Playwright — add a graceful fallback that just saves HTML without a screenshot.
- The LLM prompt assumes English. Non-English transcriptions will produce English slides (Wikipedia queries are in English). Consider detecting language and routing accordingly.
- Flask development server is used (`app.run`). For production use, switch to `gunicorn` with the `geventwebsocket` worker for better WebSocket support.
