import whisperx
import os
import torch
from .utils.vram import clear_vram

# Configuration from environment variables
DEFAULT_WHISPER_MODEL = os.environ.get("VIDEOVOICE_WHISPER_MODEL", "large-v3")
DEFAULT_WHISPER_BATCH = int(os.environ.get("VIDEOVOICE_WHISPER_BATCH", "4"))
DEFAULT_WHISPER_COMPUTE = os.environ.get("VIDEOVOICE_WHISPER_COMPUTE", "float16")
DEFAULT_DEVICE = os.environ.get("VIDEOVOICE_DEVICE", "")

# Supported languages for WhisperX
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
    def __init__(self, device: str = None, compute_type: str = None, model_name: str = None):
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
        # Adjust batch size for CPU
        self.batch_size = DEFAULT_WHISPER_BATCH if self.device == "cuda" else 1

        # VRAM pre-check: reduce batch_size or fall back to CPU
        if self.device == "cuda":
            free_vram = _get_free_vram_gb()
            print(f"STT: Free VRAM = {free_vram:.1f} GB")
            if free_vram < MIN_VRAM_GB:
                print(f"STT: VRAM below {MIN_VRAM_GB} GB — falling back to CPU (int8)")
                self.device = "cpu"
                self.compute_type = "int8"
                self.batch_size = 1
            elif free_vram < 8.0 and self.batch_size > 1:
                print("STT: Low VRAM — reducing batch_size to 1")
                self.batch_size = 1

        if self.device == "cpu":
            print("WARNING: Running WhisperX on CPU. This will be significantly slower.")

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
        if lang and lang not in SUPPORTED_LANGUAGES:
            print(f"WARNING: Language '{lang}' may not be fully supported. Proceeding anyway.")
        return lang if lang else None

    def transcribe(self, audio_path: str, language: str = None) -> str:
        # Validate inputs
        self._validate_audio_path(audio_path)
        validated_lang = self._validate_language(language)

        model = None
        try:
            print(f"STT: Loading WhisperX model '{self.model_name}' on {self.device} ({self.compute_type}, batch={self.batch_size})...")
            try:
                model = whisperx.load_model(
                    self.model_name,
                    self.device,
                    compute_type=self.compute_type
                )
            except (RuntimeError, torch.cuda.OutOfMemoryError) as e:
                if self.device == "cuda":
                    print(f"STT: GPU model loading failed ({e}), retrying on CPU with int8...")
                    clear_vram("WhisperX-fallback")
                    self.device = "cpu"
                    self.compute_type = "int8"
                    self.batch_size = 1
                    model = whisperx.load_model(
                        self.model_name,
                        self.device,
                        compute_type=self.compute_type
                    )
                else:
                    raise
            print("STT: Model loaded successfully")

            print(f"STT: Loading audio from {audio_path}...")
            audio = whisperx.load_audio(audio_path)
            print(f"STT: Audio loaded, starting transcription...")

            # Use provided language for transcription (None = auto-detect)
            result = model.transcribe(
                audio,
                batch_size=self.batch_size,
                language=validated_lang
            )
            print("STT: Transcription complete")

            # Check if we got any segments
            segments = result.get("segments", [])
            if not segments:
                print("WARNING: No speech detected in audio")
                return ""

            # Combine segments
            transcribed_text = " ".join([seg["text"].strip() for seg in segments])

            if not transcribed_text.strip():
                print("WARNING: Transcription resulted in empty text")

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
            clear_vram("WhisperX")
