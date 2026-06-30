"""
FastAPI server — wraps the canonicalization pipeline and serves the web UI.

Routes
  GET  /           → HTML UI
  GET  /health     → liveness probe
  POST /canonicalize → multipart form: files + URL fields + optional config
"""

import contextlib
import io
import os
import tempfile
from pathlib import Path
from typing import List, Optional

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.pipeline import run as pipeline_run
from app.batch import run_batch

app = FastAPI(title="Candidate Canonicalization API", version="1.0.0")

STATIC_DIR = Path(__file__).parent.parent / "front-end"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/canonicalize")
async def canonicalize(
    csv_file:     Optional[UploadFile] = File(None),
    ats_file:     Optional[UploadFile] = File(None),
    notes_file:   Optional[UploadFile] = File(None),
    resume_file:  Optional[UploadFile] = File(None),
    config_file:  Optional[UploadFile] = File(None),
    github_url:   Optional[str]        = Form(None),
    linkedin_url: Optional[str]        = Form(None),
    notes_text:   Optional[str]        = Form(None),
    config_json:  Optional[str]        = Form(None),
    candidate_id: Optional[str]        = Form(None),
):
    tmp_files = []

    async def save(upload: UploadFile, suffix: str) -> str:
        content = await upload.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"{upload.filename} exceeds the 10 MB upload limit ({len(content)//1024//1024} MB received)."
            )
        f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        f.write(content)
        f.close()
        tmp_files.append(f.name)
        return f.name

    def save_text(text: str, suffix: str) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=suffix,
                                        encoding="utf-8")
        f.write(text)
        f.close()
        tmp_files.append(f.name)
        return f.name

    try:
        csv_path = notes_path = ats_path = resume_path = config_path = None

        if csv_file and csv_file.filename:
            csv_path = await save(csv_file, ".csv")

        if ats_file and ats_file.filename:
            ats_path = await save(ats_file, ".json")

        if notes_file and notes_file.filename:
            notes_path = await save(notes_file, ".txt")
        elif notes_text and notes_text.strip():
            notes_path = save_text(notes_text.strip(), ".txt")

        if resume_file and resume_file.filename:
            resume_path = await save(resume_file, ".pdf")

        # output config — file takes priority over pasted JSON
        if config_file and config_file.filename:
            config_path = await save(config_file, ".json")
        elif config_json and config_json.strip():
            config_path = save_text(config_json.strip(), ".json")

        _sink = io.StringIO()
        with contextlib.redirect_stdout(_sink):
            result = pipeline_run(
                csv_path=csv_path,
                github_url=github_url or None,
                resume_path=resume_path,
                ats_json_path=ats_path,
                notes_path=notes_path,
                linkedin_url=linkedin_url or None,
                output_config_path=config_path,
                candidate_id=candidate_id or None,
            )
        return JSONResponse(content=result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    finally:
        for p in tmp_files:
            try:
                os.unlink(p)
            except OSError:
                pass


# ── Batch endpoint ────────────────────────────────────────────────────────────

@app.post("/batch")
async def batch_canonicalize(
    csv_file:      Optional[UploadFile]  = File(None),
    ats_file:      Optional[UploadFile]  = File(None),
    notes_file:    Optional[UploadFile]  = File(None),
    resume_files:  List[UploadFile]      = File(default=[]),
    config_file:   Optional[UploadFile]  = File(None),
    github_url:    Optional[str]         = Form(None),
    linkedin_url:  Optional[str]         = Form(None),
    notes_text:    Optional[str]         = Form(None),
    config_json:   Optional[str]         = Form(None),
):
    has_csv    = csv_file and csv_file.filename
    has_ats    = ats_file and ats_file.filename
    valid_resumes = [f for f in resume_files if f and f.filename]
    if not has_csv and not has_ats and not valid_resumes:
        raise HTTPException(status_code=400, detail="Batch requires csv_file, ats_file, or at least one resume_files.")

    tmp_files: list[str] = []

    async def save(upload: UploadFile, suffix: str) -> str:
        content = await upload.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"{upload.filename} exceeds the 10 MB upload limit ({len(content)//1024//1024} MB received)."
            )
        f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        f.write(content); f.close()
        tmp_files.append(f.name)
        return f.name

    def save_text(text: str, suffix: str) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=suffix, encoding="utf-8")
        f.write(text); f.close()
        tmp_files.append(f.name)
        return f.name

    try:
        csv_path = ats_path = notes_path = config_path = None
        resume_paths: list[str] = []

        if has_csv:
            csv_path = await save(csv_file, ".csv")
        if has_ats:
            ats_path = await save(ats_file, ".json")
        if notes_file and notes_file.filename:
            notes_path = await save(notes_file, ".txt")
        elif notes_text and notes_text.strip():
            notes_path = save_text(notes_text.strip(), ".txt")
        for rf in valid_resumes:
            resume_paths.append(await save(rf, ".pdf"))
        if config_file and config_file.filename:
            config_path = await save(config_file, ".json")
        elif config_json and config_json.strip():
            config_path = save_text(config_json.strip(), ".json")

        results = run_batch(
            csv_path=csv_path,
            ats_json_path=ats_path,
            github_url=github_url or None,
            resume_paths=resume_paths or None,
            resume_labels=[rf.filename for rf in valid_resumes] if resume_paths else None,
            notes_path=notes_path,
            linkedin_url=linkedin_url or None,
            output_config_path=config_path,
        )

        return JSONResponse(content={"count": len(results), "results": results})

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    finally:
        for p in tmp_files:
            try:
                os.unlink(p)
            except OSError:
                pass
