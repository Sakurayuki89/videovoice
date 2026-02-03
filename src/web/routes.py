from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends, Request
from fastapi.responses import FileResponse
from fastapi.security import APIKeyHeader
from typing import Optional
import shutil
import os
import uuid
import re
import time
from collections import defaultdict
from .models import JobSettings, JobResponse, SyncMode, TranslationEngine, TTSEngine, STTEngine, JobMode
from .manager import job_manager
from ..core.pipeline import pipeline
from ..config import STT_ENGINE, RATE_LIMIT_CLEANUP_THRESHOLD  # Import from config

router = APIRouter(prefix="/api")

UPLOAD_DIR = "static/uploads"
OUTPUT_DIR = "static/outputs"

# Security constants
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB
ALLOWED_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".mp3", ".wav", ".flac", ".ogg"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".ogg"}
ALLOWED_LANGUAGES = {
    "auto", "en", "ko", "ja", "zh", "ru",
    "es", "fr", "de", "it", "pt", "nl",
    "pl", "tr", "vi", "th", "ar", "hi",
}

# Authentication
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
# In production, load from environment variable or secrets manager
API_KEYS = set(os.environ.get("VIDEOVOICE_API_KEYS", "dev-key-change-in-production").split(","))
AUTH_ENABLED = os.environ.get("VIDEOVOICE_AUTH_ENABLED", "false").lower() == "true"  # loaded from .env

# Rate limiting (simple in-memory implementation)
RATE_LIMIT_REQUESTS = 1000  # requests per window
RATE_LIMIT_WINDOW = 60  # seconds
_rate_limit_store: dict = defaultdict(list)


def get_client_ip(request: Request) -> str:
    """Get client IP, considering proxy headers."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(request: Request) -> None:
    """Check if client has exceeded rate limit."""
    client_ip = get_client_ip(request)
    current_time = time.time()

    # Clean old entries for this IP
    _rate_limit_store[client_ip] = [
        t for t in _rate_limit_store[client_ip]
        if current_time - t < RATE_LIMIT_WINDOW
    ]

    # Proactive cleanup: Remove inactive IPs when threshold exceeded
    # Uses configurable threshold (default 100) instead of hardcoded 1000
    if len(_rate_limit_store) > RATE_LIMIT_CLEANUP_THRESHOLD:
        inactive_ips = [
            ip for ip, timestamps in _rate_limit_store.items()
            if not timestamps or current_time - max(timestamps) > RATE_LIMIT_WINDOW * 5
        ]
        for ip in inactive_ips:
            del _rate_limit_store[ip]

        # If still over threshold after cleanup, remove oldest entries
        if len(_rate_limit_store) > RATE_LIMIT_CLEANUP_THRESHOLD:
            # Sort by most recent activity and keep only threshold count
            sorted_ips = sorted(
                _rate_limit_store.items(),
                key=lambda x: max(x[1]) if x[1] else 0,
                reverse=True
            )
            _rate_limit_store.clear()
            for ip, timestamps in sorted_ips[:RATE_LIMIT_CLEANUP_THRESHOLD]:
                _rate_limit_store[ip] = timestamps

    # Check limit
    if len(_rate_limit_store[client_ip]) >= RATE_LIMIT_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail=f"요청 한도 초과. 최대 {RATE_LIMIT_REQUESTS}회/{RATE_LIMIT_WINDOW}초"
        )

    # Record request
    _rate_limit_store[client_ip].append(current_time)


async def verify_api_key(
    request: Request,
    api_key: Optional[str] = Depends(API_KEY_HEADER)
) -> None:
    """Verify API key if authentication is enabled."""
    if not AUTH_ENABLED:
        return  # Auth disabled, allow all

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="API key required. Provide X-API-Key header."
        )

    if api_key not in API_KEYS:
        raise HTTPException(
            status_code=403,
            detail="Invalid API key."
        )


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal and injection attacks."""
    # Extract just the filename, remove any directory components
    filename = os.path.basename(filename)
    # Remove any null bytes
    filename = filename.replace("\x00", "")
    # Keep only safe characters
    name, ext = os.path.splitext(filename)
    safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', name)
    # Generate unique prefix to prevent collisions
    unique_prefix = uuid.uuid4().hex[:8]
    return f"{unique_prefix}_{safe_name}{ext.lower()}"


def validate_file_extension(filename: str) -> bool:
    """Validate that file has an allowed extension."""
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def validate_language(lang: str) -> bool:
    """Validate that language code is allowed."""
    return lang in ALLOWED_LANGUAGES


def detect_input_type(filename: str) -> str:
    """Detect if the input file is audio or video based on extension."""
    ext = os.path.splitext(filename)[1].lower()
    return "audio" if ext in AUDIO_EXTENSIONS else "video"


