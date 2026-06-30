#!/usr/bin/env python3
"""
Eightfold Assignment — Multi-Source Candidate Data Transformer
CLI entry point.

Single candidate:
  python3 canonicalize.py --csv sample_data/sample_recruiter.csv --github https://github.com/Prinan-99

All sources:
  python3 canonicalize.py \\
    --csv   sample_data/sample_recruiter.csv \\
    --ats   sample_data/sample_ats.json \\
    --github https://github.com/Prinan-99 \\
    --notes sample_data/sample_notes.txt \\
    --resume "path/to/resume.pdf" \\
    --config config/sample_config.json \\
    --output sample_data/pria_output_custom.json

Multi-candidate (auto-detected — no flag needed):
  python3 canonicalize.py --csv sample_data/multi_candidates.csv
  python3 canonicalize.py --csv sample_data/multi_candidates.csv --output-dir batch_output/
"""

import contextlib
import io
import json
import sys
import time
from pathlib import Path

import click

from app.pipeline import run


# ── Display helpers ───────────────────────────────────────────────────────────

W = 52

def _line(char="─"): return char * W

def _src(label: str, value: str | None, width: int = 16) -> None:
    if value:
        short = Path(value).name if Path(value).exists() else value
        if len(short) > 32:
            short = "…" + short[-31:]
        click.echo(f"  \033[32m✓\033[0m  {label:<{width}} {short}")
    else:
        click.echo(f"  \033[90m–\033[0m  \033[90m{label:<{width}} not provided\033[0m")

def _bar(value: float, width: int = 12) -> str:
    filled = round(value * width)
    return "█" * filled + "░" * (width - filled)

def _print_summary(result: dict, output_path: str | None, elapsed: float) -> None:
    conf   = result.get("overall_confidence") or 0
    name   = result.get("full_name") or "—"
    skills = result.get("skills") or []
    emails = result.get("emails") or []
    phones = result.get("phones") or []
    exp    = result.get("experience") or []
    edu    = result.get("education") or []
    loc    = result.get("location") or {}
    prov   = result.get("provenance") or []

    loc_str = ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")]))
    sources = sorted({p["source"] for p in prov if p.get("source")})

    if skills and isinstance(skills[0], dict):
        skill_names = [s.get("name", "") for s in skills]
    else:
        skill_names = [str(s) for s in skills]

    conf_color = "\033[32m" if conf >= .85 else "\033[33m" if conf >= .70 else "\033[31m"

    click.echo(_line())
    click.echo(f"  {name}")
    if result.get("headline"):
        click.echo(f"  \033[90m{result['headline']}\033[0m")
    click.echo()
    click.echo(f"  Confidence   {conf_color}{conf:.3f}\033[0m  {_bar(conf)}")
    click.echo(f"  Time         {elapsed*1000:.0f}ms")
    click.echo()
    if emails:
        click.echo(f"  Email        {emails[0]}")
    if phones:
        click.echo(f"  Phone        {phones[0]}")
    if loc_str:
        click.echo(f"  Location     {loc_str}")
    if result.get("years_experience"):
        click.echo(f"  Experience   {result['years_experience']:.1f} yrs")
    if skill_names:
        preview = ", ".join(skill_names[:6])
        more    = f"  +{len(skill_names)-6} more" if len(skill_names) > 6 else ""
        click.echo(f"  Skills ({len(skill_names)})  {preview}{more}")
    if exp:
        e = exp[0]
        click.echo(f"  Last role    {e.get('title','')} at {e.get('company','')}")
    if edu:
        e = edu[0]
        click.echo(f"  Education    {e.get('institution','')}")
    if sources:
        click.echo(f"  Sources      {', '.join(sources)}")
    if prov:
        conflicts = sum(1 for p in prov if p.get("conflict"))
        click.echo(f"  Provenance   {len(prov)} entries" +
                   (f"  \033[33m{conflicts} conflict(s)\033[0m" if conflicts else ""))
    click.echo()
    if output_path:
        click.echo(f"  Saved  →  {output_path}")
    click.echo(_line())


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.command()
@click.option("--csv",        "csv_path",      default=None, help="Recruiter CSV")
@click.option("--github",     "github_url",    default=None, help="GitHub profile URL")
@click.option("--resume",     "resume_path",   default=None, help="Resume PDF")
@click.option("--ats",        "ats_json_path", default=None, help="ATS JSON export")
@click.option("--notes",      "notes_path",    default=None, help="Recruiter notes .txt")
@click.option("--linkedin",   "linkedin_url",  default=None, help="LinkedIn URL (needs PROXYCURL_API_KEY)")
@click.option("--config",     "config_path",   default=None, help="Output config JSON")
@click.option("--output","-o","output_path",   default=None, help="Write result(s) to file")
@click.option("--id",         "candidate_id",  default=None, help="Explicit candidate_id (single mode)")
@click.option("--pretty/--compact", default=True, help="Pretty-print JSON")
@click.option("--output-dir", "output_dir",    default=None, help="Save one JSON per candidate here")
@click.option("--quiet",      "quiet",         is_flag=True, default=False,
              help="Suppress UI chrome; emit only JSON")
