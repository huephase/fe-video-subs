# MAIN_PLAN.MD

# Standalone Dockerized Video Translation + Hard Subtitle App — Main Implementation Plan

## 1. Goal

Create a standalone Dockerized application that replaces the old n8n-based video-to-translated-hard-subtitles workflow with a fully managed web application.

The app should watch an external video folder, queue jobs, transcribe long videos, translate subtitles, generate styled ASS subtitles with strong RTL support, burn subtitles into videos, and expose a full web UI for configuration, job control, monitoring, errors, outputs, and system health.

The old files under the directory `old_n8n` show the previous n8n approach:

- `old_n8n/docker-compose.yml.bak` runs `postgres`, `n8n`, `whisper`, and `whisper_api` services.
- `old_n8n/Dockerfile.bak` extends the `n8nio/n8n:1` image and installs FFmpeg into the n8n container.
- `old_n8n/Video_to_Translated_Hard_Subs_v4_FIXED.json.bak` contains the n8n workflow that builds paths, extracts audio, calls the async Whisper API, waits for status files, verifies subtitles, and burns subtitles.
- `old_n8n/app.py.bak` contains a FastAPI helper that transcribes audio with `faster-whisper`, translates SRT cues, converts SRT to ASS, and exposes `/process`, `/process_async`, `/status`, and `/health` endpoints.

The new app should preserve the useful behavior from these old n8n files, but remove n8n as the main orchestration layer and replace it with a more reliable standalone app architecture.

---

## 2. Key Problems To Fix From The Current Version

### 2.1 `/video-data` should not live inside the Git-tracked app directory

Old Docker Compose mounted:

```yaml
./video-data:/video-data
```

This places large source videos, work files, generated audio, SRT, ASS, and final videos under the project directory. That is risky because video files are massive and should not be accidentally committed, synced, backed up, or deployed with the app.

The new app must mount an external host directory, for example:

```yaml
${VIDEO_DATA_HOST_PATH}:/video-data
```

Example `__main_config.json` value:

```json
"VIDEO_DATA_HOST_PATH":"/mnt/media/video-data"
```

Inside that mounted path, the app should manage:

```text
/video-data/
  watch/          # incoming videos
  processing/     # claimed files currently being prepared
  work/           # per-job scratch folders
  output/         # final hard-subbed videos
  archive/        # original videos after success, optional
  failed/         # failed source files, optional
  logs/           # external logs
  models/         # optional model cache if desired
```

The repo should include a `.gitignore` entry as a safety net:

```gitignore
video-data/
*.mp4
*.mov
*.mkv
*.avi
*.wav
*.srt
*.ass
*.vtt
*.tmp
*.part
```

However, the main protection must be Docker volume configuration, not only `.gitignore`.

---

### 2.2 Runtime settings should live in `__main_config.json`

General operational settings should be editable without rebuilding or redeploying Docker. The app should load runtime configuration from:

```text
/config/__main_config.json
```

or inside the repo for development:

```text
./config/__main_config.json
```

Secrets must not be stored in this file. Secrets belong in `.env` or Docker secrets.

The web UI should allow editing safe runtime settings and saving them back to `__main_config.json`. The backend should reload this file dynamically before starting each new job, and watch it for changes.

Recommended `__main_config.json`:

