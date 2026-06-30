"""
FastAPI server — wraps the canonicalization pipeline and serves the web UI.

Routes
  GET  /           → HTML UI
  GET  /health     → liveness probe
  POST /canonicalize → multipart form: files + URL fields + optional config
"""

import contextlib
import io
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.pipeline import run as pipeline_run
from app.batch import run_batch, run_batch_iter
from app.storage import upload_profile, upload_batch, list_profiles, get_profile, delete_profile

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

        # Upload to S3 (best-effort — never fail the response)
        try:
            s3_key = upload_profile(result)
            result["_s3_key"] = s3_key
        except Exception:
            pass

        return JSONResponse(content=result)

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    finally:
        for p in tmp_files:
            try:
                os.unlink(p)
            except OSError:
                pass


@app.post("/batch")
async def batch_canonicalize(
    csv_file:     Optional[UploadFile] = File(None),
    ats_file:     Optional[UploadFile] = File(None),
    notes_file:   Optional[UploadFile] = File(None),
    resume_file:  Optional[UploadFile] = File(None),
    config_file:  Optional[UploadFile] = File(None),
    github_url:   Optional[str]        = Form(None),
    linkedin_url: Optional[str]        = Form(None),
    notes_text:   Optional[str]        = Form(None),
    config_json:  Optional[str]        = Form(None),
):
    if not csv_file and not ats_file:
        raise HTTPException(status_code=400, detail="batch requires csv_file or ats_file")

    tmp_files = []

    async def save(upload: UploadFile, suffix: str) -> str:
        content = await upload.read()
        f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        f.write(content)
        f.close()
        tmp_files.append(f.name)
        return f.name

    def save_text(text: str, suffix: str) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=suffix, encoding="utf-8")
        f.write(text)
        f.close()
        tmp_files.append(f.name)
        return f.name

    try:
        csv_path = ats_path = notes_path = resume_path = config_path = None

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
        if config_file and config_file.filename:
            config_path = await save(config_file, ".json")
        elif config_json and config_json.strip():
            config_path = save_text(config_json.strip(), ".json")

        _sink = io.StringIO()
        with contextlib.redirect_stdout(_sink):
            results = run_batch(
                csv_path=csv_path,
                ats_json_path=ats_path,
                github_url=github_url or None,
                resume_path=resume_path,
                notes_path=notes_path,
                linkedin_url=linkedin_url or None,
                output_config_path=config_path,
                print_json=False,
            )

        # Upload batch to S3 (best-effort)
        try:
            s3_keys = upload_batch(results)
        except Exception:
            s3_keys = []

        return JSONResponse(content={"count": len(results), "results": results, "s3_keys": s3_keys})

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    finally:
        for p in tmp_files:
            try:
                os.unlink(p)
            except OSError:
                pass


# ── Streaming batch endpoint ──────────────────────────────────────────────────

@app.post("/batch/stream")
async def batch_stream(
    csv_file:     Optional[UploadFile] = File(None),
    ats_file:     Optional[UploadFile] = File(None),
    notes_file:   Optional[UploadFile] = File(None),
    resume_file:  Optional[UploadFile] = File(None),
    config_file:  Optional[UploadFile] = File(None),
    github_url:   Optional[str]        = Form(None),
    linkedin_url: Optional[str]        = Form(None),
    notes_text:   Optional[str]        = Form(None),
    config_json:  Optional[str]        = Form(None),
):
    """
    Same as /batch but streams results as newline-delimited JSON (NDJSON).
    Each line is one candidate result dict the moment it is ready.
    """
    if not csv_file and not ats_file:
        raise HTTPException(status_code=400, detail="batch requires csv_file or ats_file")

    tmp_files: list[str] = []

    async def save(upload: UploadFile, suffix: str) -> str:
        content = await upload.read()
        f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        f.write(content); f.close()
        tmp_files.append(f.name)
        return f.name

    def save_text(text: str, suffix: str) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=suffix, encoding="utf-8")
        f.write(text); f.close()
        tmp_files.append(f.name)
        return f.name

    csv_path = ats_path = notes_path = resume_path = config_path = None
    if csv_file    and csv_file.filename:    csv_path    = await save(csv_file,    ".csv")
    if ats_file    and ats_file.filename:    ats_path    = await save(ats_file,    ".json")
    if notes_file  and notes_file.filename:  notes_path  = await save(notes_file,  ".txt")
    elif notes_text and notes_text.strip():  notes_path  = save_text(notes_text.strip(), ".txt")
    if resume_file and resume_file.filename: resume_path = await save(resume_file, ".pdf")
    if config_file and config_file.filename: config_path = await save(config_file, ".json")
    elif config_json and config_json.strip(): config_path = save_text(config_json.strip(), ".json")

    async def generate():
        try:
            for result in run_batch_iter(
                csv_path=csv_path,
                ats_json_path=ats_path,
                github_url=github_url or None,
                resume_path=resume_path,
                notes_path=notes_path,
                linkedin_url=linkedin_url or None,
                output_config_path=config_path,
            ):
                # Best-effort S3 upload per candidate
                if "_error" not in result:
                    try:
                        s3_key = upload_profile(result)
                        result["_s3_key"] = s3_key
                    except Exception:
                        pass
                yield json.dumps(result, default=str) + "\n"
        finally:
            for p in tmp_files:
                try:
                    os.unlink(p)
                except OSError:
                    pass

    return StreamingResponse(generate(), media_type="application/x-ndjson")


# ── S3 Profile storage routes ─────────────────────────────────────────────────

@app.get("/profiles")
def profiles_list():
    """List all candidate profiles stored in S3."""
    try:
        items = list_profiles()
        return JSONResponse(content={"count": len(items), "profiles": items})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/profiles/{key:path}")
def profiles_get(key: str):
    """Fetch a single profile from S3 by its key."""
    try:
        profile = get_profile(key)
        return JSONResponse(content=profile)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.delete("/profiles/{key:path}")
def profiles_delete(key: str):
    """Delete a profile from S3."""
    try:
        delete_profile(key)
        return JSONResponse(content={"deleted": key})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