def main(
    csv_path, github_url, resume_path, ats_json_path,
    notes_path, linkedin_url, config_path, output_path,
    candidate_id, pretty, output_dir, quiet,
):
    """Multi-source candidate data transformer.

    Automatically detects multiple candidates in --csv / --ats and
    processes each one independently, printing JSON per candidate.
    """

    if not any([csv_path, github_url, resume_path, ats_json_path, notes_path, linkedin_url]):
        click.echo("Error: provide at least one source.", err=True)
        sys.exit(1)

    # ── Detect candidate count ────────────────────────────────────────────
    from app.batch import count_candidates, run_batch

    n = count_candidates(csv_path, ats_json_path) if (csv_path or ats_json_path) else 1
    is_multi = n > 1

    # ── Multi-candidate path ──────────────────────────────────────────────
    if is_multi:
        if not quiet:
            click.echo()
            click.echo(_line())
            click.echo("  Candidate Data Transformer")
            click.echo(_line())
            _src("Recruiter CSV", csv_path)
            _src("ATS JSON",      ats_json_path)
            _src("GitHub",        github_url)
            _src("LinkedIn",      linkedin_url)
            _src("Resume PDF",    resume_path)
            _src("Notes",         notes_path)
            if config_path:
                click.echo(f"  \033[90m  Config           {Path(config_path).name}\033[0m")
            click.echo(_line())
            click.echo(f"  {n} candidates detected\n")

        # Print per-candidate JSON only when no output destination is set
        _print_json = not quiet and not output_path and not output_dir

        results = run_batch(
            csv_path=csv_path,
            ats_json_path=ats_json_path,
            github_url=github_url,
            resume_path=resume_path,
            notes_path=notes_path,
            linkedin_url=linkedin_url,
            output_config_path=config_path,
            output_dir=output_dir,
            pretty=pretty,
            print_json=_print_json,
        )

        if output_path:
            Path(output_path).write_text(
                json.dumps(results, indent=2 if pretty else None,
                           default=str, ensure_ascii=False),
                encoding="utf-8",
            )
            if not quiet:
                click.echo(f"\n  All {n} results → {output_path}")

        if quiet:
            click.echo(json.dumps(results, indent=2 if pretty else None,
                                  default=str, ensure_ascii=False))
        return

    # ── Single candidate path ─────────────────────────────────────────────
    if not quiet:
        click.echo()
        click.echo(_line())
        click.echo("  Candidate Data Transformer")
        click.echo(_line())
        click.echo("  Sources")
        _src("Recruiter CSV",  csv_path)
        _src("ATS JSON",       ats_json_path)
        _src("GitHub",         github_url)
        _src("LinkedIn",       linkedin_url)
        _src("Resume PDF",     resume_path)
        _src("Notes",          notes_path)
        if config_path:
            click.echo(f"  \033[90m  Config           {Path(config_path).name}\033[0m")
        click.echo(_line())
        click.echo("  Running pipeline…")
        click.echo()

    t0 = time.perf_counter()
    _sink = io.StringIO()
    with contextlib.redirect_stdout(_sink):
        result = run(
            csv_path=csv_path, github_url=github_url, resume_path=resume_path,
            ats_json_path=ats_json_path, notes_path=notes_path, linkedin_url=linkedin_url,
            output_config_path=config_path, candidate_id=candidate_id,
        )
    elapsed = time.perf_counter() - t0

    indent   = 2 if pretty else None
    json_str = json.dumps(result, indent=indent, default=str, ensure_ascii=False)

    if output_path:
        Path(output_path).write_text(json_str, encoding="utf-8")

    if quiet:
        click.echo(json_str)
    else:
        _print_summary(result, output_path, elapsed)
        # Print JSON to stdout only when not saving to a file
        if not output_path:
            click.echo()
            click.echo(json_str)


if __name__ == "__main__":
    main()
