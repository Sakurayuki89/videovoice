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

    def transcribe(self, audio_path: str, language: str = None) -> str:
        """Transcribe audio - dispatches to the configured engine."""
        self._validate_audio_path(audio_path)
        validated_lang = self._validate_language(language)

        if self.engine == "groq":
            return self._transcribe_groq(audio_path, validated_lang)
        elif self.engine == "openai":
            return self._transcribe_openai(audio_path, validated_lang)
        else:
            return self._transcribe_local(audio_path, validated_lang)

    def _transcribe_local(self, audio_path: str, language: str = None) -> str:
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
                return ""

            transcribed_text = " ".join([seg.text.strip() for seg in segment_list])

            if not transcribed_text.strip():
                print("WARNING: Transcription resulted in empty text")

            print("STT: Transcription complete")
            return transcribed_text

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            print(f"STT Failed: {e}")
            raise RuntimeError(f"Transcription failed: {str(e)}") from e
        finally:
            if model is not None:
                del model
            clear_vram("Faster-Whisper")

    def _transcribe_groq(self, audio_path: str, language: str = None) -> str:
        """Groq Whisper API transcription."""
        from ..config import GROQ_API_KEY
        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set. Required for Groq STT engine.")

        # Groq API has a 25MB file size limit
        file_size = os.path.getsize(audio_path)
        max_groq_size = 25 * 1024 * 1024  # 25MB
        if file_size > max_groq_size:
            raise RuntimeError(
                f"Audio file too large for Groq API ({file_size // (1024*1024)}MB). "
                f"Maximum: 25MB. Use 'local' STT engine for large files."
            )

        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)

        print(f"STT (Groq): Transcribing {audio_path}...")
        with open(audio_path, "rb") as audio_file:
            kwargs = {
                "file": ("audio.wav", audio_file),
                "model": "whisper-large-v3",
            }
            if language:
                kwargs["language"] = language

            transcription = client.audio.transcriptions.create(**kwargs)

        text = transcription.text.strip()
        if not text:
            print("WARNING: Groq STT returned empty text")
        else:
            print(f"STT (Groq): Transcription complete ({len(text)} chars)")
        return text

    def _transcribe_openai(self, audio_path: str, language: str = None) -> str:
        """OpenAI Whisper API transcription."""
        from ..config import OPENAI_API_KEY
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set. Required for OpenAI STT engine.")

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

            transcription = client.audio.transcriptions.create(**kwargs)

        text = transcription.text.strip()
        if not text:
            print("WARNING: OpenAI STT returned empty text")
        else:
            print(f"STT (OpenAI): Transcription complete ({len(text)} chars)")
        return text
