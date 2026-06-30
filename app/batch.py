"""
Batch processor: runs pipeline.run() once per candidate.

Sources
  CSV          — one candidate per row
  ATS          — one candidate per record
  Resume PDFs  — one candidate per file (when multiple uploaded)
                 single resume: applied as shared source to all CSV/ATS candidates

Shared sources (github_url, notes, linkedin_url) are applied to every candidate.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from app.pipeline import run as pipeline_run


def _write_tmp(content: str, suffix: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8")
    f.write(content)
    f.close()
    return f.name


def _csv_rows(path: str) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def _row_to_csv_text(fieldnames: list[str], row: dict) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerow(row)
    return buf.getvalue()


def _load_ats_records(path: str) -> list[dict]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("candidates", "data", "records", "results"):
            if key in raw:
                val = raw[key]
                return val if isinstance(val, list) else [val]
        return [raw]
    return []


def run_batch(
    csv_path: str | None = None,
    ats_json_path: str | None = None,
    github_url: str | None = None,
    resume_paths: list[str] | None = None,
    resume_labels: list[str] | None = None,
    notes_path: str | None = None,
    linkedin_url: str | None = None,
    output_config_path: str | None = None,
) -> list[dict[str, Any]]:
    """
    Process every candidate found across CSV rows, ATS records, and/or resume PDFs.

    When multiple resumes are provided each becomes its own candidate.
    When only one resume is provided it is treated as a shared source applied to
    every CSV / ATS candidate (backwards-compatible behaviour).
    """
    candidates: list[dict] = []

    # Multiple resumes → each PDF is a standalone candidate
    # Single resume   → shared source; don't create a resume-only candidate
    multi_resume = resume_paths and len(resume_paths) > 1
    shared_resume = resume_paths[0] if (resume_paths and not multi_resume) else None

    if csv_path:
        rows = _csv_rows(csv_path)
        if rows:
            fieldnames = list(rows[0].keys())
            for row in rows:
                name = (
                    row.get("name") or row.get("full_name") or
                    row.get("candidate_name") or f"row-{len(candidates)+1}"
                ).strip()
                candidates.append({
                    "label": name,
                    "csv_text": _row_to_csv_text(fieldnames, row),
                    "ats_text": None,
                    "resume_path": shared_resume,
                })

    if ats_json_path:
        for rec in _load_ats_records(ats_json_path):
            name = (
                rec.get("candidate_name") or rec.get("name") or
                rec.get("full_name") or f"record-{len(candidates)+1}"
            )
            candidates.append({
                "label": str(name),
                "csv_text": None,
                "ats_text": json.dumps(rec, ensure_ascii=False),
                "resume_path": shared_resume,
            })

    if multi_resume:
        for idx, path in enumerate(resume_paths):  # type: ignore[union-attr]
            raw_label = (resume_labels[idx] if resume_labels and idx < len(resume_labels) else None) or Path(path).stem
            label = Path(raw_label).stem  # strip extension if filename was passed
            candidates.append({
                "label": label,
                "csv_text": None,
                "ats_text": None,
                "resume_path": path,
            })

    if not candidates:
        return []

    total = len(candidates)
    results: list[dict[str, Any]] = []

    for i, cand in enumerate(candidates, 1):
        t0 = time.perf_counter()
        tmp_csv = tmp_ats = None
        try:
            if cand.get("csv_text"):
                tmp_csv = _write_tmp(cand["csv_text"], ".csv")
            if cand.get("ats_text"):
                tmp_ats = _write_tmp(cand["ats_text"], ".json")

            _sink = io.StringIO()
            with contextlib.redirect_stdout(_sink):
                result = pipeline_run(
                    csv_path=tmp_csv,
                    github_url=github_url,
                    resume_path=cand.get("resume_path"),
                    ats_json_path=tmp_ats,
                    notes_path=notes_path,
                    linkedin_url=linkedin_url,
                    output_config_path=output_config_path,
                )

            elapsed_ms = round((time.perf_counter() - t0) * 1000)
            result["_batch_label"] = cand["label"]
            result["_progress"] = {
                "i": i, "total": total,
                "name": result.get("full_name") or cand["label"],
                "elapsed_ms": elapsed_ms,
            }
            results.append(result)

        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - t0) * 1000)
            results.append({
                "_batch_label": cand["label"],
                "_error": str(exc),
                "_progress": {"i": i, "total": total, "name": cand["label"], "elapsed_ms": elapsed_ms},
            })
        finally:
            for p in [tmp_csv, tmp_ats]:
                if p:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass

    return results
