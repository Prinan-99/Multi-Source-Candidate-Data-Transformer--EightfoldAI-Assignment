# 2-Minute Demo Script — Eightfold Multi-Source Candidate Transformer

## SETUP (before starting)
```bash
cd ~/Downloads/EIGHTFOLD-AIASSIGNMENT
uvicorn app.server:app --port 8000 &   # server must be running
# Browser tab open at http://localhost:8000
```

---

## ── PART 1: PROBLEM + STACK  [0:00–0:20] ──────────────────────────────────

> SAY: "The problem is simple but messy: a candidate's data lives across
> six different systems — a recruiter's spreadsheet, the ATS, GitHub,
> LinkedIn, a PDF resume, and handwritten notes. Each source has
> different quality, different format, and conflicting values.
> I built a pipeline that fuses all of them into one canonical,
> traceable JSON profile."

> SAY: "Stack: FastAPI because it gives async + auto OpenAPI docs out of
> the box. Pydantic for schema — it guarantees the output shape, no
> surprise nulls. boto3 for S3 persistence. pdfplumber + phonenumbers
> + dateparser for extraction. Everything typed, everything tested."

---

## ── PART 2: CLI — SINGLE CANDIDATE  [0:20–0:40] ──────────────────────────

**TYPE:**
```bash
python3 canonicalize.py \
  --csv sample_data/sample_recruiter.csv \
  --github https://github.com/Prinan-99 \
  --notes sample_data/sample_notes.txt \
  --output /tmp/pria_profile.json
```

> SAY (while it runs): "Three sources: CSV at confidence 0.85, GitHub
> API at 0.90, recruiter notes at 0.60. The merger picks the
> highest-confidence value when sources conflict."

> POINT AT output when it appears:
> "Confidence 0.871 — green bar means high quality merge.
> Every field has provenance — 24 entries telling us exactly
> which source won each field and why. Saved to /tmp."

---

## ── PART 3: CLI — BATCH  [0:40–0:55] ─────────────────────────────────────

**TYPE:**
```bash
python3 canonicalize.py \
  --csv sample_data/multi_candidates.csv \
  --output-dir /tmp/batch_profiles/
```

> SAY (while it runs): "Same command, multi-row CSV.
> The system auto-detects five candidates — no flag needed.
> Each one processed independently."

> POINT AT summary when it appears:
> "Five candidates. Zero failures. Average confidence 0.858.
> Each JSON saved to /tmp/batch_profiles/ and auto-uploaded to S3."

---

## ── PART 4: UI — OPEN BROWSER  [0:55–1:25] ────────────────────────────────

**SWITCH TO BROWSER at http://localhost:8000**

1. **Upload multi_candidates.csv** to Recruiter CSV field
   > SAY: "Client-side row detection — the UI reads the CSV in the
   > browser before even hitting the server. It sees 5 data rows
   > and switches to batch mode automatically."

2. **Click "Run batch (5)"**
   > SAY: "FastAPI receives the upload, runs the pipeline for each
   > candidate, uploads all five to S3, returns one JSON response."

3. **Click through 2–3 candidate cards in the sidebar**
   > SAY: "Left panel is a live candidate list. Click any name —
   > full canonical profile with source breakdown, provenance table,
   > and confidence score. Every field is traceable."

4. **Click "🗂 Saved Profiles" in the header**
   > SAY: "Every run is persisted to S3 — bucket eightfoldai-23102039,
   > region ap-southeast-1. Click any saved profile to reload it
   > instantly. No re-processing needed."

---

## ── PART 5: ARCHITECTURE DECISIONS  [1:25–1:45] ──────────────────────────

> SAY: "A few decisions I want to call out:

> One — confidence scoring. My initial design was last-write-wins.
> That broke immediately when GitHub said 'Pria Nandhini' and
> a CSV said 'P. Nandhini'. I moved to per-source confidence weights:
> GitHub 0.90, CSV 0.85, ATS 0.80, Resume 0.75, Notes 0.60.
> Highest confidence wins scalar conflicts; skills are unioned across all.

> Two — the Projector layer. The canonical record is fixed, but
> the output shape is runtime-configurable via a JSON config.
> You can rename fields, select a subset, normalise to E.164 or
> ISO 3166 — without touching any pipeline code.

> Three — S3 storage is best-effort. If it fails, the API response
> still returns the profile. Storage never breaks the pipeline."

---

## ── PART 6: FUTURE ENHANCEMENTS  [1:45–2:00] ─────────────────────────────

> SAY: "Three things I'd add next:

> First — LLM-based conflict resolution for close confidence scores,
> not just rule-based max. 'Pria' vs 'P. Nandhini' is trivial for
> a language model.

> Second — real LinkedIn data via ProxyCurl API. The extractor
> is already wired; it just needs the API key.

> Third — at scale, swap synchronous processing for a Celery queue.
> The batch endpoint becomes async: POST returns a job ID,
> a worker processes candidates in parallel, webhook fires on completion.
> S3 as the result store, no changes to the pipeline core.

> The pipeline layer is intentionally isolated — extractors, merger,
> projector are all plug-and-play. That's the architecture."

---

## COMMANDS CHEAT SHEET

```bash
# Single candidate (clean summary, save JSON to file)
python3 canonicalize.py \
  --csv sample_data/sample_recruiter.csv \
  --github https://github.com/Prinan-99 \
  --notes sample_data/sample_notes.txt \
  --output /tmp/pria_profile.json

# Batch (progress lines + summary, save per-candidate JSONs)
python3 canonicalize.py \
  --csv sample_data/multi_candidates.csv \
  --output-dir /tmp/batch_profiles/

# Raw JSON only (for piping / scripts)
python3 canonicalize.py --csv sample_data/multi_candidates.csv --quiet

# API health check
curl http://localhost:8000/health

# List S3 profiles
curl http://localhost:8000/profiles

# UI
open http://localhost:8000
```
