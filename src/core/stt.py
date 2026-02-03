import os
import torch
from faster_whisper import WhisperModel
from .utils.vram import clear_vram

# Configuration from environment variables
DEFAULT_WHISPER_MODEL = os.environ.get("VIDEOVOICE_WHISPER_MODEL", "large-v3")
DEFAULT_WHISPER_BATCH = int(os.environ.get("VIDEOVOICE_WHISPER_BATCH", "4"))
DEFAULT_WHISPER_COMPUTE = os.environ.get("VIDEOVOICE_WHISPER_COMPUTE", "float16")
DEFAULT_DEVICE = os.environ.get("VIDEOVOICE_DEVICE", "")

# Supported languages (subset of what Whisper supports)
SUPPORTED_LANGUAGES = {
    "en", "ko", "ja", "ru", "zh", "es", "fr", "de", "it", "pt",
    "nl", "pl", "tr", "vi", "th", "ar", "hi", "he", "id", "ms"
}

# Minimum VRAM (in GB) to run on GPU
MIN_VRAM_GB = 4.0


def _get_free_vram_gb() -> float:
    """Return free VRAM in GB. Returns 0 if CUDA is unavailable."""
    try:
        if not torch.cuda.is_available():
            return 0.0
        free, _ = torch.cuda.mem_get_info()
        return free / (1024 ** 3)
    except Exception:
        return 0.0


def _normalize_segment(seg) -> dict:
    """Normalize a segment to {"start": float, "end": float, "text": str} regardless of source format."""
    if isinstance(seg, dict):
        return {
            "start": float(seg.get("start", 0)),
            "end": float(seg.get("end", 0)),
            "text": str(seg.get("text", "")).strip(),
        }
    # Object with attributes (e.g., Groq/OpenAI response objects)
    return {
        "start": float(getattr(seg, "start", 0)),
        "end": float(getattr(seg, "end", 0)),
        "text": str(getattr(seg, "text", "")).strip(),
    }


def _normalize_segments(raw_segments) -> list[dict]:
    """Normalize a list of segments from any STT engine."""
    if not raw_segments:
        return []
    return [s for s in (_normalize_segment(seg) for seg in raw_segments) if s["text"]]


