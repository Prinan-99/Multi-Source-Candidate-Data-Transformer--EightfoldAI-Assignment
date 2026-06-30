# Multi-Source Candidate Data Transformer
**Eightfold Engineering Intern Assignment — Pria Nandhini M A**

Takes candidate data from multiple sources — recruiter spreadsheet, ATS export, GitHub profile, LinkedIn profile, resume PDF, and recruiter notes — and produces one clean canonical JSON profile with confidence scoring, conflict resolution, and per-field provenance.

---

## Quick start

```bash
pip install -r requirements.txt

# CLI — minimum viable run
python3 canonicalize.py \
  --csv sample_data/sample_recruiter.csv \
  --github https://github.com/Prinan-99

# Web UI
uvicorn app.server:app --port 8000
# then open http://localhost:8000
```

---

## Design & Reasoning

### Problem decomposition

The core challenge is that each source has a different:
- **Format** (CSV, JSON, PDF, API, free text)
- **Reliability** — GitHub bio is self-reported; an ATS system-of-record is higher trust
- **Coverage** — no single source has all fields

The design separates this into three stages:

```
Sources → [Extractors] → RawExtraction[]
                               ↓
                          [Merger]  → CanonicalCandidate
                               ↓
                         [Projector] → final JSON
```

**Why three stages instead of one?**  
Each stage has a single job. Extractors only parse. The merger only resolves conflicts. The projector only reshapes output. This means adding a new source (e.g. Glassdoor) touches exactly one file — you write one extractor. The merger and projector don't change.

---

### Extractor layer — Strategy Pattern

Every extractor returns the same type (`RawExtraction`): a collection of `FieldValue` objects, each carrying a `value`, `source`, `method`, and `confidence`. The pipeline doesn't know or care whether data came from a CSV column or a GitHub API call — it just collects `RawExtraction` objects and passes them to the merger.

This makes the system open for extension. Adding a new source is adding a new module in `app/extractors/`. Nothing else changes.

**Per-source confidence baselines:**

| Source | Confidence | Rationale |
|--------|-----------|-----------|
| GitHub API | 0.90 | Live API, developer self-maintains |
| LinkedIn API | 0.88 | Live API, professional self-maintains |
| Recruiter CSV | 0.85 | Structured, entered by recruiter |
| ATS JSON | 0.80 | Structured but sometimes stale |
| Resume PDF | 0.75 | Unstructured, extraction is lossy |
| Recruiter Notes | 0.60 | Free text, inherently noisy |

---

### Merger — confidence-based conflict resolution

**Why not a fixed priority ordering (GitHub > CSV > Notes)?**

A fixed priority silently discards data. If GitHub says the name is "P. Nair" (0.90) and the ATS says "Priya Nair" (0.85), a priority system picks GitHub and throws away the fuller form. Confidence-based resolution picks the higher-confidence value *and* flags the conflict if the two sources are close (within 0.05), reducing `overall_confidence` by 0.05. No data is lost; the tension is surfaced.

**Scalar fields** (name, headline, location, links): highest confidence wins. Conflict penalty applied when values differ and confidences are within 0.05 of each other.

**Array fields** (emails, phones): union + deduplicate. Phones are normalised to E.164 *before* dedup — `"+91 98765 43210"`, `"9876543210"`, and `"+919876543210"` are the same number. Without normalisation, all three survive into the output.

**Skills**: union across sources, confidence boosted using the complementary-probability formula:

```
confidence = 1 − ∏(1 − cᵢ)  for each source mentioning the skill
```

If CSV reports Python at 0.85 and GitHub repos show Python at 0.90, combined confidence is `1 − (0.15 × 0.10) = 0.985`. Each source is treated as an independent witness — agreement strengthens confidence rather than just taking the max.

**Experience / Education**: deduplicated by `(company, title)` and `(institution, degree)` keys. The most-confident version of each entry wins. Entries are sorted newest-first.

---

### Provenance — every field is traceable

Every accepted value writes a `ProvenanceEntry`:
```json
{ "field": "full_name", "source": "github_api", "method": "api", "confidence": 0.9 }
```

This satisfies the "deterministic & explainable" constraint directly. If a recruiter sees the wrong phone number in the output, they can read the provenance and know exactly which source file to fix.

