from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends, Request
from fastapi.security import APIKeyHeader
from typing import Optional
import shutil
import os
import uuid
import re
import time
from collections import defaultdict
from .models import JobSettings, JobResponse, SyncMode
from .manager import job_manager
from ..core.pipeline import pipeline

router = APIRouter(prefix="/api")

UPLOAD_DIR = "static/uploads"
OUTPUT_DIR = "static/outputs"

# Security constants
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB
ALLOWED_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".mp3", ".wav", ".flac", ".ogg"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".ogg"}
ALLOWED_LANGUAGES = {"auto", "en", "ko", "ja", "ru", "zh", "es", "fr", "de"}

# Authentication
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
# In production, load from environment variable or secrets manager
API_KEYS = set(os.environ.get("VIDEOVOICE_API_KEYS", "dev-key-change-in-production").split(","))
AUTH_ENABLED = os.environ.get("VIDEOVOICE_AUTH_ENABLED", "false").lower() == "true"

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

    # Clean old entries
    _rate_limit_store[client_ip] = [
        t for t in _rate_limit_store[client_ip]
        if current_time - t < RATE_LIMIT_WINDOW
    ]

    # Check limit
    if len(_rate_limit_store[client_ip]) >= RATE_LIMIT_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Maximum {RATE_LIMIT_REQUESTS} requests per {RATE_LIMIT_WINDOW} seconds."
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
    sync_mode: str = Form("optimize")
):
    # Rate limit check
    check_rate_limit(request)
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
        sync_mode=SyncMode(sync_mode)
    )
    
    # Detect if input is audio or video
    input_type = detect_input_type(file.filename)
    
    job_id = job_manager.create_job(settings, file_path, input_type=input_type)
    
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