class STTModule:
    def __init__(self, device: str = None, compute_type: str = None, model_name: str = None, engine: str = "local"):
        # Auto-detect device if not specified
        if device is None:
            if DEFAULT_DEVICE:
                self.device = DEFAULT_DEVICE
            else:
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

        # Set compute type based on device
        if compute_type is None:
            if self.device == "cuda":
                self.compute_type = DEFAULT_WHISPER_COMPUTE
            else:
                self.compute_type = "int8"  # CPU requires int8
        else:
            self.compute_type = compute_type

        self.model_name = model_name or DEFAULT_WHISPER_MODEL
        
        # Faster-Whisper does not use batch_size in init, but in transcribe
        # We'll keep the env var logic for consistency if needed later
        self.device_index = 0 if self.device == "cuda" else 0

        # VRAM pre-check: fall back to CPU if needed
        if self.device == "cuda":
            free_vram = _get_free_vram_gb()
            print(f"STT: Free VRAM = {free_vram:.1f} GB")
            if free_vram < MIN_VRAM_GB:
                print(f"STT: VRAM below {MIN_VRAM_GB} GB — falling back to CPU (int8)")
                self.device = "cpu"
                self.compute_type = "int8"

        self.engine = engine  # "local", "groq", "openai"

        if self.engine == "local" and self.device == "cpu":
            print("WARNING: Running Faster-Whisper on CPU. This will be significantly slower.")

    def _validate_audio_path(self, audio_path: str) -> None:
        """Validate that audio file exists and is accessible."""
        if not audio_path:
            raise ValueError("Audio path cannot be empty")
        if not os.path.isfile(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        # Check file size (max 1GB for audio)
        file_size = os.path.getsize(audio_path)
        if file_size > 1024 * 1024 * 1024:
            raise ValueError(f"Audio file too large: {file_size} bytes (max 1GB)")
        if file_size == 0:
            raise ValueError("Audio file is empty")

    def _validate_language(self, language: str) -> str:
        """Validate and normalize language code."""
        if language is None:
            return None  # Auto-detect
        lang = language.lower().strip()
        
        # Faster-Whisper might support more, but we check against our list if desired
        if lang and lang not in SUPPORTED_LANGUAGES:
            print(f"WARNING: Language '{lang}' may not be fully supported. Proceeding anyway.")
        return lang if lang else None

    def transcribe(self, audio_path: str, language: str = None, with_segments: bool = False):
        """Transcribe audio - dispatches to the configured engine.

        If with_segments=True, returns dict: {"text": str, "segments": [{"start", "end", "text"}]}
        Otherwise returns str (backward compatible).
        
        Automatic fallback: If Gemini fails with 429/quota, tries Groq → OpenAI → Local.
        """
        self._validate_audio_path(audio_path)
        validated_lang = self._validate_language(language)

        # Define fallback order based on current engine
        fallback_chain = []
        if self.engine == "gemini":
            fallback_chain = ["gemini", "groq", "openai", "local"]
        elif self.engine == "groq":
            fallback_chain = ["groq", "gemini", "openai", "local"]
        elif self.engine == "openai":
            fallback_chain = ["openai", "groq", "gemini", "local"]
        else:
            fallback_chain = ["local"]  # No fallback for local
        
        last_error = None
        for engine in fallback_chain:
            try:
                if engine == "groq":
                    result = self._transcribe_groq(audio_path, validated_lang, with_segments=with_segments)
                elif engine == "openai":
                    result = self._transcribe_openai(audio_path, validated_lang, with_segments=with_segments)
                elif engine == "gemini":
                    result = self._transcribe_gemini(audio_path, validated_lang, with_segments=with_segments)
                else:
                    result = self._transcribe_local(audio_path, validated_lang, with_segments=with_segments)
                return result
            except Exception as e:
                error_str = str(e).lower()
                # Check for quota/rate limit errors that should trigger fallback
                is_quota_error = any(kw in error_str for kw in ["429", "quota", "resource exhausted", "rate limit"])
                is_api_key_missing = "api_key" in error_str or "not set" in error_str
                
                if is_quota_error or is_api_key_missing:
                    print(f"STT ({engine}): {'Quota exceeded' if is_quota_error else 'API key missing'}, trying next engine...")
                    last_error = e
                    continue
                else:
                    # Non-quota error, don't fallback for other errors
                    raise
        
        # All fallbacks failed
        raise RuntimeError(f"모든 STT 엔진이 실패했습니다. 마지막 오류: {last_error}")

    def _transcribe_local(self, audio_path: str, language: str = None, with_segments: bool = False):
        """Local Faster-Whisper transcription."""
        model = None
        try:
            print(f"STT: Loading Faster-Whisper model '{self.model_name}' on {self.device} ({self.compute_type})...")
            try:
                model = WhisperModel(
                    self.model_name,
                    device=self.device,
                    compute_type=self.compute_type,
                    device_index=self.device_index
                )
            except Exception as e:
                if self.device == "cuda":
                    print(f"STT: GPU model loading failed ({e}), retrying on CPU with int8...")
                    clear_vram("Faster-Whisper-fallback")
                    self.device = "cpu"
                    self.compute_type = "int8"
                    model = WhisperModel(
                        self.model_name,
                        device=self.device,
                        compute_type=self.compute_type
                    )
                else:
                    raise
            print("STT: Model loaded successfully")

            print(f"STT: Transcribing {audio_path}...")

            segments, info = model.transcribe(
                audio_path,
                language=language,
                beam_size=5
            )

            print(f"STT: Detected language '{info.language}' with probability {info.language_probability:.2f}")

            segment_list = list(segments)

            if not segment_list:
                print("WARNING: No speech detected in audio")
                if with_segments:
                    return {"text": "", "segments": []}
                return ""

            transcribed_text = " ".join([seg.text.strip() for seg in segment_list])

            if not transcribed_text.strip():
                print("WARNING: Transcription resulted in empty text")

            print("STT: Transcription complete")

            if with_segments:
                return {"text": transcribed_text, "segments": _normalize_segments(segment_list)}
            return transcribed_text

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            print(f"STT Failed: {e}")
            raise RuntimeError(f"음성 인식 실패: {str(e)}") from e
        finally:
            if model is not None:
                del model
            clear_vram("Faster-Whisper")

    def _transcribe_groq(self, audio_path: str, language: str = None, with_segments: bool = False):
        """Groq Whisper API transcription with automatic compression for large files."""
        from ..config import GROQ_API_KEY
        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY가 설정되지 않았습니다. Groq STT 엔진에 필요합니다.")

        file_size = os.path.getsize(audio_path)
        max_groq_size = 25 * 1024 * 1024  # 25MB
        
        current_audio = audio_path
        temp_compressed = None

        # Automatic compression if file exceeds Groq's 25MB limit
        if file_size > max_groq_size:
            print(f"STT (Groq): Audio ({file_size // 1048576}MB) exceeds 25MB limit. Compressing...")
            import subprocess
            temp_compressed = audio_path + ".compressed.mp3"
            try:
                # Convert to mono, 64kbps MP3 (perfect for STT, very small)
                subprocess.run([
                    "ffmpeg", "-i", audio_path,
                    "-acodec", "libmp3lame",
                    "-ab", "64k", "-ac", "1", "-ar", "16000",
                    temp_compressed, "-y"
                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                
                new_size = os.path.getsize(temp_compressed)
                if new_size > max_groq_size:
                    raise RuntimeError(f"압축 불충분: {new_size // 1048576}MB (여전히 25MB 초과)")
                
                current_audio = temp_compressed
                print(f"STT (Groq): Successfully compressed to {new_size // 1048576}MB")
            except Exception as e:
                if temp_compressed and os.path.exists(temp_compressed):
                    os.remove(temp_compressed)
                print(f"STT (Groq): Compression failed ({e}), attempting with original (may fail)")

        try:
            from groq import Groq
            client = Groq(api_key=GROQ_API_KEY)

            print(f"STT (Groq): Transcribing {current_audio}...")
            with open(current_audio, "rb") as audio_file:
                kwargs = {
                    "file": (os.path.basename(current_audio), audio_file),
                    "model": "whisper-large-v3",
                }
                if language:
                    kwargs["language"] = language
                if with_segments:
                    kwargs["response_format"] = "verbose_json"

                transcription = client.audio.transcriptions.create(**kwargs)

            text = transcription.text.strip() if hasattr(transcription, 'text') else ""
            if with_segments:
                raw_segs = transcription.segments if hasattr(transcription, 'segments') and transcription.segments else []
                segments = _normalize_segments(raw_segs)
                print(f"STT (Groq): Transcription complete ({len(text)} chars, {len(segments)} segments)")
                return {"text": text, "segments": segments}

            print(f"STT (Groq): Transcription complete ({len(text)} chars)")
            return text
        finally:
            if temp_compressed and os.path.exists(temp_compressed):
                try: os.remove(temp_compressed)
                except Exception as e: print(f"Warning: Could not remove temp file: {e}")

    def _transcribe_openai(self, audio_path: str, language: str = None, with_segments: bool = False):
        """OpenAI Whisper API transcription."""
        from ..config import OPENAI_API_KEY
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다. OpenAI STT 엔진에 필요합니다.")

        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        print(f"STT (OpenAI): Transcribing {audio_path}...")
        with open(audio_path, "rb") as audio_file:
            kwargs = {
                "file": audio_file,
                "model": "whisper-1",
            }
            if language:
                kwargs["language"] = language
            if with_segments:
                kwargs["response_format"] = "verbose_json"

            transcription = client.audio.transcriptions.create(**kwargs)

        text = transcription.text.strip() if hasattr(transcription, 'text') else ""
        if with_segments:
            raw_segs = transcription.segments if hasattr(transcription, 'segments') and transcription.segments else []
            segments = _normalize_segments(raw_segs)
            print(f"STT (OpenAI): Transcription complete ({len(text)} chars, {len(segments)} segments)")
            return {"text": text, "segments": segments}

        if not text:
            print("WARNING: OpenAI STT returned empty text")
        else:
            print(f"STT (OpenAI): Transcription complete ({len(text)} chars)")
        return text

    def _transcribe_gemini(self, audio_path: str, language: str = None, with_segments: bool = False):
        """Gemini API transcription using audio upload."""
        from ..config import GEMINI_API_KEY, GEMINI_MODEL
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY가 설정되지 않았습니다. Gemini STT 엔진에 필요합니다.")

        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)

        print(f"STT (Gemini): Uploading audio {audio_path}...")
        audio_file = genai.upload_file(audio_path)

        lang_hint = f" The audio language is {language}." if language else ""
        if with_segments:
            prompt = (
                f"Transcribe this audio file accurately (language: {language or 'auto'}).\n\n"
                "Return the result as a JSON object with a single key 'segments', containing a list of objects. "
                "Each object MUST have 'start' (float seconds), 'end' (float seconds), and 'text' (string).\n\n"
                "FORMAT EXAMPLE:\n"
                '{"segments": [{"start": 0.0, "end": 2.5, "text": "Hello world"}]}\n\n'
                "RULES:\n"
                "- Segment by natural pauses or sentences\n"
                "- Timestamps must be numbers (seconds)\n"
                "- Return ONLY the JSON object"
            )
        else:
            prompt = (
                f"Transcribe this audio file accurately (language: {language or 'auto'}). "
                "Return ONLY the transcribed text, nothing else."
            )

        print(f"STT (Gemini): Transcribing with {GEMINI_MODEL}...")
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(
            [prompt, audio_file],
            generation_config=genai.types.GenerationConfig(
                temperature=0.1,
                response_mime_type="application/json" if with_segments else "text/plain"
            ),
        )

        raw = response.text.strip()

        # Clean up uploaded file
        try:
            genai.delete_file(audio_file.name)
        except Exception:
            pass

        if with_segments:
            import json
            import re
            # Comprehensive JSON extraction
            json_match = re.search(r'(\{.*\})', raw, re.DOTALL)
            cleaned = json_match.group(1) if json_match else raw
            
            # Remove markdown fences as a backup
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)
            
            try:
                data = json.loads(cleaned)
                raw_segs = data.get("segments", []) if isinstance(data, dict) else []
                segments = _normalize_segments(raw_segs)
                
                # #6 Fix: Return empty segments instead of dummy with wrong timestamps
                if not segments and raw:
                    print("STT (Gemini): WARNING - No segments parsed from JSON, returning empty segments")
                    # Return text but empty segments - caller should handle this
                
                text = " ".join(s["text"] for s in segments) if segments else raw.strip()
                print(f"STT (Gemini): Transcription complete ({len(text)} chars, {len(segments)} segments)")
                return {"text": text, "segments": segments}
            except (json.JSONDecodeError, KeyError) as e:
                print(f"STT (Gemini): Failed to parse JSON ({e}). Raw response: {raw[:200]}...")
                return {"text": raw, "segments": []}

        if not raw:
            print("WARNING: Gemini STT returned empty text")
        else:
            print(f"STT (Gemini): Transcription complete ({len(raw)} chars)")
        return raw