```json
{
  "paths": {
    "video_data_root": "/video-data",
    "watch_dir": "/video-data/watch",
    "processing_dir": "/video-data/processing",
    "work_dir": "/video-data/work",
    "output_dir": "/video-data/output",
    "archive_dir": "/video-data/archive",
    "failed_dir": "/video-data/failed"
  },
  "watcher": {
    "enabled": true,
    "scan_interval_seconds": 15,
    "stable_file_seconds": 60,
    "allowed_extensions": [".mp4", ".mov", ".mkv", ".avi", ".webm"],
    "ignore_patterns": ["*.part", "*.tmp", ".*"],
    "auto_start_jobs": true
  },
  "queue": {
    "max_concurrent_jobs": 1,
    "max_retries": 2,
    "retry_delay_seconds": 120,
    "job_timeout_minutes": 1440,
    "pause_queue_on_repeated_failures": true
  },
  "long_video": {
    "enabled": true,
    "chunking_enabled": true,
    "chunk_minutes": 20,
    "chunk_overlap_seconds": 2,
    "long_video_threshold_minutes": 160,
    "max_video_minutes_before_warning": 360,
    "resume_from_last_successful_stage": true,
    "keep_intermediate_files": true
  },
  "whisper": {
    "model": "medium",
    "device": "cpu",
    "compute_type": "int8",
    "source_language": "en",
    "beam_size": 5,
    "vad_filter": true,
    "word_timestamps": false
  },
  "translation": {
    "provider": "google_unofficial",
    "source_language": "auto",
    "target_language": "ar",
    "batch_size": 40,
    "max_chars_per_request": 3500,
    "rate_limit_delay_ms": 500,
    "retry_count": 3,
    "fallback_to_original_on_error": true
  },
  "subtitles": {
    "format": "ass",
    "font_name": "Noto Sans Arabic",
    "font_size": 12,
    "alignment": 2,
    "margin_v": 180,
    "margin_l": 80,
    "margin_r": 80,
    "outline": 3.5,
    "shadow": 1.5,
    "bold": true,
    "primary_color": "&H00FFFFFF",
    "outline_color": "&H00000000",
    "back_color": "&H78000000",
    "rtl_mode": "libass_native",
    "rtl_preprocess_fallback": false,
    "rtl_test_before_burn": true
  },
  "burn": {
    "encoder": "libx264",
    "preset": "veryfast",
    "crf": 20,
    "audio_mode": "copy",
    "escape_subtitle_path": true,
    "generate_preview_clip": true,
    "preview_duration_seconds": 45
  },
  "cleanup": {
    "archive_source_after_success": false,
    "delete_work_files_after_days": 14,
    "delete_failed_work_files_after_days": 30
  },
  "ui": {
    "app_name": "Video Subtitle Studio",
    "theme": "dark",
    "show_advanced_settings": true
  }
}
```

### 2.3 Secrets must remain in `.env`

`.env` should hold only secrets and deployment-level values:

```env
APP_PORT=8080
POSTGRES_DB=video_subs
POSTGRES_USER=video_subs
POSTGRES_PASSWORD=change_me
REDIS_PASSWORD=change_me
APP_SECRET_KEY=change_me
VIDEO_DATA_HOST_PATH=/mnt/media/video-data
CONFIG_HOST_PATH=./config
TZ=Asia/Dubai
HF_TOKEN=
TRANSLATION_API_KEY=
```

Do not store API keys, database passwords, tokens, or auth credentials in `__main_config.json`.

---

## 3. Recommended Standalone Architecture

### 3.1 Services

Replace the old n8n-first architecture with this service layout:

```text
video-subtitle-app/
  backend/              # FastAPI API + job orchestration
  frontend/             # React/Vite web UI
  worker/               # Celery/RQ/Arq worker, or same backend image with worker command
  config/
    __main_config.json
  docker-compose.yml
  .env.example
  .gitignore
  README.md
  MAIN_PLAN.MD
```

Docker services:

```text
app-api       FastAPI backend, REST API, WebSocket/SSE status stream
app-worker    Background worker that performs FFmpeg, Whisper, translation, ASS generation, burn-in
app-ui        React/Vite frontend served by Nginx or backend static hosting
postgres      Persistent job database
redis         Queue broker, locks, live progress, cancellation flags
```

Optional future service:

```text
whisper-gpu   Dedicated GPU-enabled transcription service
```

### 3.2 Use Redis and Postgres

Use Postgres for durable state:

- jobs
- job stages
- file paths
- job attempts
- errors
- logs
- app settings history
- queue history

Use Redis for fast queue coordination:

- pending job queue
- active job locks
- cancel/pause/resume flags
- live progress updates
- worker heartbeat

This avoids fragile status polling through only `status.json` files.

---

## 4. Main App Responsibilities

