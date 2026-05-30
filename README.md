# Video Subtitle Studio

Standalone Dockerized app for manual video-to-translated-hard-subtitle jobs.

This repository now contains the first milestone from `docs/MAIN_PLAN.MD`:

- Docker Compose services for `api`, `worker`, `postgres`, `redis`, and `ui`
- External video mount via `${VIDEO_DATA_HOST_PATH}:/video-data`
- Runtime settings loaded from `/config/__main_config.json`
- Manual job creation from the UI using files in `/video-data/watch`
- Optional per-job custom subtitle upload (`.srt`, `.ass`, `.vtt`) to skip audio extraction and speech-to-text
- Configurable ASS branding note, shown by default for the first 20 seconds
- One-at-a-time Redis/RQ worker processing
- FFmpeg audio extraction
- Faster Whisper transcription
- Google unofficial translation through `deep-translator`
- styled ASS subtitle generation with RTL options
- FFmpeg/libass burn-in
- live progress, logs, and errors in the UI
- final output saved to `/video-data/output`

## Quick Start

1. Copy the environment template:

   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and set `VIDEO_DATA_HOST_PATH` to a host folder outside this repo.

3. Create the expected video folders. Either source `.env` first or replace the path with your real host folder:

   ```bash
   set -a && . ./.env && set +a
   mkdir -p "$VIDEO_DATA_HOST_PATH"/{watch,processing,work,output,archive,failed}
   ```

4. Start the stack:

   ```bash
   docker compose up --build
   ```

5. Open the UI:

   ```text
   http://localhost:3000
   ```

Drop a short test video into `/video-data/watch`, then enqueue it from the Watch Folder panel. To use existing subtitles instead of speech-to-text, click the subtitle-file button beside the video before enqueueing and select a `.srt`, `.ass`, or `.vtt` file.

## Notes

- Secrets stay in `.env`; safe runtime settings live in `config/__main_config.json`.
- The first milestone intentionally uses manual enqueue. Watch-folder automation, long-video chunking, retries, cancellation, and preview approval are next-milestone work.
- Faster Whisper model downloads can take time on first run.
