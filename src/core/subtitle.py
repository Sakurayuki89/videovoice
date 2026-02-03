"""Subtitle generation module: SRT creation, segment translation, and FFmpeg burn-in."""

import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid


def _format_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamp format: HH:MM:SS,mmm"""
    # Use round to avoid floating-point precision loss
    total_ms = round(seconds * 1000)
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    secs = (total_ms % 60_000) // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt(segments: list[dict], output_path: str) -> str:
    """Generate an SRT subtitle file from segments.

    Args:
        segments: List of {"start": float, "end": float, "text": str}
        output_path: Path to write the .srt file

    Returns:
        The output_path on success.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    idx = 1
    with open(output_path, "w", encoding="utf-8") as f:
        for seg in segments:
            text = seg["text"].strip()
            if not text:
                continue
            start = _format_srt_time(seg["start"])
            end = _format_srt_time(seg["end"])
            f.write(f"{idx}\n{start} --> {end}\n{text}\n\n")
            idx += 1

    return output_path


# ---------------------------------------------------------------------------
# Segment translation
# ---------------------------------------------------------------------------
# Import chunk size from config (with fallback for standalone usage)
try:
    from ..config import SUBTITLE_CHUNK_SIZE as _CHUNK_SIZE
except ImportError:
    _CHUNK_SIZE = 10  # Fallback default


def _build_batch_text(indexed_segments: list[tuple[int, str]]) -> str:
    """Build numbered batch text for translation."""
    lines = [f"<s{idx}>{text}</s{idx}>" for idx, text in indexed_segments]
    return "\n".join(lines)


def _parse_batch_result(translated: str, expected_ids: list[int]) -> dict[int, str]:
    """Parse translated batch text with <sN>...</sN> tags back into a map."""
    # Strip markdown code blocks that Gemini sometimes wraps around output
    translated = re.sub(r"^```[a-zA-Z]*\n?", "", translated.strip())
    translated = re.sub(r"\n?```\s*$", "", translated.strip())
    result = {}
    for idx in expected_ids:
        # Try XML-style tags first
        m = re.search(rf"<s{idx}>(.*?)</s{idx}>", translated, re.DOTALL)
        if m:
            result[idx] = m.group(1).strip()
            continue
        # Fallback: try [N] marker style (word boundary after digits to avoid [1] matching [10])
        m = re.search(rf"\[{idx}\](?!\d)\s*(.*?)(?=\[\d+\]|$)", translated, re.DOTALL)
        if m:
            result[idx] = m.group(1).strip()
    return result


def _translate_single_with_retry(translator, idx: int, text: str, source_lang: str, target_lang: str, translation_engine: str, translated_map: dict, max_retries: int = 2):
    """Translate a single segment with retry and engine fallback."""
    from .utils.llm import GeminiQuotaError
    engine = translation_engine
    for attempt in range(max_retries + 1):
        try:
            result = translator.translate(text, source_lang, target_lang, "optimize", engine)
            if result and result.strip():
                translated_map[idx] = result.strip()
                return
        except GeminiQuotaError:
            print(f"Gemini quota hit for segment {idx}, switching to groq")
            engine = "groq"
            continue
        except Exception as e:
            if attempt < max_retries:
                wait = 2 ** attempt
                print(f"Retry {attempt+1}/{max_retries} for segment {idx} after {wait}s: {e}")
                time.sleep(wait)
            else:
                print(f"Individual translation failed for segment {idx} after {max_retries+1} attempts: {e}")