The standalone app should own the full pipeline:

```text
Watch folder
  -> detect stable video file
  -> create job record
  -> move or claim file
  -> extract audio
  -> transcribe
  -> translate
  -> create styled ASS subtitles
  -> run RTL validation / preview
  -> burn subtitles into final video
  -> verify output
  -> archive or leave source
  -> display result in UI
```

The n8n workflow currently performs these as separate nodes. In the new app, these become explicit backend stages with recoverable progress.

Recommended stage names:

```text
queued
claiming_file
probing_video
extracting_audio
chunking_audio
transcribing
merging_transcripts
translating
creating_srt
creating_ass
rtl_validation
creating_preview
burning_subtitles
verifying_output
completed
failed
cancelled
```

Each stage should write progress to Postgres and publish live updates through WebSocket or Server-Sent Events.

---

## 5. Watch Folder Logic

### 5.1 Stable file detection

The watcher must not start a job while a file is still copying.

A file is stable when:

- size has not changed for `stable_file_seconds`
- modified time is older than `stable_file_seconds`
- extension is allowed
- filename does not match ignore patterns such as `.part`, `.tmp`, hidden files

Pseudo-logic:

```python
for file in watch_dir:
    if not extension_allowed(file):
        continue
    if file_is_hidden_or_temp(file):
        continue
    if not file_size_stable(file, stable_file_seconds):
        continue
    if already_registered(file):
        continue
    create_job(file)
```

### 5.2 File claiming

When a worker starts a job, it should either:

1. move the file from `/video-data/watch` to `/video-data/processing`, or
2. create a lock file next to it.

Recommended approach:

```text
/video-data/watch/input.mp4
```

moves to:

```text
/video-data/processing/{job_id}/input.mp4
```

This prevents duplicate jobs and allows clean recovery.

### 5.3 Manual job creation

The web UI should also allow manually selecting a video from the watch folder or uploading/registering a path.

---

## 6. Long Video Handling

The app must handle videos longer than 160 minutes and multiple long videos safely.

### 6.1 Problem

The current FastAPI helper starts work in a Python thread and writes a simple status JSON file. This is not enough for very long jobs because:

- threads can die if the API container restarts
- progress is coarse
- cancellation is difficult
- retries are not stage-aware
- multiple long videos may exhaust CPU/RAM/disk
- one failed translation cue can affect a long run
- one huge audio file can be inefficient

### 6.2 Required long-video strategy

For videos above `long_video_threshold_minutes`, default 160 minutes:

1. Probe video duration with `ffprobe`.
2. Extract audio as 16 kHz mono WAV or compressed intermediate format.
3. Split audio into chunks, for example 20-minute chunks with 2-second overlap.
4. Transcribe each chunk independently.
5. Offset timestamps by chunk start time.
6. Merge SRT cues in correct order.
7. De-duplicate overlap cues.
8. Translate in batches.
9. Generate final SRT and ASS.
10. Burn subtitles once against the original full video.

### 6.3 Chunking folder structure

```text
/video-data/work/{job_id}/
  input.json
  probe.json
  audio/
    full.wav
    chunks/
      chunk_000.wav
      chunk_001.wav
      chunk_002.wav
  transcript/
    chunk_000.en.srt
    chunk_001.en.srt
    merged.en.srt
  translation/
    merged.ar.srt
    translation_cache.json
  subtitles/
    final.ass
  preview/
    preview.mp4
  output/
    final.mp4
  logs/
    ffmpeg_extract.log
    whisper.log
    translate.log
    burn.log
```

### 6.4 Resume support

Each stage should be idempotent. If a job stops halfway, it should resume from the last successful stage instead of starting again.

Examples:

- If `chunk_000.en.srt` exists and passed validation, do not retranscribe it.
- If `merged.en.srt` exists and cue count is valid, skip merging.
- If `merged.ar.srt` exists and cue count matches source, skip translation.
- If `final.ass` exists and can be parsed by libass/pysubs2, skip ASS creation.

### 6.5 Concurrency rules

