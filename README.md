# Multi-Source Candidate Data Transformer
**Eightfold Engineering Intern Assignment — Pria Nandhini M A**

Takes candidate data from multiple sources — recruiter spreadsheet, ATS export, GitHub profile, LinkedIn profile, resume PDF, and recruiter notes — and merges them into one clean canonical JSON profile with confidence scoring, conflict resolution, and full provenance tracking on every field.

Exposes the same pipeline as a CLI tool, a REST API, and a web UI. Results are automatically persisted to AWS S3.

---

## Architecture

### Overview

```
6 Sources  ──►  Extractors  ──►  Merger  ──►  Projector  ──►  Output
                (Strategy)      (Conflict     (Config-
                                Resolution)    Driven)
```

The pipeline is a **multi-source ETL** built around three independently testable layers. Each layer knows nothing about the others — extractors don't know how data will be merged, the merger doesn't know what the output shape will be, the projector doesn't know where data came from.

---

### Layer 1 — Extractors (Strategy Pattern)

```
Recruiter CSV   →  csv_extractor    ─┐
ATS JSON        →  ats_extractor    ─┤
GitHub API      →  github_extractor ─┤──► [ RawExtraction list ]
LinkedIn API    →  linkedin_extractor─┤      { value, source,
Resume PDF      →  resume_extractor ─┤        method, confidence }
Recruiter Notes →  notes_extractor  ─┘
```

Each source has one extractor that returns a `RawExtraction(value, source, method, confidence)`. The merger sees a flat list of these — it never cares how GitHub data was fetched vs. how a CSV was parsed. Adding a 7th source means writing one new extractor file, nothing else changes.

---

### Layer 2 — Merger (Conflict Resolution Engine)

```
RawExtraction list
        │
        ▼
┌───────────────────────────────────────────────┐
│  For each canonical field:                    │
│                                               │
│  Scalar (name, headline, location)            │
│    → highest confidence source wins           │
│    → if two sources within 0.05 and disagree  │
│      → flag conflict, penalize overall conf   │
│                                               │
│  Arrays (emails, phones)                      │
│    → union all sources + deduplicate          │
│    → phones normalized to E.164 before dedup  │
│                                               │
│  Skills                                       │
│    → union across all sources                 │
│    → same skill in N sources → compound boost │
│      conf = 1 − ∏(1 − cᵢ)                   │
│                                               │
│  Experience / Education                       │
│    → deduplicate by (company, title)          │
│    → most-confident entry retained            │
│                                               │
│  Every field writes provenance:               │
│    { field, source, method, confidence }      │
└───────────────────────────────────────────────┘
        │
        ▼
  CanonicalCandidate (13 fields, fixed schema)
```

The provenance record is the audit trail — every field carries which source won, the method used to extract it, and the confidence that got it there.

---

### Layer 3 — Projector (Config-Driven Output Shaping)

```
CanonicalCandidate (internal, fixed)
        │
        ▼
  output_config.json
  ┌─────────────────────────────────────────────┐
  │  { "fields": [                              │
  │      { "path": "primary_email",             │
  │        "from": "emails[0]",                 │
  │        "normalize": "E164" },               │
  │      { "path": "skills",                    │
  │        "from": "skills[].name",             │
  │        "normalize": "canonical" }           │
  │    ],                                       │
  │    "include_provenance": false,             │
  │    "on_missing": "null"                     │
  │  }                                          │
  └─────────────────────────────────────────────┘
        │
        ▼
  Reshaped output (any shape, any field names)
```

The same pipeline serves CLI users, ATS integrations, and front-end cards — each with a different config, no code changes. The Projector is essentially a lightweight field-mapping DSL.

---

### API Layer — Three Delivery Modes

