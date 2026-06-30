# Multi-Source Candidate Data Transformer
**Eightfold Engineering Intern Assignment — Pria Nandhini M A**

Takes candidate data from multiple sources — a recruiter spreadsheet, ATS export, GitHub profile, LinkedIn profile, resume PDF, and recruiter notes — and merges them into one clean canonical JSON profile with confidence scoring, conflict resolution, and provenance tracking on every field.

---

## Setup

```bash
pip install -r requirements.txt
```

Optional — set a GitHub token to raise the API rate limit from 60 to 5000 req/hr:
```bash
export GITHUB_TOKEN=ghp_your_token_here
```

Optional — set a Proxycurl key to enable LinkedIn live fetch:
```bash
export PROXYCURL_API_KEY=pcp_your_key_here
```

---

## Run

**Minimum — CSV + GitHub:**
```bash
python3 canonicalize.py \
  --csv sample_data/sample_recruiter.csv \
  --github https://github.com/Prinan-99
```

**All sources:**
```bash
python3 canonicalize.py \
  --csv sample_data/sample_recruiter.csv \
  --ats sample_data/sample_ats.json \
  --github https://github.com/Prinan-99 \
  --notes sample_data/sample_notes.txt
```

**Custom output config (field selection + renaming):**
```bash
python3 canonicalize.py \
  --csv sample_data/sample_recruiter.csv \
  --github https://github.com/Prinan-99 \
  --config config/sample_config.json
```

**Save output to file:**
```bash
python3 canonicalize.py \
  --csv sample_data/sample_recruiter.csv \
  --github https://github.com/Prinan-99 \
  --output candidate.json
```

---

## CLI Flags

| Flag | What it does |
|------|-------------|
| `--csv PATH` | Recruiter CSV (structured source) |
| `--ats PATH` | ATS JSON export (structured source) |
| `--github URL` | GitHub profile URL |
| `--linkedin URL` | LinkedIn profile URL (requires `PROXYCURL_API_KEY`) |
| `--resume PATH` | Resume PDF |
| `--notes PATH` | Recruiter notes `.txt` |
| `--config PATH` | Output config JSON (optional — default emits full record) |
| `--output / -o PATH` | Write JSON to file (default: stdout) |
| `--pretty / --compact` | Pretty-print output (default: pretty) |

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

## Configurable Output (Required Twist)

The same pipeline can produce different output shapes at runtime — no code changes needed. Pass a `--config` JSON:

```json
{
  "fields": [
    { "path": "full_name",     "type": "string",   "required": true },
    { "path": "primary_email", "from": "emails[0]","type": "string",   "required": true },
    { "path": "phone",         "from": "phones[0]","type": "string",   "normalize": "E164" },
    { "path": "skills",        "from": "skills[].name", "type": "string[]", "normalize": "canonical" }
  ],
  "include_confidence": true,
  "include_provenance": false,
  "on_missing": "null"
}
```

Supports: field selection, renaming, path remapping (`emails[0]`, `skills[].name`), per-field normalisation, and `on_missing` policy (`null` / `omit` / `error`).

---

## How Merging Works

| Field type | Strategy |
|---|---|
| Scalar (name, headline, location) | Highest-confidence source wins. If two sources disagree within 0.05 confidence → conflict flagged, `overall_confidence -= 0.05` |
| Arrays (emails, phones) | Union + deduplicate. Phones normalised to E.164 before dedup |
| Skills | Union across sources. Same skill confirmed in multiple sources → confidence boosted via `1 − ∏(1 − cᵢ)` |
| Experience / Education | Deduplicated by (company, title) and (institution, degree). Most-confident entry retained |

**Confidence per source:**

| Source | Confidence |
|---|---|
| GitHub API | 0.90 (profile) / 0.80 (repos) |
| LinkedIn API | 0.88 |
| Recruiter CSV | 0.85 |
| ATS JSON | 0.80 |
| Resume PDF | 0.75 |
| Recruiter Notes | 0.60 |

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
├── canonicalize.py          # CLI entry point
├── requirements.txt
├── app/
│   ├── pipeline.py          # Orchestrator
│   ├── merger.py            # Conflict resolution + confidence scoring
│   ├── projector.py         # Config-driven output reshaping
│   ├── schema.py            # Pydantic models
│   ├── extractors/
│   │   ├── csv_extractor.py
│   │   ├── ats_extractor.py
│   │   ├── github_extractor.py
│   │   ├── linkedin_extractor.py
│   │   ├── resume_extractor.py
│   │   └── notes_extractor.py
│   └── normalizers/
│       ├── phone.py         # → E.164
│       ├── date.py          # → YYYY-MM
│       ├── location.py      # → ISO 3166-1 alpha-2
│       └── skills.py        # → canonical skill names
├── config/
│   ├── default_config.json  # Full canonical output
│   └── sample_config.json   # Custom projection example
├── sample_data/
│   ├── sample_recruiter.csv
│   ├── sample_ats.json
│   ├── sample_notes.txt
│   ├── pria_output_default.json   # Produced output (default config)
│   └── pria_output_custom.json    # Produced output (custom config)
|
└── tests/
    ├── test_normalizers.py
    ├── test_merger.py
    └── test_pipeline_e2e.py
```

---

## Sample Outputs

Pre-generated outputs from the sample inputs are in `sample_data/`:
- `pria_output_default.json` — full canonical record with provenance
- `pria_output_custom.json` — reshaped output using `config/sample_config.json`

---