The default should be conservative:

```json
"max_concurrent_jobs": 1
```

For CPU-only systems, this is safer. Long videos can use all available CPU for hours. The UI should allow changing concurrency, but should warn users when increasing above 1.

### 6.6 Multiple long videos

When multiple long videos appear in the watch folder:

- queue them in order of creation time or file detected time
- show estimated duration and disk usage
- show which job is active and which jobs are queued
- allow pause/resume/cancel/retry
- prevent two workers from processing the same file
- enforce minimum free disk space before starting a job

Recommended safety checks:

```text
minimum_free_disk_gb: 20
minimum_free_disk_percent: 10
```

---

## 7. Subtitle RTL Support

### 7.1 Required RTL languages

The app should fully support right-to-left subtitles for:

- Arabic
- Persian/Farsi
- Urdu
- Hebrew
- Kurdish Sorani
- other RTL scripts where possible

### 7.2 ASS/libass rendering

Use ASS subtitles for burn-in because ASS gives stronger control over styling, alignment, margins, outlines, shadows, and font rendering.

Current code already uses `pysubs2` and ASS generation. The new app should preserve this approach but improve it.

### 7.3 Fonts

Install and include reliable fonts in the Docker image:

```text
fonts-noto-core
fonts-noto-extra
fonts-noto-ui-core
fonts-noto-color-emoji
fonts-noto-unhinted
fonts-dejavu-core
fontconfig
```

For Arabic/Persian, recommended default:

```text
Noto Sans Arabic
```

Also support:

```text
Noto Naskh Arabic
Noto Sans Hebrew
Noto Sans Arabic UI
```

Run font cache during image build:

```dockerfile
RUN fc-cache -f -v
```

### 7.4 FFmpeg subtitle burn command

Use libass through FFmpeg:

```bash
ffmpeg -y \
  -i "$INPUT_VIDEO" \
  -vf "subtitles='$ASS_PATH':fontsdir=/usr/share/fonts/truetype/noto" \
  -c:v libx264 \
  -preset veryfast \
  -crf 20 \
  -c:a copy \
  "$OUTPUT_VIDEO"
```

For ASS files, this may also be:

```bash
ffmpeg -y \
  -i "$INPUT_VIDEO" \
  -vf "ass='$ASS_PATH'" \
  -c:v libx264 \
  -preset veryfast \
  -crf 20 \
  -c:a copy \
  "$OUTPUT_VIDEO"
```

The app must safely escape subtitle paths because FFmpeg filter paths break easily with spaces, colons, apostrophes, and special characters.

### 7.5 RTL modes

Support three RTL modes in config/UI:

```text
libass_native
preprocess_bidi
auto
```

Recommended default:

```text
libass_native
```

Reason: FFmpeg/libass builds often support FriBidi and HarfBuzz, and manual reshaping can make output worse when native shaping already works.

Fallback mode:

```text
preprocess_bidi
```

Use only if Arabic/Persian appears reversed, disconnected, or incorrectly ordered.

Auto mode:

- generate a short preview clip
- optionally compare/render a test frame
- allow the user to choose the correct mode in UI

### 7.6 RTL validation preview

Before burning a full 160+ minute video, generate a short preview:

```text
/video-data/work/{job_id}/preview/rtl_preview.mp4
```

The UI should show this preview and allow:

- approve and continue
- change font
- change RTL mode
- change size/margins
- regenerate preview
- continue anyway

This prevents wasting hours burning a full video with broken RTL.

---

## 8. Web UI Requirements

The app should include a fully fledged web UI.

### 8.1 Main dashboard

Dashboard panels:

- System status
- Worker status
- Queue status
- Active job progress
- Watch folder status
- Disk space usage
- Recent completed jobs
- Recent failed jobs
- Warnings and errors

### 8.2 Queue page

Features:

- list queued jobs
- list running jobs
- list completed jobs
- list failed jobs
- pause queue
- resume queue
- cancel job
- retry job
- delete job record
- open job details
- priority control
- sort by date, duration, status, filename