---

### Determinism

Same inputs always produce the same output:
- `candidate_id` is `"cand_" + SHA256(name + emails)[:12]` — deterministic across runs, no UUID randomness
- Dict and list operations preserve insertion order (Python 3.7+)
- Skills are sorted by confidence descending before output
- Experience and education are sorted by date descending
- Phone and email dedup use ordered lists, not sets

---

### Projector — runtime output reshaping

The same canonical record can be reshaped without code changes. This was the "required twist" in the assignment spec. Pass a `--config` JSON:

```json
{
  "fields": [
    { "path": "full_name",     "type": "string",   "required": true },
    { "path": "primary_email", "from": "emails[0]","type": "string" },
    { "path": "phone",         "from": "phones[0]","type": "string", "normalize": "E164" },
    { "path": "skills",        "from": "skills[].name", "type": "string[]", "normalize": "canonical" }
  ],
  "include_confidence": true,
  "include_provenance": false,
  "on_missing": "null"
}
```

Path syntax supports: simple keys, `emails[0]` (indexed), `skills[].name` (spread-pluck). The `on_missing` policy (`null` / `omit` / `error`) controls what happens when a required field has no value.

---

### Robustness

A failing extractor is logged and skipped; the pipeline continues with whatever data it has. No extractor failure propagates to the caller as an unhandled exception. Missing or malformed sources produce `null` fields — they never produce invented values.

Tested edge cases:
- Empty call (no sources) → returns empty canonical record, `overall_confidence = 0.0`
- Garbage CSV with no recognisable columns → extractor returns empty `RawExtraction`
- Malformed ATS JSON → extractor exception caught, skipped
- Phone with unrecognisable format → stored as-is (raw), not normalised, confidence 0.5
- Single-row and multi-row CSV both handled; multi-row emits a warning and uses row 1 in single mode

---

### Scale

The current pipeline processes one candidate per call, synchronously. Batch mode (`/batch`, CLI loops) sequences calls independently — no shared state between candidates, so parallelism is trivially addable.

**Current throughput:** ~150–300 ms per candidate without live API calls (GitHub/LinkedIn add ~1–2 s). For 1000 candidates from CSV/ATS only, batch completes in ~3–5 minutes sequentially.

**What would scale it to tens of thousands:** replace the sequential loop in `run_batch()` with a `ThreadPoolExecutor` (or `asyncio.gather` once the pipeline is made async). The architecture already supports this — each call is stateless. The FastAPI endpoint also blocks an async worker on each pipeline call; in production this would move to a background task queue (Celery, RQ).

---

## Output schema

```json
{
  "candidate_id": "cand_2123320b7579",
  "full_name": "Pria Nandhini M A",
  "emails": ["candidate@example.com"],
  "phones": ["+919876543210"],
  "location": { "city": "Chennai", "region": "TN", "country": "IN" },
  "links": {
    "linkedin": "https://linkedin.com/in/pria-nandhini",
    "github": "https://github.com/Prinan-99",
    "portfolio": null,
    "other": []
  },
  "headline": "AI Engineer | Data Scientist | Full-Stack Developer",
  "years_experience": 2.5,
  "skills": [
    { "name": "Python", "confidence": 0.999, "sources": ["recruiter_csv", "github_api", "ats_json"] }
  ],
  "experience": [
    { "company": "Freelance", "title": "AI Engineer", "start": "2023-01", "end": "present", "summary": null }
  ],
  "education": [
    { "institution": "Rathinam Technical Campus", "degree": "B.E", "field": "Computer Science Engineering", "end_year": 2025 }
  ],
  "provenance": [
    { "field": "full_name", "source": "github_api", "method": "api", "confidence": 0.9 }
  ],
  "overall_confidence": 0.87
}
```

---

## CLI

```bash
# All sources
python3 canonicalize.py \
  --csv sample_data/sample_recruiter.csv \
  --ats sample_data/sample_ats.json \
  --github https://github.com/Prinan-99 \
  --notes sample_data/sample_notes.txt

# Custom output shape
python3 canonicalize.py \
  --csv sample_data/sample_recruiter.csv \
  --config config/sample_config.json

# Save to file
python3 canonicalize.py \
  --csv sample_data/sample_recruiter.csv \
  --github https://github.com/Prinan-99 \
  --output candidate.json
```

