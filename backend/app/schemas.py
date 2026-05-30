from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CreateJobRequest(BaseModel):
    source_path: str
    source_language: str | None = None
    target_language: str | None = None
    custom_subtitle_path: str | None = None
    auto_start: bool = True


class JobOut(BaseModel):
    id: str
    source_path: str
    processing_path: str | None
    output_path: str | None
    work_dir: str
    original_filename: str
    status: str
    stage: str
    progress: float
    duration_seconds: float | None
    file_size_bytes: int | None
    target_language: str
    source_language: str | None
    uses_custom_subtitle: bool
    custom_subtitle_filename: str | None
    error_summary: str | None
    error_detail: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime

    class Config:
        from_attributes = True


class JobLogOut(BaseModel):
    id: int
    job_id: str
    level: str
    stage: str | None
    message: str
    metadata_json: dict
    created_at: datetime

    class Config:
        from_attributes = True