def translate_segments(segments: list[dict], translator, source_lang: str, target_lang: str, translation_engine: str = "gemini", progress_callback=None) -> tuple[list[dict], float]:
    """Translate all segments using batching to preserve timing context.

    Handles batching in chunks to avoid timeout on long videos.
    Uses XML-style tags (<sN>text</sN>) for robustness.

    Args:
        progress_callback: Optional callable(current, total) for progress updates.

    Returns:
        Tuple of (translated_segments, success_rate) where success_rate is 0-100.
    """
    if not segments:
        return [], 100.0

    if source_lang == target_lang:
        return segments, 100.0

    # Map original index to translated text
    translated_map = {}
    to_translate = [(i, s["text"]) for i, s in enumerate(segments) if s["text"].strip()]

    if not to_translate:
        return segments

    total_chunks = (len(to_translate) + _CHUNK_SIZE - 1) // _CHUNK_SIZE
    
    # Process in chunks to avoid timeout and token limits
    for chunk_idx, chunk_start in enumerate(range(0, len(to_translate), _CHUNK_SIZE)):
        chunk = to_translate[chunk_start:chunk_start + _CHUNK_SIZE]
        batch_text = _build_batch_text(chunk)
        expected_ids = [idx for idx, _ in chunk]

        system_prompt = (
            f"You are a professional subtitle translator from {source_lang} to {target_lang}. "
            "RULES: Keep the <sN>...</sN> tags exactly as-is and put the translation inside them. "
            "Output ONLY the translated segments with tags. No explanations. No extra text.\n\n"
            "Example input:\n<s0>Hello world</s0>\n<s1>How are you?</s1>\n\n"
            f"Example output:\n<s0>[translation of 'Hello world' in {target_lang}]</s0>\n"
            f"<s1>[translation of 'How are you?' in {target_lang}]</s1>"
        )

        try:
            print(f"Translating subtitle chunk {chunk_start//_CHUNK_SIZE + 1} ({len(chunk)} segments)...")
            translated_batch = translator.translate_raw(
                batch_text, system_prompt, translation_engine
            )
            parsed = _parse_batch_result(translated_batch, expected_ids)
        except Exception as e:
            print(f"Batch translation failed: {e}")
            parsed = {}

        # Check parse success rate
        # #5 Fix: Use configurable threshold
        from ..config import SUBTITLE_BATCH_THRESHOLD
        threshold_ratio = SUBTITLE_BATCH_THRESHOLD / 100.0
        if len(parsed) >= len(expected_ids) * threshold_ratio:
            translated_map.update(parsed)
            # Fill missing items in this chunk individually if any
            if len(parsed) < len(expected_ids):
                missing = [c for c in chunk if c[0] not in parsed]
                print(f"Batch missing {len(missing)} items, translating individually...")
                for idx, text in missing:
                    _translate_single_with_retry(translator, idx, text, source_lang, target_lang, translation_engine, translated_map)
        else:
            # Fallback: translate individually for this whole chunk if batch failed completely
            print(f"Batch parsing failed ({len(parsed)}/{len(expected_ids)}), falling back to individual translation")
            for idx, text in chunk:
                _translate_single_with_retry(translator, idx, text, source_lang, target_lang, translation_engine, translated_map)

        # Report progress after each chunk
        if progress_callback:
            progress_callback(chunk_idx + 1, total_chunks)

    # Build final segments
    translated_segments = []
    for i, seg in enumerate(segments):
        translated_segments.append({
            "start": seg["start"],
            "end": seg["end"],
            "text": translated_map.get(i, seg["text"])
        })

    success_rate = len(translated_map) / len(to_translate) * 100 if to_translate else 100
    # Log failed segment indices for debugging
    if success_rate < 100:
        failed_indices = [i for i, _ in to_translate if i not in translated_map]
        print(f"Untranslated segment indices: {failed_indices}")
    print(f"Translation complete: {len(translated_map)}/{len(to_translate)} segments ({success_rate:.0f}%)")

    return translated_segments, success_rate


# ---------------------------------------------------------------------------
# FFmpeg subtitle burn-in
# ---------------------------------------------------------------------------

