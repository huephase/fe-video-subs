from __future__ import annotations

import re
import time
from pathlib import Path

import pysubs2
from deep_translator import GoogleTranslator
from faster_whisper import WhisperModel


_model_cache: dict[tuple[str, str, str], WhisperModel] = {}


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


def transcribe_to_srt(audio_path: Path, srt_path: Path, cfg: dict) -> None:
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    whisper = cfg["whisper"]
    segments, _ = whisper_model(cfg).transcribe(
        str(audio_path),
        beam_size=whisper["beam_size"],
        vad_filter=whisper["vad_filter"],
        language=whisper.get("source_language"),
        task="transcribe",
    )
    with srt_path.open("w", encoding="utf-8") as srt:
        index = 1
        for seg in segments:
            text = seg.text.strip()
            if text:
                srt.write(f"{index}\n{srt_time(seg.start)} --> {srt_time(seg.end)}\n{text}\n\n")
                index += 1


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
    subs.save(str(output_ass))

