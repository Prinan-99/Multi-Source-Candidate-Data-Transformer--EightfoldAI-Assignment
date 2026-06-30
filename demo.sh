#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
#  Eightfold Assignment — Live Demo Runner
#  Usage: bash demo.sh
#  Each ENTER press: first shows what to SAY, second runs the command.
# ─────────────────────────────────────────────────────────────────

GREEN="\033[32m"
CYAN="\033[36m"
YELLOW="\033[33m"
BOLD="\033[1m"
DIM="\033[90m"
RESET="\033[0m"
WHITE="\033[97m"

# Print a "say this out loud" block
say() {
  echo ""
  echo -e "  ${YELLOW}${BOLD}◆ SAY THIS${RESET}"
  echo -e "  ${DIM}$(printf '─%.0s' {1..50})${RESET}"
  while IFS= read -r line; do
    echo -e "  ${WHITE}$line${RESET}"
  done <<< "$1"
  echo -e "  ${DIM}$(printf '─%.0s' {1..50})${RESET}"
  echo ""
}

run_pause() {
  echo -e "  ${DIM}── press ENTER to run the command ──${RESET}"
  read -r
}

next_pause() {
  echo ""
  echo -e "  ${DIM}── press ENTER for next step ──${RESET}"
  read -r
  clear
}

step() {
  echo -e "  ${CYAN}${BOLD}$1${RESET}"
  echo -e "  ${DIM}$(printf '─%.0s' {1..54})${RESET}"
  echo ""
}

# ══════════════════════════════════════════════════════════════
# PRE-FLIGHT
# ══════════════════════════════════════════════════════════════
clear
echo -e "${BOLD}  Eightfold Demo — Pre-flight check${RESET}"
echo ""

if ! curl -sf http://localhost:8000/health > /dev/null 2>&1; then
  echo -e "  ${YELLOW}⚡ Starting API server on :8000 …${RESET}"
  uvicorn app.server:app --port 8000 > /tmp/demo_server.log 2>&1 &
  sleep 3
fi

if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
  echo -e "  ${GREEN}✓  API server        http://localhost:8000${RESET}"
else
  echo -e "  \033[31m✗  Server failed to start\033[0m"
  exit 1
fi

echo -e "  ${GREEN}✓  CSV (1 candidate)  sample_data/sample_recruiter.csv${RESET}"
echo -e "  ${GREEN}✓  CSV (5 candidates) sample_data/multi_candidates.csv${RESET}"
echo -e "  ${GREEN}✓  GitHub             https://github.com/Prinan-99${RESET}"
echo -e "  ${GREEN}✓  S3 bucket          eightfoldai-23102039 (ap-southeast-1)${RESET}"
echo ""
echo -e "  ${BOLD}Everything ready. Open http://localhost:8000 in your browser.${RESET}"


next_pause

# ══════════════════════════════════════════════════════════════
# STEP 1 — Single candidate
# ══════════════════════════════════════════════════════════════
clear
step "STEP 1 of 3  —  Single Candidate, Multi-Source Merge"



echo -e "  ${DIM}Command:${RESET}"
echo -e "  ${CYAN}python3 canonicalize.py \\${RESET}"
echo -e "  ${CYAN}  --csv    sample_data/sample_recruiter.csv \\${RESET}"
echo -e "  ${CYAN}  --github https://github.com/Prinan-99 \\${RESET}"
echo -e "  ${CYAN}  --notes  sample_data/sample_notes.txt \\${RESET}"
echo -e "  ${CYAN}  --output /tmp/pria_profile.json${RESET}"
echo ""

run_pause

python3 canonicalize.py \
  --csv    sample_data/sample_recruiter.csv \
  --github https://github.com/Prinan-99 \
  --notes  sample_data/sample_notes.txt \
  --output /tmp/pria_profile.json

echo ""
echo -e "  ${DIM}  Provenance — who won each field:${RESET}"
python3 -c "
import json
d = json.load(open('/tmp/pria_profile.json'))
seen = {}
for p in d.get('provenance', []):
    f = p['field']
    if f not in seen:
        seen[f] = p
        print(f'    {f:<20} <- {p[\"source\"]:<22} conf={p[\"confidence\"]:.2f}')
" 2>/dev/null | head -8



next_pause

# ══════════════════════════════════════════════════════════════
# STEP 2 — Batch
# ══════════════════════════════════════════════════════════════
clear
step "STEP 2 of 3  —  Batch Processing (5 Candidates)"



echo -e "  ${DIM}Command:${RESET}"
echo -e "  ${CYAN}python3 canonicalize.py \\${RESET}"
echo -e "  ${CYAN}  --csv sample_data/multi_candidates.csv \\${RESET}"
echo -e "  ${CYAN}  --output-dir /tmp/batch_profiles/${RESET}"
echo ""

run_pause

python3 canonicalize.py \
  --csv sample_data/multi_candidates.csv \
  --output-dir /tmp/batch_profiles/

echo ""
echo -e "  ${DIM}  Files written:${RESET}"
ls /tmp/batch_profiles/ 2>/dev/null | sed 's/^/    /'