@router.post("/jobs", response_model=JobResponse, dependencies=[Depends(verify_api_key)])
async def create_job(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    source_lang: str = Form("auto"),
    target_lang: str = Form("ko"),
    clone_voice: bool = Form(True),
    verify_translation: bool = Form(False),
    sync_mode: str = Form("optimize"),
    translation_engine: str = Form("gemini"),  # Match frontend default
    tts_engine: str = Form("auto"),
    stt_engine: str = Form(STT_ENGINE),  # Use config default here
    mode: str = Form("dubbing")  # "dubbing" | "subtitle"
):
    # Rate limit check
    check_rate_limit(request)

    # Validate mode
    valid_modes = {"dubbing", "subtitle"}
    if mode not in valid_modes:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}. Must be one of: {', '.join(valid_modes)}")

    # Subtitle mode requires video input
    # (validated later after file is saved)

    # Validate STT engine
    valid_stt_engines = {"local", "groq", "openai", "gemini"}
    if stt_engine not in valid_stt_engines:
        raise HTTPException(status_code=400, detail=f"Invalid stt_engine: {stt_engine}. Must be one of: {', '.join(valid_stt_engines)}")

    # Validate translation engine
    valid_engines = {"local", "groq", "gemini"}
    if translation_engine not in valid_engines:
        raise HTTPException(status_code=400, detail=f"Invalid translation_engine: {translation_engine}. Must be one of: {', '.join(valid_engines)}")

    # Validate TTS engine
    valid_tts_engines = {"auto", "xtts", "edge", "silero", "elevenlabs", "openai"}
    if tts_engine not in valid_tts_engines:
        raise HTTPException(status_code=400, detail=f"Invalid tts_engine: {tts_engine}. Must be one of: {', '.join(valid_tts_engines)}")

    # --- HIGH PRIORITY: API Key Pre-Validation ---
    # Check if required API keys exist for selected engines
    missing_keys = []
    if translation_engine == "groq" and not os.environ.get("GROQ_API_KEY"):
        missing_keys.append("GROQ_API_KEY (번역 엔진 Groq 사용시 필요)")
    if translation_engine == "gemini" and not os.environ.get("GEMINI_API_KEY"):
        missing_keys.append("GEMINI_API_KEY (번역 엔진 Gemini 사용시 필요)")
    if stt_engine == "groq" and not os.environ.get("GROQ_API_KEY"):
        missing_keys.append("GROQ_API_KEY (STT 엔진 Groq 사용시 필요)")
    if stt_engine == "openai" and not os.environ.get("OPENAI_API_KEY"):
        missing_keys.append("OPENAI_API_KEY (STT 엔진 OpenAI 사용시 필요)")
    if stt_engine == "gemini" and not os.environ.get("GEMINI_API_KEY"):
        missing_keys.append("GEMINI_API_KEY (STT 엔진 Gemini 사용시 필요)")
    if mode != "subtitle":
        if tts_engine == "elevenlabs" and not os.environ.get("ELEVENLABS_API_KEY"):
            missing_keys.append("ELEVENLABS_API_KEY (TTS 엔진 ElevenLabs 사용시 필요)")
        if tts_engine == "openai" and not os.environ.get("OPENAI_API_KEY"):
            missing_keys.append("OPENAI_API_KEY (TTS 엔진 OpenAI 사용시 필요)")
    if verify_translation and not os.environ.get("GEMINI_API_KEY"):
        missing_keys.append("GEMINI_API_KEY (번역 검증 사용시 필요)")
    
    if missing_keys:
        raise HTTPException(
            status_code=400, 
            detail=f"필수 API 키가 설정되지 않았습니다: {'; '.join(set(missing_keys))}"
        )
    # --- End API Key Pre-Validation ---

    # Validate language codes
    if not validate_language(source_lang):
        raise HTTPException(status_code=400, detail=f"Invalid source language: {source_lang}")
    if not validate_language(target_lang) or target_lang == "auto":
        raise HTTPException(status_code=400, detail=f"Invalid target language: {target_lang}")

    # Validate sync_mode
    valid_sync_modes = {"optimize", "speed_audio", "stretch"}
    if sync_mode not in valid_sync_modes:
        raise HTTPException(status_code=400, detail=f"Invalid sync_mode: {sync_mode}. Must be one of: {', '.join(valid_sync_modes)}")

    # Validate file extension
    if not file.filename or not validate_file_extension(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Check file size by reading in chunks
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    # Generate safe filename
    safe_filename = sanitize_filename(file.filename)
    file_path = os.path.join(UPLOAD_DIR, safe_filename)

    # Verify the path is within UPLOAD_DIR (defense in depth)
    abs_upload_dir = os.path.abspath(UPLOAD_DIR)
    abs_file_path = os.path.abspath(file_path)
    if not abs_file_path.startswith(abs_upload_dir):
        raise HTTPException(status_code=400, detail="Invalid file path")

    # Save file with size limit check
    total_size = 0
    try:
        with open(file_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):  # 1MB chunks
                total_size += len(chunk)
                if total_size > MAX_FILE_SIZE:
                    buffer.close()
                    os.remove(file_path)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB"
                    )
                buffer.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail="Failed to save file")
        
    settings = JobSettings(
        source_lang=source_lang,
        target_lang=target_lang,
        clone_voice=clone_voice,
        verify_translation=verify_translation,
        sync_mode=SyncMode(sync_mode),
        translation_engine=TranslationEngine(translation_engine),
        tts_engine=TTSEngine(tts_engine),
        stt_engine=STTEngine(stt_engine),
        mode=JobMode(mode)
    )
    
    # Detect if input is audio or video
    input_type = detect_input_type(file.filename)

    # #16 Fix: Validate that subtitle mode only accepts video input
    if mode == "subtitle" and input_type == "audio":
        os.remove(file_path)  # Clean up uploaded file
        raise HTTPException(
            status_code=400,
            detail="자막 모드는 비디오 파일만 지원합니다. 오디오 파일은 더빙 모드를 사용하세요."
        )

    # #14 Fix: Reject new jobs when too many are already active
    MAX_CONCURRENT_JOBS = int(os.environ.get("VIDEOVOICE_MAX_CONCURRENT_JOBS", "3"))
    active_count = job_manager.get_active_job_count()
    if active_count >= MAX_CONCURRENT_JOBS:
        os.remove(file_path)  # Clean up uploaded file
        raise HTTPException(
            status_code=429,
            detail=f"서버가 현재 {active_count}개의 작업을 처리 중입니다. 잠시 후 다시 시도해주세요. (최대 동시 작업: {MAX_CONCURRENT_JOBS})"
        )

    job_id = job_manager.create_job(settings, file_path, input_type=input_type, original_filename=file.filename)

    # Trigger pipeline
    background_tasks.add_task(pipeline.process_job, job_id)

    return job_manager.get_job(job_id)