def _has_nvenc() -> bool:
    """Check if NVIDIA NVENC encoder is available."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, timeout=10
        )
        return b"h264_nvenc" in result.stdout
    except Exception:
        return False


def _is_safe_ffmpeg_path(path: str) -> bool:
    """Check if a path is safe for FFmpeg subtitles filter (ASCII, no special chars)."""
    try:
        path.encode("ascii")
        if not re.search(r'[\s()\[\]{}\'\"!#$%&]', os.path.basename(path)):
            return True
    except UnicodeEncodeError:
        pass
    return False


def _prepare_safe_path(file_path: str, prefix: str = "vv_sub") -> tuple[str, bool]:
    """Copy a file to a safe ASCII-only temp path for FFmpeg.

    Returns (safe_path, needs_cleanup).
    """
    if _is_safe_ffmpeg_path(file_path):
        return file_path, False

    # Copy to a safe temp path
    temp_dir = tempfile.gettempdir()
    ext = os.path.splitext(file_path)[1]
    safe_name = f"{prefix}_{uuid.uuid4().hex[:12]}{ext}"
    safe_path = os.path.join(temp_dir, safe_name)
    shutil.copy2(file_path, safe_path)
    return safe_path, True


def _prepare_safe_srt(srt_path: str) -> tuple[str, bool]:
    """Copy SRT to a safe ASCII-only temp path for FFmpeg subtitles filter."""
    return _prepare_safe_path(srt_path, prefix="vv_sub")


def _escape_srt_for_ffmpeg(srt_path: str) -> str:
    """Escape SRT path for FFmpeg subtitles filter."""
    # FFmpeg subtitles filter (libass) needs forward slashes and escaped colons/backslashes
    escaped = srt_path.replace("\\", "/").replace(":", "\\:").replace("'", "'\\''")
    return escaped


def _build_burn_cmd(video_path: str, escaped_srt: str, output_path: str, use_nvenc: bool) -> list[str]:
    """Build FFmpeg command for subtitle burn-in."""
    if use_nvenc:
        return [
            "ffmpeg", "-i", video_path,
            "-vf", f"subtitles='{escaped_srt}'",
            "-c:a", "copy",
            "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23",
            output_path, "-y"
        ]
    return [
        "ffmpeg", "-i", video_path,
        "-vf", f"subtitles='{escaped_srt}'",
        "-c:a", "copy",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        output_path, "-y"
    ]


def burn_subtitles(video_path: str, srt_path: str, output_path: str) -> bool:
    """Burn subtitles into video using FFmpeg subtitles filter.

    - Copies SRT to safe ASCII path to avoid encoding/special char issues
    - Automatically uses GPU encoding (h264_nvenc) if available
    - Falls back to libx264 fast on failure
    """
    if not os.path.isfile(video_path):
        print(f"Subtitle burn failed: Video not found: {video_path}")
        return False
    if not os.path.isfile(srt_path):
        print(f"Subtitle burn failed: SRT not found: {srt_path}")
        return False

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Copy SRT and video to safe paths to avoid FFmpeg path parsing issues with unicode
    safe_srt, srt_cleanup = _prepare_safe_srt(srt_path)
    safe_video, video_cleanup = _prepare_safe_path(video_path, prefix="vv_vid")
    escaped_srt = _escape_srt_for_ffmpeg(safe_srt)
    use_nvenc = _has_nvenc()

    def _cleanup():
        for path, needed in [(safe_srt, srt_cleanup), (safe_video, video_cleanup)]:
            if needed and os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    try:
        if use_nvenc:
            print("Subtitle burn: Using NVIDIA GPU encoding (h264_nvenc)")
        else:
            print("Subtitle burn: Using CPU encoding (libx264 fast)")

        cmd = _build_burn_cmd(safe_video, escaped_srt, output_path, use_nvenc)
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, timeout=600)
        return True

    except subprocess.CalledProcessError as e:
        stderr_msg = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""

        # NVENC failed → retry with CPU
        if use_nvenc:
            print(f"NVENC failed, retrying with CPU: {stderr_msg[:200]}")
            try:
                cmd_cpu = _build_burn_cmd(safe_video, escaped_srt, output_path, False)
                subprocess.run(cmd_cpu, check=True, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE, timeout=600)
                return True
            except Exception as e2:
                print(f"Subtitle burn CPU fallback failed: {e2}")
                return False

        print(f"Subtitle burn failed: {stderr_msg[:500]}")
        return False
    except subprocess.TimeoutExpired:
        print("Subtitle burn failed: Operation timed out")
        return False
    except FileNotFoundError:
        print("Subtitle burn failed: ffmpeg not found in PATH")
        return False
    finally:
        _cleanup()


def embed_soft_subtitles(video_path: str, srt_path: str, output_path: str, language: str = "ko") -> bool:
    """Embed subtitles as a separate track (soft subtitles) - VERY FAST.

    Unlike burn_subtitles which re-encodes the video (slow), this method:
    - Copies video/audio streams without re-encoding
    - Adds subtitle as a separate track
    - Completes in ~1 second regardless of video length

    Note: Subtitles can be toggled on/off in the player (not "burned in").
    """
    if not os.path.isfile(video_path):
        print(f"Soft subtitle embed failed: Video not found: {video_path}")
        return False
    if not os.path.isfile(srt_path):
        print(f"Soft subtitle embed failed: SRT not found: {srt_path}")
        return False

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Determine subtitle codec based on output container
    ext = os.path.splitext(output_path)[1].lower()
    if ext == ".mp4":
        sub_codec = "mov_text"
    elif ext == ".mkv":
        sub_codec = "srt"  # MKV supports SRT directly
    elif ext == ".webm":
        sub_codec = "webvtt"
    else:
        sub_codec = "mov_text"  # Default for MP4-like containers

    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-i", srt_path,
        "-c:v", "copy",
        "-c:a", "copy",
        "-c:s", sub_codec,
        "-map", "0:v",
        "-map", "0:a?",
        "-map", "1:0",
        "-metadata:s:s:0", f"language={language}",
        output_path, "-y"
    ]

    try:
        print(f"Embedding soft subtitles (codec: {sub_codec})...")
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, timeout=60)
        print("Soft subtitle embedding complete!")
        return True
    except subprocess.CalledProcessError as e:
        stderr_msg = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        print(f"Soft subtitle embed failed: {stderr_msg[:500]}")
        return False
    except subprocess.TimeoutExpired:
        print("Soft subtitle embed failed: Unexpected timeout")
        return False
    except FileNotFoundError:
        print("Soft subtitle embed failed: ffmpeg not found in PATH")
        return False