```
POST /canonicalize
  ──► pipeline.run() ──► JSONResponse
      (single, waits, returns full result)

POST /batch
  ──► batch.run_batch() ──► JSONResponse({ count, results, s3_keys })
      (all candidates, buffers everything, returns at end)

POST /batch/stream
  ──► batch.run_batch_iter()   ← Python generator, yields one result at a time
      │
      ▼
  StreamingResponse (NDJSON)
      │
      ▼  (browser)
  fetch() → ReadableStream → decode chunks → split \n → parse JSON
      │
      ▼
  candidate card animates in immediately (no waiting for others)
```

The streaming endpoint uses a **generator + StreamingResponse** so the browser renders each candidate the moment it is ready — not after all 5 finish.

---

### Storage — Best-Effort S3

```
pipeline result
      │
      ├──► return to caller  (always, blocking)
      │
      └──► S3 upload         (try/except, non-blocking)
             profiles/<id>_<name>.json          ← single run
             profiles/batch_<ts>/<n>_<name>.json ← batch run
```

S3 upload is fire-and-forget — a storage outage never blocks the API response. The `/profiles` endpoints expose list/get/delete over whatever is stored.

---

### Key Design Decisions

| Decision | Why |
|---|---|
| Confidence weights per source | Avoids hard-coded "CSV always wins" — degrades gracefully when sources are missing |
| Compound skill confidence `1 − ∏(1−cᵢ)` | Same skill in 3 sources should be near-certain, not just the max of three |
| Generator for streaming | Zero buffering — candidate renders in UI the moment processing finishes |
| Projector as config DSL | One pipeline core serves CLI, REST API, and any ATS integration format |
| Provenance on every field | Recruiter sees *why* a value was chosen, not just what it is |
| Best-effort S3 | Storage failure never surfaces to the caller during a live demo or prod request |

---

## Setup

```bash
pip install -r requirements.txt
```

**AWS credentials** — create a `.env` file in the project root:
```
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_DEFAULT_REGION=ap-southeast-1
S3_BUCKET_NAME=your-bucket-name
```

**Optional — GitHub token** (raises rate limit from 60 → 5000 req/hr):
```bash
export GITHUB_TOKEN=ghp_your_token_here
```

**Optional — LinkedIn live fetch** (requires ProxyCurl):
```bash
export PROXYCURL_API_KEY=pcp_your_key_here
```

---

## CLI

### Single candidate

```bash
python3 canonicalize.py \
  --csv   sample_data/sample_recruiter.csv \
  --github https://github.com/Prinan-99 \
  --notes  sample_data/sample_notes.txt \
  --output candidate.json
```

Prints a summary card with confidence bar, skills, provenance count, and elapsed time. JSON saved to file.

### Batch (auto-detected)

```bash
python3 canonicalize.py \
  --csv sample_data/multi_candidates.csv \
  --output-dir batch_output/
```

No `--batch` flag needed. The CLI peeks at the CSV row count and routes automatically. If the CSV has more than one data row, every candidate is processed independently. Shows a live progress line per candidate and a final summary table.

### All sources

```bash
python3 canonicalize.py \
  --csv    sample_data/sample_recruiter.csv \
  --ats    sample_data/sample_ats.json \
  --github https://github.com/Prinan-99 \
  --notes  sample_data/sample_notes.txt \
  --resume "sample_data/Sasidharan_Selvakumar _Resume_Updated.pdf" \
  --config config/sample_config.json \
  --output candidate.json
```

### CLI Flags

| Flag | Description |
|------|-------------|
| `--csv PATH` | Recruiter CSV |
| `--ats PATH` | ATS JSON export |
| `--github URL` | GitHub profile URL |
| `--linkedin URL` | LinkedIn URL (requires `PROXYCURL_API_KEY`) |
| `--resume PATH` | Resume PDF |
| `--notes PATH` | Recruiter notes `.txt` |
| `--config PATH` | Output config JSON |
| `--output / -o PATH` | Save JSON to file |
| `--output-dir PATH` | Save one JSON per candidate (batch mode) |
| `--id TEXT` | Override candidate_id (single mode) |
| `--pretty / --compact` | Pretty-print output (default: pretty) |
| `--quiet` | Suppress all UI chrome — emit only JSON |

