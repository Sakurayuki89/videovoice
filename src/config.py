"""
VideoVoice Configuration

All settings can be overridden via environment variables.
"""
import os
from pathlib import Path

# Base Paths
PROJECT_ROOT = Path(__file__).parent.parent
STATIC_DIR = PROJECT_ROOT / "static"
UPLOAD_DIR = STATIC_DIR / "uploads"
OUTPUT_DIR = STATIC_DIR / "outputs"

# Ensure directories exist
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Server Configuration
HOST = os.environ.get("VIDEOVOICE_HOST", "0.0.0.0")
PORT = int(os.environ.get("VIDEOVOICE_PORT", "8000"))
DEBUG = os.environ.get("VIDEOVOICE_DEBUG", "false").lower() == "true"

# CORS Configuration
CORS_ORIGINS = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173"
).split(",")

# Authentication
AUTH_ENABLED = os.environ.get("VIDEOVOICE_AUTH_ENABLED", "false").lower() == "true"
API_KEYS = set(
    os.environ.get("VIDEOVOICE_API_KEYS", "dev-key-change-in-production").split(",")
)

# Rate Limiting
RATE_LIMIT_REQUESTS = int(os.environ.get("VIDEOVOICE_RATE_LIMIT", "10"))
RATE_LIMIT_WINDOW = int(os.environ.get("VIDEOVOICE_RATE_WINDOW", "60"))

# File Upload Limits
MAX_FILE_SIZE = int(os.environ.get("VIDEOVOICE_MAX_FILE_SIZE", str(500 * 1024 * 1024)))  # 500MB
ALLOWED_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm"}

# Supported Languages
ALLOWED_LANGUAGES = {"auto", "en", "ko", "ja", "ru", "zh", "es", "fr", "de"}

# Job Manager Configuration
MAX_JOBS = int(os.environ.get("VIDEOVOICE_MAX_JOBS", "1000"))
MAX_LOGS_PER_JOB = int(os.environ.get("VIDEOVOICE_MAX_LOGS", "1000"))
JOB_EXPIRATION_HOURS = int(os.environ.get("VIDEOVOICE_JOB_EXPIRATION", "24"))

# AI Model Configuration
WHISPER_MODEL = os.environ.get("VIDEOVOICE_WHISPER_MODEL", "large-v3")
WHISPER_BATCH_SIZE = int(os.environ.get("VIDEOVOICE_WHISPER_BATCH", "4"))
WHISPER_COMPUTE_TYPE = os.environ.get("VIDEOVOICE_WHISPER_COMPUTE", "float16")

OLLAMA_HOST = os.environ.get("VIDEOVOICE_OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("VIDEOVOICE_OLLAMA_MODEL", "qwen3:14b")
OLLAMA_TIMEOUT = int(os.environ.get("VIDEOVOICE_OLLAMA_TIMEOUT", "120"))

# Groq API (for translation and STT)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

# OpenAI API (for STT and TTS)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# ElevenLabs API (for TTS)
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")

# STT Engine
STT_ENGINE = os.environ.get("VIDEOVOICE_STT_ENGINE", "local")  # local, groq, openai

# Gemini API (for translation quality validation)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


TTS_MODEL = os.environ.get("VIDEOVOICE_TTS_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2")
TTS_ENGINE = os.environ.get("VIDEOVOICE_TTS_ENGINE", "auto")  # auto, xtts, edge, silero

# Edge TTS Voice Map (Microsoft Neural voices)
EDGE_TTS_VOICES = {
    "ko": os.environ.get("EDGE_TTS_VOICE_KO", "ko-KR-SunHiNeural"),
    "ru": os.environ.get("EDGE_TTS_VOICE_RU", "ru-RU-SvetlanaNeural"),
    "en": os.environ.get("EDGE_TTS_VOICE_EN", "en-US-AriaNeural"),
    "ja": os.environ.get("EDGE_TTS_VOICE_JA", "ja-JP-NanamiNeural"),
    "zh": os.environ.get("EDGE_TTS_VOICE_ZH", "zh-CN-XiaoxiaoNeural"),
    "es": os.environ.get("EDGE_TTS_VOICE_ES", "es-ES-ElviraNeural"),
    "fr": os.environ.get("EDGE_TTS_VOICE_FR", "fr-FR-DeniseNeural"),
    "de": os.environ.get("EDGE_TTS_VOICE_DE", "de-DE-KatjaNeural"),
}

# TTS auto-select map: language -> best engine when clone_voice is OFF
TTS_AUTO_SELECT = {
    "ko": "edge",
    "ru": "edge",
    "en": "xtts",
    "ja": "xtts",
    "zh": "edge",
    "es": "edge",
    "fr": "edge",
    "de": "edge",
}

# FFmpeg Configuration
FFMPEG_TIMEOUT = int(os.environ.get("VIDEOVOICE_FFMPEG_TIMEOUT", "600"))  # 10 minutes
STT_TIMEOUT = int(os.environ.get("VIDEOVOICE_STT_TIMEOUT", "300"))  # 5 minutes

# Translation Cache
CACHE_DIR = STATIC_DIR / "cache" / "translations"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
TRANSLATION_CACHE_ENABLED = os.environ.get("VIDEOVOICE_CACHE_ENABLED", "true").lower() == "true"
CACHE_EXPIRATION_DAYS = int(os.environ.get("VIDEOVOICE_CACHE_EXPIRATION_DAYS", "30"))

# Device Configuration (auto-detected if not set)
DEVICE = os.environ.get("VIDEOVOICE_DEVICE", "")  # "cuda", "cpu", or "" for auto


def get_device():
    """Get the compute device (cuda or cpu)."""
    if DEVICE:
        return DEVICE

    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"
