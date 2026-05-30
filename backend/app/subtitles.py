from __future__ import annotations

import copy
import re
import tempfile
import time
import wave
from pathlib import Path

import pysubs2
from deep_translator import GoogleTranslator
from faster_whisper import WhisperModel


_model_cache: dict[tuple[str, str, str], WhisperModel] = {}
SUPPORTED_SUBTITLE_SUFFIXES = {".srt", ".ass", ".vtt"}


def validate_subtitle_path(path: Path) -> Path:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUBTITLE_SUFFIXES:
        allowed = ", ".join(sorted(SUPPORTED_SUBTITLE_SUFFIXES))
        raise ValueError(f"Custom subtitle file must use one of these formats: {allowed}")
    if not path.exists() or not path.is_file():
        raise ValueError("Custom subtitle file must point to an existing file")
    return path


def srt_time(seconds: float) -> str:
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000:
        seconds += 1
        ms = 0
    s = int(seconds) % 60
    m = (int(seconds) // 60) % 60
    h = int(seconds) // 3600
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def whisper_model(cfg: dict) -> WhisperModel:
    whisper = cfg["whisper"]
    key = (whisper["model"], whisper["device"], whisper["compute_type"])
    if key not in _model_cache:
        _model_cache[key] = WhisperModel(key[0], device=key[1], compute_type=key[2])
    return _model_cache[key]


def whisper_language(value: str | None) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    if not value or value.lower() in {"auto", "none", "null"}:
        return None
    return value


def transcribe_options(cfg: dict) -> dict:
    whisper = cfg["whisper"]
    return {
        "beam_size": int(whisper["beam_size"]),
        "vad_filter": bool(whisper.get("vad_filter", True)),
        "language": whisper_language(whisper.get("source_language")),
        "task": "transcribe",
        "condition_on_previous_text": bool(whisper.get("condition_on_previous_text", False)),
        "no_speech_threshold": float(whisper.get("no_speech_threshold", 0.8)),
        "temperature": float(whisper.get("temperature", 0.0)),
    }


def write_wav_chunk(reader: wave.Wave_read, chunk_path: Path, start_frame: int, frame_count: int) -> None:
    reader.setpos(start_frame)
    frames = reader.readframes(frame_count)
    with wave.open(str(chunk_path), "wb") as writer:
        writer.setnchannels(reader.getnchannels())
        writer.setsampwidth(reader.getsampwidth())
        writer.setframerate(reader.getframerate())
        writer.writeframes(frames)


def transcribe_audio_segments(audio_path: Path, cfg: dict):
    whisper = cfg["whisper"]
    if not bool(whisper.get("chunking_enabled", True)):
        segments, _ = whisper_model(cfg).transcribe(str(audio_path), **transcribe_options(cfg))
        for seg in segments:
            yield seg.start, seg.end, seg.text
        return

    chunk_seconds = max(60, int(whisper.get("chunk_minutes", 20)) * 60)
    overlap_seconds = max(0, int(whisper.get("chunk_overlap_seconds", 2)))
    if overlap_seconds >= chunk_seconds:
        overlap_seconds = max(0, chunk_seconds - 1)

    with wave.open(str(audio_path), "rb") as reader:
        frame_rate = reader.getframerate()
        total_frames = reader.getnframes()
        chunk_frames = chunk_seconds * frame_rate
        overlap_frames = overlap_seconds * frame_rate
        step_frames = max(1, chunk_frames - overlap_frames)

        with tempfile.TemporaryDirectory(prefix="subtitle-chunks-") as tmp:
            tmp_dir = Path(tmp)
            chunk_index = 0
            start_frame = 0
            while start_frame < total_frames:
                frame_count = min(chunk_frames, total_frames - start_frame)
                chunk_path = tmp_dir / f"chunk_{chunk_index:04}.wav"
                write_wav_chunk(reader, chunk_path, start_frame, frame_count)

                offset_seconds = start_frame / frame_rate
                keep_from = 0.0 if chunk_index == 0 else overlap_seconds
                segments, _ = whisper_model(cfg).transcribe(str(chunk_path), **transcribe_options(cfg))
                for seg in segments:
                    if seg.end <= keep_from:
                        continue
                    yield offset_seconds + max(seg.start, keep_from), offset_seconds + seg.end, seg.text

                chunk_index += 1
                start_frame += step_frames


def transcribe_to_srt(audio_path: Path, srt_path: Path, cfg: dict) -> None:
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    with srt_path.open("w", encoding="utf-8") as srt:
        index = 1
        previous_end = 0.0
        for start, end, text in transcribe_audio_segments(audio_path, cfg):
            text = text.strip()
            if text:
                start = max(start, previous_end)
                end = max(end, start + 0.25)
                srt.write(f"{index}\n{srt_time(start)} --> {srt_time(end)}\n{text}\n\n")
                previous_end = end
                index += 1


def normalize_custom_subtitle_to_srt(input_path: Path, output_srt: Path) -> None:
    validate_subtitle_path(input_path)
    output_srt.parent.mkdir(parents=True, exist_ok=True)
    try:
        subs = pysubs2.load(str(input_path), encoding="utf-8")
    except Exception as exc:
        raise ValueError(f"Custom subtitle file could not be parsed: {exc}") from exc
    if not list(subs):
        raise ValueError("Custom subtitle file does not contain any subtitle cues")
    subs.sort()
    subs.save(str(output_srt), encoding="utf-8", format_="srt")


def translate_srt(input_srt: Path, output_srt: Path, cfg: dict) -> None:
    output_srt.parent.mkdir(parents=True, exist_ok=True)
    content = input_srt.read_text(encoding="utf-8").strip()
    if not content:
        output_srt.write_text("", encoding="utf-8")
        return

    translation = cfg["translation"]
    translator = GoogleTranslator(source=translation["source_language"], target=translation["target_language"])
    blocks = re.split(r"\n\s*\n", content)
    translated: list[str] = []

    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3:
            translated.append(block)
            continue
        index, timestamp = lines[0], lines[1]
        text = "\n".join(lines[2:]).strip()
        translated_text = text
        for attempt in range(int(translation["retry_count"]) + 1):
            try:
                translated_text = translator.translate(text) if text else ""
                break
            except Exception:
                if attempt >= int(translation["retry_count"]) and not translation["fallback_to_original_on_error"]:
                    raise
                time.sleep(max(translation["rate_limit_delay_ms"], 0) / 1000)
        translated.append(f"{index}\n{timestamp}\n{translated_text}")
        time.sleep(max(translation["rate_limit_delay_ms"], 0) / 1000)

    output_srt.write_text("\n\n".join(translated) + "\n", encoding="utf-8")


def normalize_subtitle_text(text: str) -> str:
    text = re.sub(r"[ \t\r\n]+", " ", text).strip()
    text = re.sub(r"\s+([،؛؟,.!?;:])", r"\1", text)
    text = re.sub(r"([،؛؟,.!?;:])(?=\S)", r"\1 ", text)
    return text.strip()


def split_long_token(token: str, max_chars: int) -> list[str]:
    if len(token) <= max_chars:
        return [token]
    return [token[index : index + max_chars] for index in range(0, len(token), max_chars)]


def wrapped_lines(text: str, max_chars_per_line: int) -> list[str]:
    words: list[str] = []
    for word in text.split():
        words.extend(split_long_token(word, max_chars_per_line))

    lines: list[str] = []
    current: list[str] = []
    current_len = 0

    for word in words:
        next_len = len(word) if not current else current_len + 1 + len(word)
        if current and next_len > max_chars_per_line:
            lines.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len = next_len

    if current:
        lines.append(" ".join(current))
    return lines


def split_text_for_cues(text: str, max_chars_per_line: int, max_lines: int) -> list[str]:
    words: list[str] = []
    for word in text.split():
        words.extend(split_long_token(word, max_chars_per_line))

    chunks: list[str] = []
    current: list[str] = []
    max_chars_per_cue = max_chars_per_line * max_lines

    for word in words:
        candidate = " ".join([*current, word])
        if current and (len(candidate) > max_chars_per_cue or len(wrapped_lines(candidate, max_chars_per_line)) > max_lines):
            chunks.append(" ".join(current))
            current = [word]
        else:
            current.append(word)

    if current:
        chunks.append(" ".join(current))
    return chunks or [text]


def wrap_subtitle_text(text: str, max_chars_per_line: int, max_lines: int) -> str:
    lines = wrapped_lines(text, max_chars_per_line)
    if len(lines) <= max_lines:
        return "\n".join(lines)

    return "\n".join(lines[: max_lines - 1] + [" ".join(lines[max_lines - 1 :])])


def clean_subtitle_quality(input_srt: Path, output_srt: Path, cfg: dict) -> None:
    output_srt.parent.mkdir(parents=True, exist_ok=True)
    sub_cfg = cfg["subtitles"]
    if not sub_cfg.get("quality_enabled", True):
        output_srt.write_text(input_srt.read_text(encoding="utf-8"), encoding="utf-8")
        return

    subs = pysubs2.load(str(input_srt), encoding="utf-8")
    max_chars_per_line = max(12, int(sub_cfg.get("max_chars_per_line", 38)))
    max_lines = max(1, int(sub_cfg.get("max_lines", 2)))
    max_chars_per_cue = max_chars_per_line * max_lines
    max_duration_ms = max(500, int(float(sub_cfg.get("max_cue_duration_seconds", 6.0)) * 1000))
    min_duration_ms = max(250, int(float(sub_cfg.get("min_cue_duration_seconds", 1.0)) * 1000))
    min_gap_ms = max(0, int(sub_cfg.get("min_gap_ms", 80)))
    split_long_cues = bool(sub_cfg.get("split_long_cues", True))

    cleaned = pysubs2.SSAFile()
    cleaned.info.update(subs.info)
    cleaned.styles.update(subs.styles)

    source_events = list(subs)
    for index, line in enumerate(source_events):
        text = normalize_subtitle_text(line.plaintext)
        if not text:
            continue

        chunks = [text]
        if split_long_cues and (len(text) > max_chars_per_cue or len(wrapped_lines(text, max_chars_per_line)) > max_lines):
            chunks = split_text_for_cues(text, max_chars_per_line, max_lines)

        end_limit = line.end
        if index + 1 < len(source_events):
            end_limit = min(end_limit, source_events[index + 1].start - min_gap_ms)
        original_duration = max(0, end_limit - line.start)
        gaps_total = min_gap_ms * max(0, len(chunks) - 1)
        usable_duration = max(0, original_duration - gaps_total)
        chunk_duration = max(min_duration_ms, min(max_duration_ms, usable_duration // len(chunks) if chunks else usable_duration))
        cursor = line.start

        for chunk in chunks:
            cue = copy.copy(line)
            cue.start = cursor
            cue.end = cursor + chunk_duration
            cue.plaintext = wrap_subtitle_text(chunk, max_chars_per_line, max_lines)
            cleaned.append(cue)
            cursor = cue.end + min_gap_ms

    cleaned.sort()
    for index, line in enumerate(cleaned):
        if line.end <= line.start:
            line.end = line.start + min_duration_ms
        line.end = min(line.end, line.start + max_duration_ms)
        if index + 1 < len(cleaned):
            next_line = cleaned[index + 1]
            if line.end + min_gap_ms > next_line.start:
                line.end = max(line.start + min(250, min_duration_ms), next_line.start - min_gap_ms)

    cleaned.remove_miscellaneous_events()
    cleaned.save(str(output_srt))


def maybe_preprocess_rtl(text: str, enabled: bool) -> str:
    if not enabled:
        return text
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text


def ass_color(value: str) -> pysubs2.Color:
    match = re.fullmatch(r"&H([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})", value)
    if not match:
        return pysubs2.Color(255, 255, 255, 0)
    a, b, g, r = (int(part, 16) for part in match.groups())
    return pysubs2.Color(r, g, b, a)


def add_branding_event(subs: pysubs2.SSAFile, base_style: pysubs2.SSAStyle, sub_cfg: dict) -> None:
    if not bool(sub_cfg.get("branding_enabled", True)):
        return
    branding_text = str(sub_cfg.get("branding_text", "")).strip()
    if not branding_text:
        return

    duration_ms = max(1000, int(float(sub_cfg.get("branding_duration_seconds", 20.0)) * 1000))
    branding_style = copy.copy(base_style)
    branding_style.fontsize = max(8, int(round(float(base_style.fontsize) * 0.85)))
    branding_style.alignment = 8
    branding_style.marginv = max(24, int(int(sub_cfg.get("margin_v", 180)) * 0.25))

    subs.styles["Branding"] = branding_style
    subs.events.insert(
        0,
        pysubs2.SSAEvent(
            start=0,
            end=duration_ms,
            text=maybe_preprocess_rtl(
                branding_text,
                sub_cfg.get("rtl_mode") == "preprocess_bidi" or bool(sub_cfg.get("rtl_preprocess_fallback", False)),
            ),
            style="Branding",
        ),
    )


def srt_to_ass(input_srt: Path, output_ass: Path, cfg: dict) -> None:
    output_ass.parent.mkdir(parents=True, exist_ok=True)
    sub_cfg = cfg["subtitles"]
    subs = pysubs2.load(str(input_srt), encoding="utf-8")

    style = pysubs2.SSAStyle()
    style.fontname = sub_cfg["font_name"]
    style.fontsize = int(sub_cfg["font_size"])
    style.primarycolor = ass_color(sub_cfg["primary_color"])
    style.outlinecolor = ass_color(sub_cfg["outline_color"])
    style.backcolor = ass_color(sub_cfg["back_color"])
    style.bold = bool(sub_cfg["bold"])
    style.borderstyle = 1
    style.outline = float(sub_cfg["outline"])
    style.shadow = float(sub_cfg["shadow"])
    style.alignment = int(sub_cfg["alignment"])
    style.marginl = int(sub_cfg["margin_l"])
    style.marginr = int(sub_cfg["margin_r"])
    style.marginv = int(sub_cfg["margin_v"])
    style.encoding = 1

    rtl_preprocess = sub_cfg["rtl_mode"] == "preprocess_bidi" or bool(sub_cfg["rtl_preprocess_fallback"])
    subs.styles["Default"] = style
    for line in subs:
        line.style = "Default"
        line.text = maybe_preprocess_rtl(line.text, rtl_preprocess)
    add_branding_event(subs, style, sub_cfg)
    subs.save(str(output_ass))
