from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


def run_command(args: list[str], log_path: Path) -> subprocess.CompletedProcess[str]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(args, text=True, capture_output=True, check=False)
    log_path.write_text(
        "$ " + " ".join(args) + "\n\nSTDOUT:\n" + proc.stdout + "\n\nSTDERR:\n" + proc.stderr,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {proc.returncode}: {' '.join(args)}")
    return proc


def probe_video(input_path: Path, output_path: Path, log_path: Path) -> dict:
    proc = run_command(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(input_path)],
        log_path,
    )
    data = json.loads(proc.stdout or "{}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def extract_duration_seconds(probe: dict) -> float | None:
    duration = probe.get("format", {}).get("duration")
    return float(duration) if duration else None


def extract_audio(input_path: Path, audio_path: Path, log_path: Path) -> None:
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(audio_path),
        ],
        log_path,
    )


def burn_subtitles(input_video: Path, ass_path: Path, output_path: Path, cfg: dict, log_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio_args = ["-c:a", "copy"] if cfg["burn"]["audio_mode"] == "copy" else ["-c:a", cfg["burn"]["audio_mode"]]
    run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_video),
            "-vf",
            f"ass={str(ass_path)}",
            "-c:v",
            cfg["burn"]["encoder"],
            "-preset",
            cfg["burn"]["preset"],
            "-crf",
            str(cfg["burn"]["crf"]),
            *audio_args,
            str(output_path),
        ],
        log_path,
    )


def claim_source(source_path: Path, processing_dir: Path, job_id: str) -> Path:
    job_processing_dir = processing_dir / job_id
    job_processing_dir.mkdir(parents=True, exist_ok=True)
    claimed = job_processing_dir / source_path.name
    if claimed.exists():
        return claimed
    shutil.move(str(source_path), str(claimed))
    return claimed