---

## Web UI + REST API

### Start the server

```bash
uvicorn app.server:app --port 8000
```

Open **http://localhost:8000** in a browser.

### UI features

- Upload any combination of sources in the left panel
- CSV with multiple rows → automatically switches to **batch mode** (detected client-side from row count before submission)
- **Single candidate**: shows confidence bar, contact, skills, experience, education, provenance table
- **Batch**: candidates appear in a sidebar one by one as they stream from the server — no waiting for all to finish. Click any card to see the full canonical profile in the detail pane
- **Saved Profiles** drawer (top-right) — lists every profile stored in S3; click to reload, delete to remove

### REST API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/canonicalize` | Single candidate — multipart form, returns JSON |
| `POST` | `/batch` | Batch — multipart form, returns `{count, results, s3_keys}` |
| `POST` | `/batch/stream` | Batch streaming — returns NDJSON, one line per candidate as it completes |
| `GET`  | `/profiles` | List all profiles stored in S3 |
| `GET`  | `/profiles/{key}` | Fetch a single profile from S3 by key |
| `DELETE` | `/profiles/{key}` | Delete a profile from S3 |
| `GET`  | `/health` | Liveness probe |
| `GET`  | `/docs` | Auto-generated OpenAPI docs (FastAPI) |

#### Form fields (all optional, at least one required)

| Field | Type | Description |
|-------|------|-------------|
| `csv_file` | file | Recruiter CSV |
| `ats_file` | file | ATS JSON export |
| `notes_file` | file | Recruiter notes `.txt` |
| `resume_file` | file | Resume PDF |
| `config_file` | file | Output config JSON |
| `github_url` | string | GitHub profile URL |
| `linkedin_url` | string | LinkedIn profile URL |
| `notes_text` | string | Recruiter notes (pasted inline) |
| `config_json` | string | Output config JSON (pasted inline) |

#### Streaming batch example

```bash
curl -N -X POST http://localhost:8000/batch/stream \
  -F "csv_file=@sample_data/multi_candidates.csv" \
  | while read line; do
      echo "$line" | python3 -c "import json,sys; d=json.load(sys.stdin); p=d['_progress']; print(f'[{p[\"i\"]}/{p[\"total\"]}] {d.get(\"full_name\")}  conf={d.get(\"overall_confidence\")}')"
    done
```

---

## S3 Storage

Every pipeline run automatically uploads the result to S3:

- **Single run**: `profiles/<candidate_id>_<name>.json`
- **Batch run**: `profiles/batch_<timestamp>/<n>_<name>.json`

Upload is best-effort — if S3 is unreachable the API still returns the profile. Storage never blocks the pipeline.

```bash
# List all stored profiles
curl http://localhost:8000/profiles

# Fetch one
curl http://localhost:8000/profiles/profiles/cand_abc123_Pria.json

# Delete one
curl -X DELETE http://localhost:8000/profiles/profiles/cand_abc123_Pria.json
```

---

## Output Schema

Every run produces a 13-field canonical record:

