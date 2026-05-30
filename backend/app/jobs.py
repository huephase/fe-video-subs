from __future__ import annotations

import traceback
import uuid
import shutil
import time
from pathlib import Path

from sqlalchemy import desc, select

from app.config import ensure_runtime_dirs, load_config
from app.database import Job, JobLog, session_scope, utcnow
from app.media import burn_subtitles, claim_source, extract_audio, extract_duration_seconds, probe_video
from app.queueing import job_queue, redis_connection
from app.subtitles import clean_subtitle_quality, srt_to_ass, transcribe_to_srt, translate_srt


def pause_key(job_id: str) -> str:
    return f"job:{job_id}:paused"


class JobCleared(RuntimeError):
    pass


def log_job(job_id: str, level: str, stage: str | None, message: str, metadata: dict | None = None) -> None:
    with session_scope() as session:
        session.add(JobLog(job_id=job_id, level=level, stage=stage, message=message, metadata_json=metadata or {}))


def update_job(job_id: str, **fields) -> None:
    with session_scope() as session:
        job = session.get(Job, job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        for key, value in fields.items():
            setattr(job, key, value)
        job.updated_at = utcnow()


def list_jobs() -> list[Job]:
    with session_scope() as session:
        return list(session.scalars(select(Job).order_by(desc(Job.created_at))).all())


def get_job(job_id: str) -> Job | None:
    with session_scope() as session:
        return session.get(Job, job_id)


def create_job(source_path: str, source_language: str | None, target_language: str | None, auto_start: bool) -> Job:
    cfg = load_config()
    ensure_runtime_dirs(cfg)
    source = Path(source_path)
    root = Path(cfg.paths.video_data_root).resolve()
    resolved = source.resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError("source_path must be inside configured video_data_root")
    if not resolved.exists() or not resolved.is_file():
        raise ValueError("source_path must point to an existing video file")

    job_id = str(uuid.uuid4())
    snapshot = cfg.model_dump()
    if source_language:
        snapshot["whisper"]["source_language"] = source_language
    if target_language:
        snapshot["translation"]["target_language"] = target_language

    job = Job(
        id=job_id,
        source_path=str(resolved),
        work_dir=str(Path(snapshot["paths"]["work_dir"]) / job_id),
        original_filename=resolved.name,
        status="queued",
        stage="queued",
        progress=0,
        file_size_bytes=resolved.stat().st_size,
        target_language=snapshot["translation"]["target_language"],
        source_language=snapshot["whisper"]["source_language"],
        config_snapshot=snapshot,
    )
    with session_scope() as session:
        session.add(job)
    log_job(job_id, "info", "queued", "Job created")
    if auto_start:
        enqueue_job(job_id)
    return get_job(job_id) or job


def enqueue_job(job_id: str) -> None:
    queue = job_queue()
    rq_job = queue.enqueue("app.jobs.process_job", job_id, job_id=f"video-job-{job_id}")
    update_job(job_id, rq_job_id=rq_job.id, status="queued", stage="queued", progress=0)
    log_job(job_id, "info", "queued", "Job enqueued")


def job_logs(job_id: str) -> list[JobLog]:
    with session_scope() as session:
        return list(session.scalars(select(JobLog).where(JobLog.job_id == job_id).order_by(JobLog.created_at)).all())


def mark_interrupted_jobs() -> int:
    interrupted_at = utcnow()
    count = 0
    with session_scope() as session:
        jobs = list(session.scalars(select(Job).where(Job.status.in_(("running", "pausing")))).all())
        for job in jobs:
            job.status = "failed"
            job.error_summary = "Job interrupted by application shutdown"
            job.error_detail = (
                "This job was marked running in the database, but the worker process was not active after startup. "
                "Clear it to remove related working files, or start it again to retry from the beginning."
            )
            job.updated_at = interrupted_at
            session.add(
                JobLog(
                    job_id=job.id,
                    level="error",
                    stage=job.stage,
                    message="Job interrupted by application shutdown",
                    metadata_json={},
                )
            )
            count += 1
    return count


def set_job_paused(job_id: str, paused: bool) -> Job:
    job = get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")
    redis = redis_connection()
    if paused:
        redis.set(pause_key(job_id), "1")
        next_status = "paused" if job.status == "queued" else "pausing"
        update_job(job_id, status=next_status)
        log_job(job_id, "info", job.stage, "Job paused")
    else:
        redis.delete(pause_key(job_id))
        next_status = "queued" if job.stage == "queued" else "running"
        update_job(job_id, status=next_status)
        log_job(job_id, "info", job.stage, "Job resumed")
    refreshed = get_job(job_id)
    if not refreshed:
        raise ValueError(f"Job {job_id} not found")
    return refreshed


def wait_if_paused(job_id: str) -> bool:
    redis = redis_connection()
    logged = False
    while redis.exists(pause_key(job_id)):
        job = get_job(job_id)
        if not job:
            return False
        if not logged:
            update_job(job_id, status="paused")
            log_job(job_id, "info", job.stage, "Worker is paused before the next stage")
            logged = True
        time.sleep(2)
    return get_job(job_id) is not None


def clear_job(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")
    if job.status in {"running", "pausing"}:
        raise ValueError("Running jobs must reach paused status before they can be cleared")

    redis_connection().delete(pause_key(job_id))
    if job.rq_job_id:
        try:
            rq_job = job_queue().fetch_job(job.rq_job_id)
            if rq_job:
                rq_job.cancel()
        except Exception:
            pass

    cfg = job.config_snapshot
    root = Path(cfg["paths"]["video_data_root"]).resolve()
    candidates = [Path(job.work_dir)]
    if job.processing_path:
        candidates.append(Path(job.processing_path).parent)
    if job.output_path:
        candidates.append(Path(job.output_path))

    for path in candidates:
        resolved = path.resolve()
        if root not in resolved.parents and resolved != root:
            continue
        if resolved.is_dir():
            shutil.rmtree(resolved, ignore_errors=True)
        elif resolved.exists():
            resolved.unlink()

    with session_scope() as session:
        session.query(JobLog).filter(JobLog.job_id == job_id).delete()
        stored = session.get(Job, job_id)
        if stored:
            session.delete(stored)


def process_job(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")
    cfg = job.config_snapshot
    paths = cfg["paths"]
    work_dir = Path(job.work_dir)
    logs_dir = work_dir / "logs"
    audio_path = work_dir / "audio" / "source.wav"
    source_srt = work_dir / "transcript" / "source.srt"
    translated_srt = work_dir / "translation" / f"translated.{cfg['translation']['target_language']}.srt"
    cleaned_srt = work_dir / "translation" / f"cleaned.{cfg['translation']['target_language']}.srt"
    ass_path = work_dir / "subtitles" / "final.ass"
    output_name = f"{Path(job.original_filename).stem}_{cfg['translation']['target_language']}_{job_id[:8]}_hardsub.mp4"
    output_path = Path(paths["output_dir"]) / output_name

    def stage(name: str, progress: float, message: str) -> None:
        if not wait_if_paused(job_id):
            raise JobCleared("Job was cleared while paused")
        update_job(job_id, status="running", stage=name, progress=progress)
        log_job(job_id, "info", name, message)

    try:
        if not wait_if_paused(job_id):
            return
        update_job(job_id, status="running", stage="claiming_file", progress=1, started_at=utcnow())
        ensure_runtime_dirs(load_config())
        source = claim_source(Path(job.source_path), Path(paths["processing_dir"]), job_id)
        update_job(job_id, processing_path=str(source))

        stage("probing_video", 8, "Probing source video")
        probe = probe_video(source, work_dir / "probe.json", logs_dir / "ffprobe.log")
        update_job(job_id, duration_seconds=extract_duration_seconds(probe))

        stage("extracting_audio", 18, "Extracting normalized mono 16 kHz audio")
        extract_audio(source, audio_path, logs_dir / "ffmpeg_extract.log", cfg)

        stage("transcribing", 45, "Transcribing audio with Faster Whisper")
        transcribe_to_srt(audio_path, source_srt, cfg)

        stage("translating", 70, "Translating subtitle cues")
        translate_srt(source_srt, translated_srt, cfg)

        stage("cleaning_subtitles", 78, "Applying subtitle timing and line-length quality rules")
        clean_subtitle_quality(translated_srt, cleaned_srt, cfg)

        stage("creating_ass", 84, "Generating styled ASS subtitles")
        srt_to_ass(cleaned_srt, ass_path, cfg)

        stage("burning_subtitles", 92, "Burning subtitles into final video")
        burn_subtitles(source, ass_path, output_path, cfg, logs_dir / "burn.log")

        update_job(
            job_id,
            status="completed",
            stage="completed",
            progress=100,
            output_path=str(output_path),
            completed_at=utcnow(),
            error_summary=None,
            error_detail=None,
        )
        log_job(job_id, "info", "completed", "Final video saved", {"output_path": str(output_path)})
    except JobCleared:
        return
    except Exception as exc:
        detail = traceback.format_exc()
        update_job(job_id, status="failed", stage="failed", error_summary=str(exc), error_detail=detail)
        log_job(job_id, "error", "failed", str(exc), {"traceback": detail})
        raise