### 8.3 Job details page

Show:

- filename
- source path
- output path
- duration
- file size
- current stage
- progress percentage
- started time
- elapsed time
- estimated remaining time if available
- logs per stage
- generated English SRT
- generated translated SRT
- generated ASS
- preview video
- final output video
- error traceback if failed

Actions:

- start
- pause if supported
- cancel
- retry from failed stage
- retry full job
- regenerate subtitles only
- reburn video only
- download SRT
- download ASS
- download final video
- open output folder path

### 8.4 Settings page

Editable settings from `__main_config.json`:

- video data root
- watch folder
- work folder
- output folder
- archive folder
- queue concurrency
- long-video threshold
- chunk length
- target language
- translation provider
- subtitle font
- font size
- margin settings
- RTL mode
- burn preset/CRF
- cleanup policy

The UI should validate paths before saving.

### 8.5 Watch folder page

Show:

- files waiting in watch folder
- files currently copying/not stable
- ignored files
- unsupported extensions
- button to scan now
- button to enqueue selected files

### 8.6 Errors panel

Show:

- error summary
- failed stage
- exact command that failed, with secrets redacted
- FFmpeg stderr
- translation provider errors
- missing font errors
- missing path/permission errors
- insufficient disk warnings

### 8.7 Logs panel

Support live logs via WebSocket/SSE.

Show logs grouped by:

- watcher
- queue
- worker
- ffmpeg
- whisper
- translation
- subtitle generation
- burn

---

## 9. Backend API Design

Recommended endpoints:

```text
GET    /api/health
GET    /api/config
PUT    /api/config
POST   /api/config/reload
GET    /api/system/disk
GET    /api/system/fonts
GET    /api/watch/files
POST   /api/watch/scan
POST   /api/jobs
GET    /api/jobs
GET    /api/jobs/{job_id}
POST   /api/jobs/{job_id}/start
POST   /api/jobs/{job_id}/cancel
POST   /api/jobs/{job_id}/retry
POST   /api/jobs/{job_id}/retry-from-stage
POST   /api/jobs/{job_id}/preview
POST   /api/jobs/{job_id}/reburn
GET    /api/jobs/{job_id}/logs
GET    /api/jobs/{job_id}/download/srt-source
GET    /api/jobs/{job_id}/download/srt-translated
GET    /api/jobs/{job_id}/download/ass
GET    /api/jobs/{job_id}/download/video
GET    /api/queue
POST   /api/queue/pause
POST   /api/queue/resume
GET    /api/events/stream
```

Use WebSocket or Server-Sent Events for live progress:

```text
GET /api/events/stream
```

---

## 10. Database Plan

Use Postgres tables.

### 10.1 jobs

```sql
CREATE TABLE jobs (
  id UUID PRIMARY KEY,
  source_path TEXT NOT NULL,
  processing_path TEXT,
  output_path TEXT,
  work_dir TEXT NOT NULL,
  original_filename TEXT NOT NULL,
  status TEXT NOT NULL,
  stage TEXT NOT NULL,
  progress NUMERIC DEFAULT 0,
  duration_seconds NUMERIC,
  file_size_bytes BIGINT,
  target_language TEXT NOT NULL,
  source_language TEXT,
  config_snapshot JSONB NOT NULL,
  error_summary TEXT,
  error_detail TEXT,
  retry_count INTEGER DEFAULT 0,
  priority INTEGER DEFAULT 100,
  created_at TIMESTAMPTZ DEFAULT now(),
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ DEFAULT now()
);
```

### 10.2 job_stages

```sql
CREATE TABLE job_stages (
  id UUID PRIMARY KEY,
  job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
  stage TEXT NOT NULL,
  status TEXT NOT NULL,
  progress NUMERIC DEFAULT 0,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  error TEXT,
  metadata JSONB DEFAULT '{}'
);
```

### 10.3 job_logs

```sql
CREATE TABLE job_logs (
  id BIGSERIAL PRIMARY KEY,
  job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
  level TEXT NOT NULL,
  stage TEXT,
  message TEXT NOT NULL,
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now()
);
```