```json
{
  "candidate_id": "cand_2123320b7579",
  "full_name": "Pria Nandhini M A",
  "emails": ["candidate@example.com"],
  "phones": ["+919876543210"],
  "location": { "city": "Chennai", "region": "TN", "country": "IN" },
  "links": {
    "linkedin": "https://linkedin.com/in/pria-nandhini",
    "github":   "https://github.com/Prinan-99",
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

Batch results include two additional fields: `_batch_label` (original row name) and `_progress` (`{i, total, name, elapsed_ms}`). Streaming results include `_s3_key` once uploaded.

---

## Configurable Output (Required Twist)

The same pipeline can produce different output shapes at runtime — no code changes needed. Pass a `--config` JSON:

```json
{
  "fields": [
    { "path": "full_name",     "type": "string",    "required": true },
    { "path": "primary_email", "from": "emails[0]", "type": "string",   "required": true },
    { "path": "phone",         "from": "phones[0]", "type": "string",   "normalize": "E164" },
    { "path": "skills",        "from": "skills[].name", "type": "string[]", "normalize": "canonical" }
  ],
  "include_confidence": true,
  "include_provenance": false,
  "on_missing": "null"
}
```

Supports: field selection, renaming, path remapping (`emails[0]`, `skills[].name`), per-field normalisation (`E164`, `canonical`, `ISO3166`), and `on_missing` policy (`null` / `omit` / `error`).

---

## Confidence & Merging

**Per-source confidence weights:**

| Source | Confidence |
|--------|------------|
| GitHub API (profile) | 0.90 |
| LinkedIn API | 0.88 |
| Recruiter CSV | 0.85 |
| ATS JSON | 0.80 |
| Resume PDF | 0.75 |
| Recruiter Notes | 0.60 |

**Merge strategies by field type:**

| Field type | Strategy |
|------------|----------|
| Scalar (name, headline, location) | Highest-confidence source wins. Two sources disagree within 0.05 → conflict flagged, `overall_confidence -= 0.05` |
| Arrays (emails, phones) | Union + deduplicate. Phones normalised to E.164 before dedup |
| Skills | Union across all sources. Same skill confirmed by multiple sources → confidence boosted: `1 − ∏(1 − cᵢ)` |
| Experience / Education | Deduplicated by (company, title) / (institution, degree). Most-confident entry retained |

---

## Demo

```bash
bash demo.sh
```

Interactive 3-step demo: single-candidate CLI → batch CLI → web UI. Each step shows a `◆ SAY THIS` block with talking points before running the command.

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

## Project Structure

```
├── canonicalize.py              # CLI entry point (single + batch, auto-detected)
├── demo.sh                      # Interactive live demo runner
├── requirements.txt
├── .env                         # AWS credentials (not committed)
│
├── app/
│   ├── pipeline.py              # Orchestrator — calls extractors → merger → projector
│   ├── merger.py                # Confidence-based conflict resolution
│   ├── projector.py             # Config-driven output reshaping
│   ├── schema.py                # Pydantic models (CanonicalCandidate, OutputConfig, …)
│   ├── batch.py                 # Batch processor — run_batch(), run_batch_iter() generator
│   ├── server.py                # FastAPI app — /canonicalize, /batch, /batch/stream, /profiles
│   ├── storage.py               # S3 upload/list/fetch/delete via boto3
│   ├── extractors/
│   │   ├── csv_extractor.py
│   │   ├── ats_extractor.py
│   │   ├── github_extractor.py
│   │   ├── linkedin_extractor.py
│   │   ├── resume_extractor.py
│   │   └── notes_extractor.py
│   └── normalizers/
│       ├── phone.py             # → E.164
│       ├── date.py              # → YYYY-MM
│       ├── location.py          # → ISO 3166-1 alpha-2
│       └── skills.py            # → canonical skill names
│
├── config/
│   ├── default_config.json      # Full canonical output
│   └── sample_config.json       # Custom projection example
│
├── front-end/
│   └── index.html               # Single-file UI (vanilla JS, no build step)
│
├── sample_data/
│   ├── sample_recruiter.csv     # Single-candidate CSV
│   ├── multi_candidates.csv     # 5-candidate CSV (triggers batch mode)
│   ├── sample_ats.json
│   ├── sample_notes.txt
│   ├── pria_output_default.json # Pre-generated output (default config)
│   └── pria_output_custom.json  # Pre-generated output (custom config)
│
└── tests/
    ├── test_normalizers.py
    ├── test_merger.py
    └── test_pipeline_e2e.py
```
