from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


CONFIG_PATH = Path(os.getenv("APP_CONFIG_PATH", "/config/__main_config.json"))


class PathsConfig(BaseModel):
    video_data_root: str = "/video-data"
    watch_dir: str = "/video-data/watch"
    processing_dir: str = "/video-data/processing"
    work_dir: str = "/video-data/work"
    output_dir: str = "/video-data/output"
    archive_dir: str = "/video-data/archive"
    failed_dir: str = "/video-data/failed"


class QueueConfig(BaseModel):
    max_concurrent_jobs: int = 1


class WhisperConfig(BaseModel):
    model: str = "medium"
    device: str = "cpu"
    compute_type: str = "int8"
    source_language: str | None = "en"
    beam_size: int = 5
    vad_filter: bool = True
    normalize_audio: bool = True
    chunking_enabled: bool = True
    chunk_minutes: int = 20
    chunk_overlap_seconds: int = 2
    condition_on_previous_text: bool = False
    no_speech_threshold: float = 0.8
    temperature: float = 0.0


class TranslationConfig(BaseModel):
    provider: str = "google_unofficial"
    source_language: str = "auto"
    target_language: str = "ar"
    rate_limit_delay_ms: int = 500
    retry_count: int = 3
    fallback_to_original_on_error: bool = True


class SubtitleConfig(BaseModel):
    font_name: str = "Noto Sans Arabic"
    font_size: int = 12
    alignment: int = 2
    margin_v: int = 180
    margin_l: int = 80
    margin_r: int = 80
    outline: float = 3.5
    shadow: float = 1.5
    bold: bool = True
    primary_color: str = "&H00FFFFFF"
    outline_color: str = "&H00000000"
    back_color: str = "&H78000000"
    rtl_mode: str = "libass_native"
    rtl_preprocess_fallback: bool = False
    quality_enabled: bool = True
    max_chars_per_line: int = 38
    max_lines: int = 2
    max_cue_duration_seconds: float = 6.0
    min_cue_duration_seconds: float = 1.0
    min_gap_ms: int = 80
    split_long_cues: bool = True
    branding_enabled: bool = True
    branding_text: str = "Subtitles by Video Subtitle Studio"
    branding_duration_seconds: float = 20.0


class BurnConfig(BaseModel):
    encoder: str = "libx264"
    preset: str = "veryfast"
    crf: int = 20
    audio_mode: str = "copy"


class UiConfig(BaseModel):
    app_name: str = "Video Subtitle Studio"
    theme: str = "dark"


class AppConfig(BaseModel):
    paths: PathsConfig = Field(default_factory=PathsConfig)
    queue: QueueConfig = Field(default_factory=QueueConfig)
    whisper: WhisperConfig = Field(default_factory=WhisperConfig)
    translation: TranslationConfig = Field(default_factory=TranslationConfig)
    subtitles: SubtitleConfig = Field(default_factory=SubtitleConfig)
    burn: BurnConfig = Field(default_factory=BurnConfig)
    ui: UiConfig = Field(default_factory=UiConfig)


def load_config() -> AppConfig:
    if not CONFIG_PATH.exists():
        return AppConfig()
    return AppConfig.model_validate_json(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(payload: dict[str, Any]) -> AppConfig:
    cfg = AppConfig.model_validate(payload)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        backup = CONFIG_PATH.with_name(f"__main_config.backup.{int(CONFIG_PATH.stat().st_mtime)}.json")
        backup.write_text(CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg.model_dump(), indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)
    return cfg


def ensure_runtime_dirs(cfg: AppConfig) -> None:
    for path in cfg.paths.model_dump().values():
        Path(path).mkdir(parents=True, exist_ok=True)