### 10.4 app_settings_history

```sql
CREATE TABLE app_settings_history (
  id BIGSERIAL PRIMARY KEY,
  config JSONB NOT NULL,
  changed_by TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

---

## 11. Worker Pipeline Details

### 11.1 Probe video

Use `ffprobe`:

```bash
ffprobe -v error \
  -print_format json \
  -show_format \
  -show_streams \
  "$INPUT_VIDEO"
```

Save output:

```text
/video-data/work/{job_id}/probe.json
```

Extract:

- duration
- video codec
- audio codec
- resolution
- frame rate
- file size
- audio streams

### 11.2 Extract audio

Use:

```bash
ffmpeg -y \
  -i "$INPUT_VIDEO" \
  -vn \
  -ac 1 \
  -ar 16000 \
  -c:a pcm_s16le \
  "$AUDIO_PATH"
```

For very long videos, allow compressed intermediate option to save disk:

```bash
-c:a flac
```

or:

```bash
-c:a libopus -b:a 32k
```

Use WAV by default for compatibility.

### 11.3 Transcription

Use Faster Whisper inside the worker or a dedicated local service.

Recommended Python function should support:

- language
- model
- beam size
- VAD
- chunk-level progress
- resume per chunk
- device and compute type

Current code loads `WhisperModel` from env values. The new app should load these from `__main_config.json` for runtime behavior and from `.env` only for infrastructure defaults.

### 11.4 Translation

Current code uses `deep_translator.GoogleTranslator`. Keep it as an initial option, but abstract translation behind a provider interface:

```python
class TranslatorProvider:
    def translate_batch(self, texts: list[str], target_language: str) -> list[str]:
        ...
```

Providers:

```text
google_unofficial
openai_optional
deepseek_optional
local_optional
manual_upload
```

Must support:

- batching
- retries
- rate limiting
- translation cache
- cue count preservation
- fallback to original text if configured

### 11.5 ASS generation

Keep `pysubs2`, but improve output:

- save all style settings
- support per-language font defaults
- support RTL mode
- preserve punctuation
- avoid destroying line breaks unnecessarily
- include metadata comments in ASS file

### 11.6 Burn subtitles

Burn against the original video, not chunked video.

Use logs:

```text
/video-data/work/{job_id}/logs/burn.log
```

Save final output to:

```text
/video-data/output/{safe_basename}_{target_language}_hardsub.mp4
```

If output exists, append a timestamp or job ID.

---

## 12. Docker Compose Plan

Recommended new `docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: ["redis-server", "--appendonly", "yes", "--requirepass", "${REDIS_PASSWORD}"]
    volumes:
      - redis_data:/data

  api:
    build:
      context: .
      dockerfile: backend/Dockerfile
    restart: unless-stopped
    env_file: .env
    ports:
      - "${APP_PORT:-8080}:8080"
    volumes:
      - ${VIDEO_DATA_HOST_PATH}:/video-data
      - ${CONFIG_HOST_PATH:-./config}:/config
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started

  worker:
    build:
      context: .
      dockerfile: backend/Dockerfile
    restart: unless-stopped
    env_file: .env
    command: ["python", "-m", "app.worker"]
    volumes:
      - ${VIDEO_DATA_HOST_PATH}:/video-data
      - ${CONFIG_HOST_PATH:-./config}:/config
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started

  ui:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    restart: unless-stopped
    ports:
      - "${UI_PORT:-3000}:80"
    depends_on:
      - api

volumes:
  postgres_data:
  redis_data:
```

Important: use named Docker volumes for database data, but external host bind mounts for massive video files.

---

## 13. Backend Dockerfile Plan

Use Debian/Ubuntu-based Python image instead of Alpine for better FFmpeg/libass/font compatibility.

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fontconfig \
    fonts-noto-core \
    fonts-noto-extra \
    fonts-noto-ui-core \
    fonts-noto-color-emoji \
    fonts-dejavu-core \
    libfribidi0 \
    libharfbuzz0b \
    ca-certificates \
    curl \
    && fc-cache -f -v \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend /app

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

Recommended `requirements.txt`:

```text
fastapi
uvicorn[standard]
pydantic
pydantic-settings
sqlalchemy
alembic
asyncpg
redis
rq
python-multipart
watchfiles
faster-whisper
pysubs2
deep-translator
arabic-reshaper
python-bidi
```

If using Celery instead of RQ:

```text
celery
```

---

## 14. Frontend Plan

Use:

```text
React + Vite + TypeScript
```

Suggested pages:

```text
/src/pages/Dashboard.tsx
/src/pages/Queue.tsx
/src/pages/JobDetails.tsx
/src/pages/WatchFolder.tsx
/src/pages/Settings.tsx
/src/pages/Logs.tsx
/src/pages/SystemHealth.tsx
```

Suggested components:

```text
JobStatusBadge.tsx
ProgressBar.tsx
StageTimeline.tsx
LogViewer.tsx
ErrorPanel.tsx
SettingsForm.tsx
FolderPicker.tsx
DiskUsageCard.tsx
PreviewPlayer.tsx
QueueControls.tsx
```

UI should be clean and practical:

- dark mode by default
- large status cards
- queue table
- clear error panels
- live progress
- one-click retry
- one-click preview generation
- clear paths shown for watch/work/output folders

---

## 15. Configuration Editing Rules

When the UI saves `__main_config.json`:

1. Validate JSON schema.
2. Validate directories exist or can be created.
3. Test write permissions.
4. Save backup first:

```text
/config/__main_config.backup.YYYYMMDD_HHMMSS.json
```

5. Write new config atomically:

```text
__main_config.json.tmp -> __main_config.json
```

6. Reload backend config.
7. Record change in `app_settings_history`.

Do not allow UI to edit `.env` secrets.

---

## 16. Security and Safety

### 16.1 Path safety

The API must prevent path traversal.

Only allow paths inside configured roots:

```text
/video-data
/config
```

Reject:

```text
../../etc/passwd
/root/.ssh
/var/run/docker.sock
```

### 16.2 Command execution safety

Do not build FFmpeg commands with unsafe shell strings.

Use Python `subprocess.run([...])` list arguments, not `shell=True`.

Bad:

```python
subprocess.run(f"ffmpeg -i {input_path} ...", shell=True)
```

Good:

```python
subprocess.run([
  "ffmpeg", "-y",
  "-i", str(input_path),
  "-vf", filter_arg,
  "-c:v", "libx264",
  "-preset", preset,
  "-crf", str(crf),
  "-c:a", "copy",
  str(output_path),
])
```

### 16.3 Authentication

At minimum, protect the UI with app login or reverse-proxy auth.

Possible options:

- simple local admin password from `.env`
- OAuth later
- private LAN only at first

### 16.4 Log redaction

Redact secrets from logs:

- database URLs
- API keys
- tokens
- passwords

---

## 17. Migration From Current n8n Workflow

### Phase 1 — Extract core pipeline from n8n

Move these steps from n8n into backend/worker code:

- build paths
- create job folder
- extract audio
- call transcription/translation
- verify subtitle files
- burn subtitles
- confirm output

### Phase 2 — Replace status files with database state

Keep writing `status.json` optionally for human-readable debugging, but use Postgres as source of truth.

### Phase 3 — Add watch folder

Implement watcher service that scans `/video-data/watch` and enqueues stable files.

### Phase 4 — Add web UI

Start with dashboard, queue, settings, and job details.

### Phase 5 — Add long-video chunking

Implement chunk/resume logic before processing production-length videos.

### Phase 6 — Add RTL preview and validation

Generate preview clips before burning full long videos.

### Phase 7 — Remove n8n containers

Once standalone app is stable, remove:

```text
n8n
whisper_api as separate helper if folded into worker
old n8n Dockerfile
```

---

## 18. Suggested First Milestone

Build a minimal but complete standalone version:

1. Docker Compose with `api`, `worker`, `postgres`, `redis`, `ui`.
2. External mount using `${VIDEO_DATA_HOST_PATH}:/video-data`.
3. `__main_config.json` loaded from `/config`.
4. Manual job creation from UI.
5. Queue one job at a time.
6. Extract audio.
7. Transcribe.
8. Translate.
9. Generate ASS.
10. Burn subtitles.
11. Show live progress and errors.
12. Save final video to `/video-data/output`.

After this works, add watch folder automation and long-video chunking.

---

## 19. Suggested Second Milestone

Add production-level reliability:

1. Watch folder scan.
2. Stable file detection.
3. Long-video chunking above 160 minutes.
4. Resume per stage.
5. Retry failed translation batches.
6. RTL preview clip.
7. Disk-space checks.
8. Cleanup policy.
9. Job logs and downloadable artifacts.
10. Config editing through UI.

---

## 20. Acceptance Criteria

The app is ready when:

- `/video-data` is mounted from outside the Git repo.
- The app can run from Docker Compose with one command.
- General settings can be changed in `__main_config.json` or web UI without rebuilding Docker.
- Secrets are only in `.env`.
- Watch folder detects stable videos and queues them.
- UI shows queued/running/done/failed jobs.
- UI can start, stop/cancel, retry, and inspect jobs.
- A 160+ minute video can be processed through chunking and resume-safe stages.
- Multiple long videos queue safely without overloading the machine.
- RTL subtitles render correctly for Arabic/Persian using ASS/libass.
- Preview clips can be generated before full burn-in.
- Errors are visible and actionable in the UI.
- Final hard-subbed videos are written to `/video-data/output`.

---

## 21. Recommended Development Order

```text
1. Create repo structure
2. Create backend FastAPI app
3. Add config loader for /config/__main_config.json
4. Add Postgres models and migrations
5. Add Redis queue
6. Add worker skeleton
7. Add FFmpeg probe/extract helpers
8. Port transcription logic from current app(1).py
9. Port translation logic into provider interface
10. Port SRT-to-ASS logic and improve RTL support
11. Add burn-in helper with safe subprocess calls
12. Add job API endpoints
13. Add React dashboard and queue UI
14. Add settings UI
15. Add watch folder scanner
16. Add long-video chunking and resume
17. Add RTL preview workflow
18. Add cleanup and archival policies
19. Test with short video
20. Test with 160+ minute video
21. Test with multiple queued long videos
22. Remove n8n dependency
```

---

## 22. Important Implementation Notes

### 22.1 Keep source videos untouched where possible

Do not modify source videos in place. Copy or move them to a processing folder and write final outputs separately.

### 22.2 Use safe filenames

Create job-safe names:

```text
{original_basename}_{target_language}_{job_id_short}_hardsub.mp4
```

### 22.3 Keep config snapshots

Every job should store the exact config snapshot used when it started. This makes output reproducible even if settings change later.

### 22.4 Do not rely only on percent progress

Show both:

- stage name
- progress percent

For long jobs, stage detail matters more than percentage.

### 22.5 Translation quality

For production-quality subtitles, the app should eventually support a stronger translation provider than unofficial Google translation. The provider should preserve cue counts and timestamp structure.

### 22.6 Subtitle quality tools

Add tools for:

- max characters per line
- max lines per subtitle
- minimum cue duration
- merging very short cues
- splitting very long cues
- punctuation cleanup
- Arabic/Persian punctuation normalization

---

## 23. Final Target Experience

The final app should feel like a small local video subtitle studio:

1. User drops videos into `/video-data/watch`.
2. App detects them automatically.
3. Jobs appear in the web UI queue.
4. Worker processes one or more jobs depending on configured concurrency.
5. User can inspect progress, logs, errors, previews, and outputs.
6. Long videos are chunked and resumed safely.
7. RTL subtitles render correctly before committing to a full burn.
8. Final videos appear in `/video-data/output`.
9. App settings are editable through `__main_config.json` and the UI.
10. The repo remains clean and Git-trackable because massive video files live outside the app directory.
