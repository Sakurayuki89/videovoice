import os
import asyncio
import torch
from .utils.vram import clear_vram

# Configuration from environment variables
DEFAULT_TTS_MODEL = os.environ.get("VIDEOVOICE_TTS_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2")
DEFAULT_DEVICE = os.environ.get("VIDEOVOICE_DEVICE", "")

# Supported languages for XTTS v2
SUPPORTED_XTTS_LANGUAGES = {
    "en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru",
    "nl", "cs", "ar", "zh", "ja", "ko", "hu", "hi"
}

# Maximum text length for TTS (characters)
MAX_TEXT_LENGTH = 10000


class TTSModule:
    """Unified TTS module supporting multiple engines: xtts, edge, silero, elevenlabs, openai."""

    def __init__(self, engine: str = "xtts", device: str = None):
        self.engine = engine  # "xtts", "edge", "silero"

        if device is None:
            if DEFAULT_DEVICE:
                self.device = DEFAULT_DEVICE
            else:
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

    def generate(self, text: str, speaker_wav: str, output_path: str,
                 language: str = "ko", voice: str = None) -> bool:
        """Generate TTS audio. Dispatches to the appropriate engine.

        Args:
            text: Text to synthesize
            speaker_wav: Reference audio for voice cloning (used by xtts only)
            output_path: Path to write the output WAV/MP3
            language: Target language code
            voice: Optional voice ID override (for edge/silero)

        Returns:
            True on success
        """
        if self.engine == "edge":
            return asyncio.get_event_loop().run_until_complete(
                self._generate_edge(text, output_path, language, voice)
            )
        elif self.engine == "silero":
            return self._generate_silero(text, output_path, language, voice)
        elif self.engine == "elevenlabs":
            return self._generate_elevenlabs(text, speaker_wav, output_path, language)
        elif self.engine == "openai":
            return self._generate_openai(text, output_path, language, voice)
        else:
            return self._generate_xtts(text, speaker_wav, output_path, language)

    async def generate_async(self, text: str, speaker_wav: str, output_path: str,
                             language: str = "ko", voice: str = None) -> bool:
        """Async version of generate. Preferred when called from async context."""
        if self.engine == "edge":
            return await self._generate_edge(text, output_path, language, voice)
        elif self.engine == "silero":
            return await asyncio.to_thread(
                self._generate_silero, text, output_path, language, voice
            )
        elif self.engine == "elevenlabs":
            return await asyncio.to_thread(
                self._generate_elevenlabs, text, speaker_wav, output_path, language
            )
        elif self.engine == "openai":
            return await asyncio.to_thread(
                self._generate_openai, text, output_path, language, voice
            )
        else:
            return await asyncio.to_thread(
                self._generate_xtts, text, speaker_wav, output_path, language
            )

    # ──────────────────────────── Edge TTS ────────────────────────────

    async def _generate_edge(self, text: str, output_path: str,
                             language: str, voice: str = None) -> bool:
        """Edge TTS - free, high quality, no GPU required."""
        import edge_tts

        text = self._validate_text(text)
        self._validate_output_path(output_path)

        # Resolve voice
        if not voice:
            from ..config import EDGE_TTS_VOICES
            voice = EDGE_TTS_VOICES.get(language, "en-US-AriaNeural")

        print(f"Edge TTS: Generating with voice '{voice}' for language '{language}'...")

        # Edge TTS outputs mp3 by default; convert to wav if needed
        is_wav = output_path.lower().endswith(".wav")
        if is_wav:
            mp3_path = output_path.rsplit(".", 1)[0] + "_edge_temp.mp3"
        else:
            mp3_path = output_path

        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(mp3_path)

        if not os.path.isfile(mp3_path) or os.path.getsize(mp3_path) == 0:
            raise RuntimeError("Edge TTS failed to create output file")

        # Convert mp3 to wav if needed
        if is_wav:
            try:
                import subprocess
                result = subprocess.run(
                    ["ffmpeg", "-y", "-i", mp3_path, "-ar", "22050", "-ac", "1", output_path],
                    capture_output=True, timeout=60
                )
                if result.returncode != 0:
                    raise RuntimeError(f"FFmpeg conversion failed: {result.stderr.decode()[:200]}")
            finally:
                if os.path.exists(mp3_path):
                    os.remove(mp3_path)

        output_size = os.path.getsize(output_path)
        print(f"Edge TTS output created: {output_path} ({output_size} bytes)")
        return True

    # ──────────────────────────── Silero TTS ────────────────────────────

    def _generate_silero(self, text: str, output_path: str,
                         language: str, voice: str = None) -> bool:
        """Silero TTS - lightweight local, specialized for Russian."""
        text = self._validate_text(text)
        self._validate_output_path(output_path)

        if language != "ru":
            print(f"WARNING: Silero TTS is optimized for Russian. Language '{language}' may not work well.")

        print(f"Silero TTS: Generating for language '{language}'...")

        model, _ = torch.hub.load(
            repo_or_dir='snakers4/silero-models',
            model='silero_tts',
            language=language,
            speaker='v4_ru' if language == 'ru' else f'v4_{language}'
        )
        model.to(self.device)

        speaker = voice or ('baya' if language == 'ru' else 'random')
        audio = model.apply_tts(text=text, speaker=speaker, sample_rate=48000)

        # Save as WAV
        import torchaudio
        torchaudio.save(output_path, audio.unsqueeze(0).cpu(), 48000)

        if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError("Silero TTS failed to create output file")

        output_size = os.path.getsize(output_path)
        print(f"Silero TTS output created: {output_path} ({output_size} bytes)")

        del model
        clear_vram("Silero")
        return True

    # ──────────────────────────── XTTS v2 ────────────────────────────

    def _generate_xtts(self, text: str, speaker_wav: str,
                       output_path: str, language: str) -> bool:
        """XTTS v2 - voice cloning with speaker reference audio."""
        validated_text = self._validate_text(text)
        self._validate_speaker_wav(speaker_wav)
        self._validate_output_path(output_path)
        validated_lang = self._validate_xtts_language(language)

        tts = None
        try:
            from TTS.api import TTS
            print(f"Loading XTTS model... ({self.device})")
            tts = TTS(DEFAULT_TTS_MODEL).to(self.device)

            print(f"Generating TTS to {output_path}...")
            tts.tts_to_file(
                text=validated_text,
                file_path=output_path,
                speaker_wav=speaker_wav,
                language=validated_lang
            )

            if not os.path.isfile(output_path):
                raise RuntimeError("TTS failed to create output file")

            output_size = os.path.getsize(output_path)
            if output_size == 0:
                raise RuntimeError("TTS created empty output file")

            print(f"XTTS output created: {output_path} ({output_size} bytes)")
            return True

        except (ValueError, FileNotFoundError):
            raise
        except Exception as e:
            print(f"XTTS Failed: {e}")
            raise RuntimeError(f"XTTS generation failed: {str(e)}") from e
        finally:
            if tts is not None:
                del tts
            clear_vram("XTTS")

    # ──────────────────────────── ElevenLabs TTS ────────────────────────────

    def _generate_elevenlabs(self, text: str, speaker_wav: str,
                             output_path: str, language: str) -> bool:
        """ElevenLabs TTS - high quality with voice cloning support."""
        from ..config import ELEVENLABS_API_KEY, ELEVENLABS_MODEL
        if not ELEVENLABS_API_KEY:
            raise RuntimeError("ELEVENLABS_API_KEY is not set. Required for ElevenLabs TTS engine.")

        text = self._validate_text(text)
        self._validate_output_path(output_path)

        from elevenlabs.client import ElevenLabs

        client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

        # If speaker_wav is provided, use voice cloning via add voice
        if speaker_wav and os.path.isfile(speaker_wav):
            print(f"ElevenLabs TTS: Cloning voice from {speaker_wav}...")
            # Use 'ivc.create' method for Instant Voice Cloning in newer SDK versions
            import time
            # We must open the file in binary mode
            try:
                with open(speaker_wav, "rb") as audio_file:
                    voice = client.voices.ivc.create(
                        name=f"videovoice_clone_{int(time.time())}",
                        files=[audio_file],
                        description="Cloned voice for dubbing",
                    )
                voice_id = voice.voice_id
            except Exception as e:
                print(f"ElevenLabs Cloning Failed: {e}")
                if hasattr(e, 'body'):
                    print(f"Error Body: {e.body}")
                print("Falling back to default voice due to cloning error.")
                voice_id = "21m00Tcm4TlvDq8ikWAM"
        else:
            # Use default voice
            voice_id = "21m00Tcm4TlvDq8ikWAM"  # Rachel
            print(f"ElevenLabs TTS: Using default voice...")

        print(f"ElevenLabs TTS: Generating for language '{language}'...")
        # Use 'text_to_speech.convert' method in newer SDK versions
        audio = client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            model_id=ELEVENLABS_MODEL,
        )

        # audio is a generator of bytes
        with open(output_path, "wb") as f:
            for chunk in audio:
                f.write(chunk)

        if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError("ElevenLabs TTS failed to create output file")

        output_size = os.path.getsize(output_path)
        print(f"ElevenLabs TTS output created: {output_path} ({output_size} bytes)")
        return True

    # ──────────────────────────── OpenAI TTS ────────────────────────────

    def _generate_openai(self, text: str, output_path: str,
                         language: str, voice: str = None) -> bool:
        """OpenAI TTS - preset voices, no cloning."""
        from ..config import OPENAI_API_KEY
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set. Required for OpenAI TTS engine.")

        text = self._validate_text(text)
        self._validate_output_path(output_path)

        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        voice = voice or "alloy"
        print(f"OpenAI TTS: Generating with voice '{voice}' for language '{language}'...")

        response = client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text,
        )

        response.stream_to_file(output_path)

        if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError("OpenAI TTS failed to create output file")

        output_size = os.path.getsize(output_path)
        print(f"OpenAI TTS output created: {output_path} ({output_size} bytes)")
        return True

    # ──────────────────────────── Validation ────────────────────────────

    def _validate_text(self, text: str) -> str:
        if not text:
            raise ValueError("Text cannot be empty")
        text = text.strip()
        if not text:
            raise ValueError("Text cannot be empty after stripping whitespace")
        if len(text) > MAX_TEXT_LENGTH:
            print(f"WARNING: Text truncated from {len(text)} to {MAX_TEXT_LENGTH} characters")
            text = text[:MAX_TEXT_LENGTH]
        return text

    def _validate_speaker_wav(self, speaker_wav: str) -> None:
        if not speaker_wav:
            raise ValueError("Speaker WAV path cannot be empty")
        if not os.path.isfile(speaker_wav):
            raise FileNotFoundError(f"Speaker WAV file not found: {speaker_wav}")
        file_size = os.path.getsize(speaker_wav)
        if file_size < 10 * 1024:
            print("WARNING: Speaker WAV file is very small. Voice cloning quality may be poor.")
        if file_size > 50 * 1024 * 1024:
            raise ValueError(f"Speaker WAV file too large: {file_size} bytes (max 50MB)")

    def _validate_output_path(self, output_path: str) -> None:
        if not output_path:
            raise ValueError("Output path cannot be empty")
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

    def _validate_xtts_language(self, language: str) -> str:
        if not language:
            raise ValueError("Language code cannot be empty")
        lang = language.lower().strip()
        if lang not in SUPPORTED_XTTS_LANGUAGES:
            raise ValueError(
                f"Unsupported XTTS language: {lang}. "
                f"Supported: {', '.join(sorted(SUPPORTED_XTTS_LANGUAGES))}"
            )
        return lang


# Backward compatibility alias
XTTSModule = TTSModule
