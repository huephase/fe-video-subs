from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.config import ensure_runtime_dirs, load_config, save_config
from app.database import init_db
from app.jobs import clear_job, create_job, enqueue_job, get_job, job_logs, list_jobs, set_job_paused
from app.schemas import CreateJobRequest, JobLogOut, JobOut


app = FastAPI(title="Video Subtitle Studio")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    init_db()
    ensure_runtime_dirs(load_config())


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "api"}


@app.get("/api/config")
def read_config() -> dict:
    return load_config().model_dump()


@app.put("/api/config")
def update_config(payload: dict) -> dict:
    cfg = save_config(payload)
    ensure_runtime_dirs(cfg)
    return cfg.model_dump()


@app.get("/api/watch/files")
def watch_files() -> list[dict]:
    cfg = load_config()
    watch_dir = Path(cfg.paths.watch_dir)
    if not watch_dir.exists():
        return []
    return [
        {"path": str(path), "name": path.name, "size": path.stat().st_size, "modified_at": path.stat().st_mtime}
        for path in sorted(watch_dir.iterdir())
        if path.is_file()
    ]


@app.post("/api/jobs", response_model=JobOut)
def create_job_endpoint(req: CreateJobRequest) -> JobOut:
    try:
        job = create_job(req.source_path, req.source_language, req.target_language, req.auto_start)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JobOut.model_validate(job)


@app.get("/api/jobs", response_model=list[JobOut])
def list_jobs_endpoint() -> list[JobOut]:
    return [JobOut.model_validate(job) for job in list_jobs()]


@app.get("/api/jobs/{job_id}", response_model=JobOut)
def get_job_endpoint(job_id: str) -> JobOut:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobOut.model_validate(job)


@app.post("/api/jobs/{job_id}/start", response_model=JobOut)
def start_job_endpoint(job_id: str) -> JobOut:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in {"queued", "failed"}:
        raise HTTPException(status_code=400, detail="Only queued or failed jobs can be started")
    enqueue_job(job_id)
    refreshed = get_job(job_id)
    return JobOut.model_validate(refreshed)


@app.post("/api/jobs/{job_id}/pause", response_model=JobOut)
def pause_job_endpoint(job_id: str) -> JobOut:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in {"queued", "running"}:
        raise HTTPException(status_code=400, detail="Only queued or running jobs can be paused")
    return JobOut.model_validate(set_job_paused(job_id, True))


@app.post("/api/jobs/{job_id}/resume", response_model=JobOut)
def resume_job_endpoint(job_id: str) -> JobOut:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in {"paused", "pausing"}:
        raise HTTPException(status_code=400, detail="Only paused jobs can be resumed")
    return JobOut.model_validate(set_job_paused(job_id, False))


@app.delete("/api/jobs/{job_id}")
def clear_job_endpoint(job_id: str) -> dict:
    try:
        clear_job(job_id)
    except ValueError as exc:
        message = str(exc)
        if "not found" in message:
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    return {"status": "cleared", "job_id": job_id}


@app.get("/api/jobs/{job_id}/logs", response_model=list[JobLogOut])
def get_job_logs_endpoint(job_id: str) -> list[JobLogOut]:
    return [JobLogOut.model_validate(log) for log in job_logs(job_id)]


@app.get("/api/events/stream")
async def events_stream() -> StreamingResponse:
    async def emit():
        while True:
            payload = [JobOut.model_validate(job).model_dump(mode="json") for job in list_jobs()]
            yield f"data: {json.dumps({'jobs': payload})}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(emit(), media_type="text/event-stream")
