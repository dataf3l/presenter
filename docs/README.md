# Live Lecture Slide System

Real-time AI-powered slides generated from live speech transcription.

```
[transcription tool] ──stdout──▶ transcription_reader.py ──▶ current_slide.html
                                        │                            ▲
                                        ▼                            │
                                 LLM API (:5006)              presenter.py (:5001)
                                        │                            │
                                        ▼                       [browser]
                                 Wikipedia REST API
```

---

## Files

| File | Purpose |
|------|---------|
| `transcription_reader.py` | Reads stdin, batches every N lines, asks LLM to pick a Wikipedia query + bullet points, fetches Wikipedia, writes `current_slide.html` |
| `presenter.py` | Flask app on port 5001 – serves `current_slide.html` with injected CSS, auto-refreshes every 500 ms |
| `current_slide.html` | Shared file written by the pipeline, read by the presenter |

---

## Quick Start

### 1. Install dependencies
```bash
pip install flask requests
```

### 2. Start the presenter (open this in the browser first)
```bash
python presenter.py
# Open http://localhost:5001/
```

### 3. Pipe your transcription tool into the reader
```bash
your_transcription_tool | python transcription_reader.py --topic "Neural Networks"
```

Or test with a text file:
```bash
cat my_lecture_notes.txt | python transcription_reader.py --topic "Quantum Computing"
```

---

## Options

### transcription_reader.py
```
--topic   Overall lecture topic shown to the LLM  (default: "General Knowledge")
--lines   Lines to batch before calling LLM        (default: 3)
--model   LLM model name for the API              (default: groq)
```

### presenter.py
```
--slide   Path to current_slide.html              (default: ./current_slide.html)
--port    HTTP port                               (default: 5001)
```

---

## How the LLM prompt works

The LLM receives:
- The overall lecture topic
- The last N lines of transcription

It returns JSON like:
```json
{
  "wikipedia_query": "neural network backpropagation",
  "headline": "How Neural Networks Learn",
  "bullets": [
    "Backpropagation adjusts weights using gradient descent.",
    "Each layer learns increasingly abstract representations.",
    "Learning rate controls the size of each weight update."
  ]
}
```

The pipeline then:
1. Fetches `https://en.wikipedia.org/api/rest_v1/page/summary/<query>`
2. Gets the extract + thumbnail image URL
3. Writes a minimal HTML file
4. The presenter injects CSS and serves it

---

## LLM API (client)

The system POSTs to `http://localhost:5006/generate`:
```json
{ "document": "<full prompt>", "model_name": "groq" }
```
Response:
```json
{ "response": "<LLM text output>" }
```
Change `LLM_API_URL` or `LLM_MODEL` at the top of `transcription_reader.py` to point at a different host/model.