def validate_job_id(job_id: str) -> str:
    """Validate job ID format (UUID)."""
    try:
        # Validate UUID format
        parsed = uuid.UUID(job_id, version=4)
        return str(parsed)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")


@router.get("/jobs/{job_id}", response_model=JobResponse, dependencies=[Depends(verify_api_key)])
async def get_job_status(request: Request, job_id: str):
    # Rate limit check
    check_rate_limit(request)

    # Validate job ID format
    validated_id = validate_job_id(job_id)

    job = job_manager.get_job(validated_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/jobs/{job_id}/cancel", dependencies=[Depends(verify_api_key)])
async def cancel_job(request: Request, job_id: str):
    """Cancel a queued or processing job."""
    # Rate limit check
    check_rate_limit(request)

    # Validate job ID format
    validated_id = validate_job_id(job_id)

    success = job_manager.cancel_job(validated_id)
    if not success:
        job = job_manager.get_job(validated_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job with status: {job.status}"
        )

    return {"message": "Job cancelled successfully", "job_id": validated_id}


@router.get("/jobs/{job_id}/download", dependencies=[Depends(verify_api_key)])
async def download_job_output(request: Request, job_id: str):
    """Download the output file for a completed job with Content-Disposition header."""
    check_rate_limit(request)
    validated_id = validate_job_id(job_id)

    job = job_manager.get_job(validated_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.output_file:
        raise HTTPException(status_code=404, detail="No output file available")

    # output_file is like "/static/outputs/dubbed_xxx.mp4"
    file_path = os.path.abspath(job.output_file.lstrip("/"))
    output_dir = os.path.abspath(OUTPUT_DIR)
    if not file_path.startswith(output_dir) or not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Output file not found on disk")

    ext = os.path.splitext(file_path)[1]
    filename = f"videovoice_{validated_id[:8]}{ext}"

    return FileResponse(
        file_path,
        filename=filename,
        media_type="application/octet-stream",
    )


# #4 Fix: Add SRT download endpoint for subtitle mode
@router.get("/jobs/{job_id}/srt", dependencies=[Depends(verify_api_key)])
async def download_job_srt(request: Request, job_id: str):
    """Download the SRT subtitle file for a completed subtitle job."""
    check_rate_limit(request)
    validated_id = validate_job_id(job_id)

    job = job_manager.get_job(validated_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check if this is a subtitle job
    mode = getattr(job.settings, 'mode', None)
    mode_value = mode.value if hasattr(mode, 'value') else mode
    if mode_value != 'subtitle':
        raise HTTPException(status_code=400, detail="SRT download is only available for subtitle mode jobs")

    # Construct SRT file path
    srt_path = os.path.join(OUTPUT_DIR, f"subtitle_{validated_id}.srt")
    abs_srt_path = os.path.abspath(srt_path)
    abs_output_dir = os.path.abspath(OUTPUT_DIR)

    if not abs_srt_path.startswith(abs_output_dir) or not os.path.isfile(abs_srt_path):
        raise HTTPException(status_code=404, detail="SRT file not found on disk")

    filename = f"videovoice_{validated_id[:8]}.srt"

    return FileResponse(
        abs_srt_path,
        filename=filename,
        media_type="text/srt",
    )

