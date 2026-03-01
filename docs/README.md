# Live Lecture Slide System — Full Pipeline

```
[transcription tool]
        │ stdout
        ▼
transcription_reader.py  ──▶  current_slide.html
        │ (LLM + Wikipedia)          │
        │                            ├──▶  presenter.py  :5001  [browser display]
        │                            │         (filesystem watcher, no flicker)
        │                            │
        │                            └──▶  slide_watcher.py
        │                                       │
        │                                  ./lecture/versions/slide_NNNN_*.html
        │                                  ./lecture/images/slide_NNNN.png
        │
        └────────── build_report.py ──▶  ./lecture/report.html + report.pdf
```

---

## Files

| File | Purpose |
|------|---------|
| `transcription_reader.py` | Reads stdin → LLM → 3 Wikipedia queries → best image → `current_slide.html` |
| `presenter.py` | Flask :5001 — serves slide with CSS, JS polls `/api/version`, reloads only on change (no flicker) |
| `slide_watcher.py` | Watches `current_slide.html`, saves versioned HTMLs + PNG screenshots |
| `build_report.py` | Combines all versioned slides into `report.html` + `report.pdf` |

---

## Install

```bash
pip install flask requests

# For screenshots and PDF (choose one):
pip install playwright && playwright install chromium
# OR install wkhtmltopdf from https://wkhtmltopdf.org/
```

---

## Usage

### 1. Start the presenter (open in browser)
```bash
python presenter.py --lecture "Biology 101"
# Open http://localhost:5001/
```

### 2. Start the slide watcher (archives every version + screenshots)
```bash
python slide_watcher.py --lecture my_biology_lecture
# Saves to ./my_biology_lecture/versions/ and ./my_biology_lecture/images/
```

### 3. Pipe your transcription tool
```bash
your_transcription_tool | python transcription_reader.py \
    --topic "BASIC BIOLOGY" --lines 2 --model groq

# Or test with a file:
python simulate.py my_notes.txt | python transcription_reader.py --topic "Biology"
```

### 4. Generate the report (after lecture)
```bash
python build_report.py \
    --versions ./my_biology_lecture/versions \
    --images   ./my_biology_lecture/images \
    --out      ./my_biology_lecture \
    --title    "Biology 101 — March 2026"
# Opens report.html in browser → Ctrl+P for PDF
# Or if playwright/wkhtmltopdf installed: report.pdf is auto-generated
```

---

## Key improvements over v1

### No more flicker
- Removed `<meta http-equiv="refresh">` 
- Browser JS polls `/api/version` every 500ms
- Page only reloads when the file actually changes → animation plays once, cleanly

### Better images
- LLM now returns **3 Wikipedia queries** ordered by preference
- System tries each query; uses the first one that has an image
- For each match, tries **1200px Action API** image first, falls back to summary thumbnail
- Result: dramatically more slides with images

### Slide archiving
- `slide_watcher.py` saves every slide version with a timestamp
- Screenshots captured automatically (Playwright or wkhtmltoimage)

### Report generation  
- `build_report.py` reads all versioned slides, embeds screenshots
- Outputs one styled HTML with print page-breaks
- Auto-generates PDF if playwright or wkhtmltopdf is available

---

## Command reference

```bash
# transcription_reader.py
--topic    "BASIC BIOLOGY"     # lecture topic for LLM context
--lines    2                   # lines to batch (lower = faster slides)
--model    groq                # LLM model name
--slide    current_slide.html  # output file

# presenter.py
--slide    current_slide.html  # file to watch and serve
--port     5001                # HTTP port

# slide_watcher.py
--slide    current_slide.html  # file to watch
--lecture  my_lecture          # folder name for output

# build_report.py
--versions ./my_lecture/versions
--images   ./my_lecture/images
--out      ./my_lecture
--title    "My Lecture Title"
--no-pdf   # skip PDF step
```
