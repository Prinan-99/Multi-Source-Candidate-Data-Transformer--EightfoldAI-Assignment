#!/usr/bin/env python3
"""
Eightfold Assignment — Multi-Source Candidate Data Transformer
CLI entry point.

Usage examples
──────────────
# Structured (CSV) + unstructured (GitHub):
python canonicalize.py --csv sample_data/recruiter.csv --github https://github.com/Prinan-99

# All three sources:
python canonicalize.py \
  --csv sample_data/recruiter.csv \
  --github https://github.com/Prinan-99 \
  --resume "/home/pria/Downloads/Pria Nandhini Resume - Final.pdf"

# With a custom output config:
python canonicalize.py \
  --csv sample_data/recruiter.csv \
  --github https://github.com/Prinan-99 \
  --config config/sample_config.json \
  --output candidate_output.json
"""

import json
import sys
from pathlib import Path

import click

from app.pipeline import run


@click.command()
@click.option("--csv", "csv_path", default=None, help="Path to recruiter CSV file")
@click.option("--github", "github_url", default=None, help="GitHub profile URL or username")
@click.option("--resume", "resume_path", default=None, help="Path to resume PDF")
@click.option("--ats", "ats_json_path", default=None, help="Path to ATS JSON blob")
@click.option("--notes", "notes_path", default=None, help="Path to recruiter notes .txt file")
@click.option("--linkedin", "linkedin_url", default=None, help="LinkedIn profile URL (requires PROXYCURL_API_KEY)")
@click.option("--config", "config_path", default=None, help="Path to output config JSON")
@click.option("--output", "-o", "output_path", default=None, help="Write JSON to this file (default: stdout)")
@click.option("--id", "candidate_id", default=None, help="Explicit candidate_id (default: auto-generated)")
@click.option("--pretty/--compact", default=True, help="Pretty-print JSON (default: pretty)")
def main(
    csv_path: str | None,
    github_url: str | None,
    resume_path: str | None,
    ats_json_path: str | None,
    notes_path: str | None,
    linkedin_url: str | None,
    config_path: str | None,
    output_path: str | None,
    candidate_id: str | None,
    pretty: bool,
) -> None:
    """Transform multi-source candidate data into a single canonical profile."""

    if not any([csv_path, github_url, resume_path, ats_json_path, notes_path, linkedin_url]):
        click.echo(
            "Error: provide at least one source (--csv, --github, --resume, --ats).",
            err=True,
        )
        sys.exit(1)

    result = run(
        csv_path=csv_path,
        github_url=github_url,
        resume_path=resume_path,
        ats_json_path=ats_json_path,
        notes_path=notes_path,
        linkedin_url=linkedin_url,
        output_config_path=config_path,
        candidate_id=candidate_id,
    )

    indent = 2 if pretty else None
    json_str = json.dumps(result, indent=indent, default=str, ensure_ascii=False)

    if output_path:
        Path(output_path).write_text(json_str, encoding="utf-8")
        click.echo(f"Output written to {output_path}")
    else:
        click.echo(json_str)


if __name__ == "__main__":
    main()
