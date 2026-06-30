# Multi-Source Candidate Data Transformer
**Eightfold Engineering Intern Assignment — Pria Nandhini M A**

Merges recruiter CSV, ATS JSON, GitHub, LinkedIn, resume PDF, and recruiter notes into one canonical JSON profile with confidence scoring and per-field provenance.

---

## Setup

```bash
pip install -r requirements.txt
```

Optional env vars:
```bash
export GITHUB_TOKEN=ghp_...        # raises GitHub rate limit 60 → 5000 req/hr
export PROXYCURL_API_KEY=pcp_...   # enables LinkedIn live fetch
```

---
## Architecture
The design separates this into three stages:

```
Sources → [Extractors] → RawExtraction[]
                               ↓
                          [Merger]  → CanonicalCandidate
                               ↓
                         [Projector] → final JSON
                         
```
## How to run

**CLI — single candidate (default output):**
```bash
python3 canonicalize.py \
  --csv sample_data/sample_recruiter.csv \
  --github https://github.com/Prinan-99 \
  --notes sample_data/sample_notes.txt
```

**CLI — custom output shape:**
```bash
python3 canonicalize.py \
  --csv sample_data/sample_recruiter.csv \
  --config config/sample_config.json
```

**CLI — batch (multi-row CSV → one JSON per candidate):**
```bash
python3 canonicalize.py \
  --csv sample_data/multi_candidates.csv \
  --output-dir batch_output/
```

**Web UI:**
```bash
uvicorn app.server:app --port 8000
# open http://localhost:8000
```

Upload any combination of sources. A multi-row CSV is auto-detected as batch mode. API endpoints: `POST /canonicalize` (single), `POST /batch` (multi).

---

## Sample outputs

Pre-generated outputs on the provided sample inputs are in `sample_data/`:

- [`pria_output_default.json`](sample_data/pria_output_default.json) — default config (all fields + provenance)
- [`pria_output_custom.json`](sample_data/pria_output_custom.json) — custom config (field selection, E.164 phone, skill names only)

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
├── canonicalize.py        # CLI entry point
├── app/
│   ├── server.py          # FastAPI (GET / · POST /canonicalize · POST /batch)
│   ├── pipeline.py        # Orchestrator: extract → merge → project
│   ├── batch.py           # Batch processor
│   ├── merger.py          # Confidence-based conflict resolution
│   ├── projector.py       # Config-driven output reshaping
│   ├── schema.py          # Pydantic models
│   ├── extractors/        # One module per source (CSV, ATS, GitHub, LinkedIn, PDF, Notes)
│   └── normalizers/       # Phone → E.164, date → YYYY-MM, location → ISO 3166, skills
├── config/
│   ├── default_config.json
│   └── sample_config.json
├── sample_data/
│   ├── sample_recruiter.csv
│   ├── sample_ats.json
│   ├── sample_notes.txt
│   ├── multi_candidates.csv
│   ├── pria_output_default.json
│   └── pria_output_custom.json
└── tests/
```
