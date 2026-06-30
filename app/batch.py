"""
Batch processor: runs pipeline.run() once per candidate.

Sources
  CSV   — one candidate per row
  ATS   — one candidate per record (handles list / {"candidates":[...]} / {"data":{...}})

Other sources (GitHub URL, resume, notes) are shared across all candidates
when provided — useful for a single notes file that applies to everyone,
or a single GitHub org URL that isn't per-candidate.
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_tmp(content: str, suffix: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8")
    f.write(content)
    f.close()
    return f.name


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


def _csv_rows(path: str) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


def _row_to_csv_text(fieldnames: list[str], row: dict) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerow(row)
    return buf.getvalue()


def _ats_record_to_text(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False)


# ── Main batch runner ─────────────────────────────────────────────────────────

def count_candidates(csv_path: str | None, ats_json_path: str | None) -> int:
    """Quick peek: how many candidates are in these sources combined?"""
    total = 0
    if csv_path:
        try:
            total += max(len(_csv_rows(csv_path)), 0)
        except Exception:
            pass
    if ats_json_path:
        try:
            total += max(len(_load_ats_records(ats_json_path)), 0)
        except Exception:
            pass
    return total


def _build_candidates(csv_path: str | None, ats_json_path: str | None) -> list[dict]:
    """Shared helper: build the ordered list of per-candidate input dicts."""
    candidates: list[dict] = []

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
                })

    if ats_json_path:
        records = _load_ats_records(ats_json_path)
        if records:
            for rec in records:
                name = (
                    rec.get("candidate_name") or rec.get("name") or
                    rec.get("full_name") or f"record-{len(candidates)+1}"
                )
                idx = len([c for c in candidates if c.get("ats_text") is None
                           and c.get("csv_text") is not None])
                if csv_path and idx <= len(candidates) - 1:
                    candidates[len(candidates) - idx - 1]["ats_text"] = _ats_record_to_text(rec)
                else:
                    candidates.append({
                        "label": str(name),
                        "csv_text": None,
                        "ats_text": _ats_record_to_text(rec),
                    })

    return candidates


def run_batch_iter(
    csv_path: str | None = None,
    ats_json_path: str | None = None,
    github_url: str | None = None,
    resume_path: str | None = None,
    notes_path: str | None = None,
    linkedin_url: str | None = None,
    output_config_path: str | None = None,
) -> Any:
    """
    Generator version of run_batch.
    Yields one result dict per candidate the moment it is ready.
    Each dict has an added '_progress' key: {i, total, elapsed_ms, name}.
    """
    candidates = _build_candidates(csv_path, ats_json_path)
    total = len(candidates)

    if not candidates:
        return

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
                    resume_path=resume_path,
                    ats_json_path=tmp_ats,
                    notes_path=notes_path,
                    linkedin_url=linkedin_url,
                    output_config_path=output_config_path,
                    candidate_id=None,
                )

            elapsed_ms = (time.perf_counter() - t0) * 1000
            name = result.get("full_name") or cand["label"]
            result["_batch_label"] = cand["label"]
            result["_progress"] = {"i": i, "total": total,
                                   "name": name, "elapsed_ms": round(elapsed_ms)}

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            result = {
                "_batch_label": cand["label"],
                "_error": str(exc),
                "_progress": {"i": i, "total": total,
                              "name": cand["label"], "elapsed_ms": round(elapsed_ms)},
            }

        finally:
            for p in [tmp_csv, tmp_ats]:
                if p:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass

        yield result


def run_batch(
    csv_path: str | None = None,
    ats_json_path: str | None = None,
    github_url: str | None = None,
    resume_path: str | None = None,
    notes_path: str | None = None,
    linkedin_url: str | None = None,
    output_config_path: str | None = None,
    output_dir: str | None = None,
    pretty: bool = True,
    print_json: bool = False,
) -> list[dict[str, Any]]:
    """
    Process every candidate found in the CSV and/or ATS JSON.
    Returns list of result dicts (one per candidate).
    Prints a live progress line for each candidate.
    """

    candidates = _build_candidates(csv_path, ats_json_path)
    if not candidates:
        print("[batch] No candidates found. Provide a --csv or --ats with data.")
        return []

    total = len(candidates)
    print(f"\nProcessing {total} candidate{'s' if total > 1 else ''}\n")

    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    tmp_files: list[str] = []

    try:
        for i, cand in enumerate(candidates, 1):
            t0 = time.perf_counter()
            tmp_csv = tmp_ats = None

            try:
                if cand.get("csv_text"):
                    tmp_csv = _write_tmp(cand["csv_text"], ".csv")
                    tmp_files.append(tmp_csv)

                if cand.get("ats_text"):
                    tmp_ats = _write_tmp(cand["ats_text"], ".json")
                    tmp_files.append(tmp_ats)

                _sink = io.StringIO()
                with contextlib.redirect_stdout(_sink):
                    result = pipeline_run(
                        csv_path=tmp_csv,
                        github_url=github_url,
                        resume_path=resume_path,
                        ats_json_path=tmp_ats,
                        notes_path=notes_path,
                        linkedin_url=linkedin_url,
                        output_config_path=output_config_path,
                        candidate_id=None,
                    )

                elapsed_ms = (time.perf_counter() - t0) * 1000
                conf   = result.get("overall_confidence") or 0
                skills = len(result.get("skills") or [])
                name   = result.get("full_name") or cand["label"]

                result["_batch_label"] = cand["label"]
                results.append(result)

                indent = 2 if pretty else None
                json_str = json.dumps(result, indent=indent, default=str, ensure_ascii=False)

                if print_json:
                    W = 52
                    dim, reset = "\033[90m", "\033[0m"
                    print(f"\n{'─'*W}")
                    print(f"  [{i}/{total}]  {name}  "
                          f"{dim}conf={conf:.3f}  skills={skills}  {elapsed_ms:.0f}ms{reset}")
                    print(f"{'─'*W}")
                    print(json_str)
                else:
                    status = "\033[32m✓\033[0m"
                    print(f"  [{i:>{len(str(total))}}/{total}] {status} {name:<28} "
                          f"conf={conf:.2f}  skills={skills:<3}  {elapsed_ms:.0f}ms")

                if output_dir:
                    slug = "".join(c if c.isalnum() else "_" for c in name)[:40]
                    out_path = Path(output_dir) / f"{i:03d}_{slug}.json"
                    out_path.write_text(json_str, encoding="utf-8")

            except Exception as exc:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                status = "\033[31m✗\033[0m"
                print(f"  [{i:>{len(str(total))}}/{total}] {status} {cand['label']:<28} "
                      f"ERROR: {exc}  {elapsed_ms:.0f}ms")
                results.append({"_batch_label": cand["label"], "_error": str(exc)})

    finally:
        for p in tmp_files:
            try:
                os.unlink(p)
            except OSError:
                pass

    # ── Summary ───────────────────────────────────────────────────────────
    ok  = [r for r in results if "_error" not in r]
    err = [r for r in results if "_error" in r]
    avg_conf = sum(r.get("overall_confidence") or 0 for r in ok) / len(ok) if ok else 0

    print(f"\n{'─'*50}")
    print(f"  Total     : {total}")
    print(f"  Succeeded : {len(ok)}")
    print(f"  Failed    : {len(err)}")
    if ok:
        print(f"  Avg conf  : {avg_conf:.3f}")
    if output_dir:
        print(f"  Output    : {Path(output_dir).resolve()}/")
    print(f"{'─'*50}\n")

    return results