| Flag | Description |
|------|-------------|
| `--csv PATH` | Recruiter CSV |
| `--ats PATH` | ATS JSON export |
| `--github URL` | GitHub profile URL |
| `--linkedin URL` | LinkedIn URL (requires `PROXYCURL_API_KEY`) |
| `--resume PATH` | Resume PDF |
| `--notes PATH` | Recruiter notes `.txt` |
| `--config PATH` | Output config JSON |
| `--output / -o PATH` | Write to file (default: stdout) |
| `--pretty / --compact` | Output format (default: pretty) |

Optional env vars:
```bash
export GITHUB_TOKEN=ghp_...        # raises GitHub rate limit 60 → 5000 req/hr
export PROXYCURL_API_KEY=pcp_...   # enables LinkedIn live fetch
```

---

## Web UI

```bash
uvicorn app.server:app --port 8000
```

Open `http://localhost:8000`. Upload any combination of sources, run single or batch.

**Batch mode** is triggered automatically:
- Upload a CSV with more than one data row → "N candidates detected — Batch mode"
- Select multiple PDF resumes at once (Ctrl/Cmd+click) → each PDF = one candidate
- Mix CSV rows + multiple resumes → all processed together

Results appear as a clickable pill row; select any candidate to see its full canonical view.

API endpoints:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Web UI |
| `GET` | `/health` | Liveness probe |
| `POST` | `/canonicalize` | Single candidate |
| `POST` | `/batch` | Batch — returns `{count, results[]}` |

---

## Tests

```bash
python3 -m pytest tests/ -v
```

65 tests across three files:
- `test_normalizers.py` — phone E.164, date YYYY-MM, location ISO 3166, skill aliases
- `test_merger.py` — scalar conflict resolution, skill confidence boosting, deduplication
- `test_pipeline_e2e.py` — full pipeline runs, schema validation, projector config

---

## Project structure

```
├── canonicalize.py           # CLI entry point
├── requirements.txt
├── app/
│   ├── server.py             # FastAPI — GET / · POST /canonicalize · POST /batch
│   ├── pipeline.py           # Orchestrator: detect → extract → merge → project
│   ├── batch.py              # Batch processor — one pipeline call per candidate
│   ├── merger.py             # Conflict resolution + confidence scoring
│   ├── projector.py          # Config-driven output reshaping
│   ├── schema.py             # Pydantic models (RawExtraction, CanonicalCandidate, OutputConfig)
│   ├── extractors/
│   │   ├── csv_extractor.py
│   │   ├── ats_extractor.py
│   │   ├── github_extractor.py
│   │   ├── linkedin_extractor.py
│   │   ├── resume_extractor.py
│   │   └── notes_extractor.py
│   └── normalizers/
│       ├── phone.py          # → E.164 (default region: IN)
│       ├── date.py           # → YYYY-MM
│       ├── location.py       # → ISO 3166-1 alpha-2
│       └── skills.py         # → canonical skill names
├── front-end/
│   └── index.html            # Single-file Web UI (no build step)
├── config/
│   ├── default_config.json
│   └── sample_config.json
├── sample_data/
│   ├── sample_recruiter.csv
│   ├── sample_ats.json
│   ├── sample_notes.txt
│   ├── multi_candidates.csv       # 5-row CSV for batch mode demo
│   ├── pria_output_default.json   # Pre-generated output (default config)
│   └── pria_output_custom.json    # Pre-generated output (custom config)
└── tests/
    ├── test_normalizers.py
    ├── test_merger.py
    └── test_pipeline_e2e.py
```

---

## Known limitations

- **LinkedIn**: live fetch requires a paid Proxycurl key. Without it, the extractor returns an empty extraction silently — the run continues with other sources.
- **Resume PDF**: uses `pdfplumber`. Complex layouts and scanned PDFs produce degraded text extraction. Unrecognised fields become `null`, never invented.
- **Batch throughput**: sequential today; trivially parallelisable with `ThreadPoolExecutor` since each call is stateless.
- **Async pipeline**: `pipeline.run()` is sync and blocks the FastAPI event loop. Fine for demo; production would use a task queue.
