from __future__ import annotations

import traceback
import uuid
from pathlib import Path

from sqlalchemy import desc, select

from app.config import ensure_runtime_dirs, load_config
from app.database import Job, JobLog, session_scope, utcnow
from app.media import burn_subtitles, claim_source, extract_audio, extract_duration_seconds, probe_video
from app.queueing import job_queue
from app.subtitles import srt_to_ass, transcribe_to_srt, translate_srt


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
    ass_path = work_dir / "subtitles" / "final.ass"
    output_name = f"{Path(job.original_filename).stem}_{cfg['translation']['target_language']}_{job_id[:8]}_hardsub.mp4"
    output_path = Path(paths["output_dir"]) / output_name

    def stage(name: str, progress: float, message: str) -> None:
        update_job(job_id, status="running", stage=name, progress=progress)
        log_job(job_id, "info", name, message)

    try:
        update_job(job_id, status="running", stage="claiming_file", progress=1, started_at=utcnow())
        ensure_runtime_dirs(load_config())
        source = claim_source(Path(job.source_path), Path(paths["processing_dir"]), job_id)
        update_job(job_id, processing_path=str(source))

        stage("probing_video", 8, "Probing source video")
        probe = probe_video(source, work_dir / "probe.json", logs_dir / "ffprobe.log")
        update_job(job_id, duration_seconds=extract_duration_seconds(probe))

        stage("extracting_audio", 18, "Extracting mono 16 kHz audio")
        extract_audio(source, audio_path, logs_dir / "ffmpeg_extract.log")

        stage("transcribing", 45, "Transcribing audio with Faster Whisper")
        transcribe_to_srt(audio_path, source_srt, cfg)

        stage("translating", 70, "Translating subtitle cues")
        translate_srt(source_srt, translated_srt, cfg)

        stage("creating_ass", 82, "Generating styled ASS subtitles")
        srt_to_ass(translated_srt, ass_path, cfg)

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
    except Exception as exc:
        detail = traceback.format_exc()
        update_job(job_id, status="failed", stage="failed", error_summary=str(exc), error_detail=detail)
        log_job(job_id, "error", "failed", str(exc), {"traceback": detail})
        raise