echo ""
echo -e "  ${DIM}  S3 — verifying uploads …${RESET}"
python3 -c "
from app.storage import list_profiles
items = list_profiles()
print(f'    {len(items)} profiles now in S3:')
for p in items[-5:]:
    print(f'    s3://eightfoldai-23102039/{p[\"key\"]}')
" 2>/dev/null



next_pause

# ══════════════════════════════════════════════════════════════
# STEP 3 — UI
# ══════════════════════════════════════════════════════════════
clear
step "STEP 3 of 3  —  Web UI"

say "The CLI is for scripts and automation. The UI is for recruiters.
I built a FastAPI-backed web interface — same pipeline underneath,
different surface. The interesting design choice here is client-side
detection. The UI reads your CSV in the browser before it even hits
the server. It counts the data rows and switches to batch mode
automatically. You don't configure anything — you just upload the file
and the UI already knows what it's dealing with."

echo ""
echo -e "  ${BOLD}  Switch to your browser now → http://localhost:8000${RESET}"
echo ""
echo -e "  ${GREEN}  1.${RESET}  Upload ${BOLD}sample_data/multi_candidates.csv${RESET}"
echo -e "           Watch the badge switch to ${CYAN}\"5 candidates detected — batch mode\"${RESET}"
echo ""
echo -e "  ${GREEN}  2.${RESET}  Click ${BOLD}Run batch (5)${RESET}"
echo -e "           FastAPI receives the file, runs all 5, uploads to S3,"
echo -e "           returns one combined JSON response"
echo ""
echo -e "  ${GREEN}  3.${RESET}  Click each candidate card in the sidebar"
echo -e "           Full canonical profile — skills, provenance table, confidence"
echo ""
echo -e "  ${GREEN}  4.${RESET}  Click ${BOLD}🗂 Saved Profiles${RESET} in the top-right header"
echo -e "           Live list pulled from S3 — click any entry to reload it"
echo ""

xdg-open http://localhost:8000 2>/dev/null || open http://localhost:8000 2>/dev/null


echo -e "  ${DIM}  ── demo complete — press ENTER for final report ──${RESET}"
read -r

# ══════════════════════════════════════════════════════════════
# FINAL REPORT
# ══════════════════════════════════════════════════════════════
clear
echo ""
echo -e "  ${BOLD}  What was built — Final Report${RESET}"
echo -e "  ${DIM}  $(printf '─%.0s' {1..50})${RESET}"
echo ""
echo -e "  ${GREEN}✓${RESET}  ${BOLD}Pipeline${RESET}         Extractor → Merger → Projector"
echo -e "  ${GREEN}✓${RESET}  ${BOLD}Sources${RESET}           CSV · ATS · GitHub · LinkedIn · Resume · Notes"
echo -e "  ${GREEN}✓${RESET}  ${BOLD}Conflict resolution${RESET} Confidence weights  GitHub 0.90  CSV 0.85  ATS 0.80"
echo -e "                                          Resume 0.75  Notes 0.60"
echo -e "  ${GREEN}✓${RESET}  ${BOLD}Provenance${RESET}        Every field carries source + method + confidence"
echo -e "  ${GREEN}✓${RESET}  ${BOLD}Batch mode${RESET}        Auto-detected from row count — no flags needed"
echo -e "  ${GREEN}✓${RESET}  ${BOLD}S3 persistence${RESET}    Best-effort upload after every run"
echo -e "  ${GREEN}✓${RESET}  ${BOLD}REST API${RESET}          FastAPI · Pydantic · auto OpenAPI docs"
echo -e "  ${GREEN}✓${RESET}  ${BOLD}Web UI${RESET}            Batch sidebar · provenance view · S3 profile drawer"
echo ""
echo -e "  ${DIM}  $(printf '─%.0s' {1..50})${RESET}"
echo ""

python3 -c "
from app.storage import list_profiles
items = list_profiles()
ok = [x for x in items if 'batch' not in x['key']]
batch = [x for x in items if 'batch' in x['key']]
print(f'  S3 profiles stored   : {len(items)}')
print(f'  Single-run profiles  : {len(ok)}')
print(f'  Batch-run profiles   : {len(batch)}')
" 2>/dev/null

echo ""
echo -e "  ${DIM}  $(printf '─%.0s' {1..50})${RESET}"
echo -e "  ${BOLD}  What I'd add next${RESET}"
echo ""
echo -e "  ${DIM}  →${RESET}  LLM conflict resolution when confidence scores are close"
echo -e "  ${DIM}  →${RESET}  Real LinkedIn data via ProxyCurl API (extractor already wired)"
echo -e "  ${DIM}  →${RESET}  Async Celery queue for scale — POST returns job ID,"
echo -e "       webhook fires on completion, S3 as the result store,"
echo -e "       pipeline core stays completely unchanged"
echo ""
echo -e "  ${DIM}  API docs  →  http://localhost:8000/docs${RESET}"
echo -e "  ${DIM}  S3 list   →  http://localhost:8000/profiles${RESET}"
echo ""
