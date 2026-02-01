import os
import requests
import asyncio

# Load .env at startup
try:
    from dotenv import load_dotenv
    from pathlib import Path
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="VideoVoice API", version="0.1.0")

# CORS Configuration - Restrict to known origins
_env_origins = os.environ.get("CORS_ORIGINS", "")
_default_origins = ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174", "http://127.0.0.1:5174"]
ALLOWED_ORIGINS = list(set(o.strip() for o in _env_origins.split(",") if o.strip()) | set(_default_origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)

from fastapi.staticfiles import StaticFiles

from .routes import router
app.include_router(router)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return {"message": "VideoVoice API is running"}

async def get_elevenlabs_usage(api_key):
    if not api_key:
        return None
    try:
        def _fetch():
            response = requests.get(
                "https://api.elevenlabs.io/v1/user/subscription",
                headers={"xi-api-key": api_key},
                timeout=3
            )
            if response.status_code == 200:
                data = response.json()
                return {
                    "used": data.get("character_count", 0),
                    "limit": data.get("character_limit", 0)
                }
            return None
        return await asyncio.to_thread(_fetch)
    except Exception:
        return None

@app.get("/api/system/status")
async def system_status():
    from src.core.utils.vram import get_vram_info
    from .manager import job_manager

    vram_info = get_vram_info()

    # Check for API keys
    eleven_key = os.environ.get("ELEVENLABS_API_KEY")
    eleven_usage = await get_elevenlabs_usage(eleven_key) if eleven_key else None

    api_status = {
        "groq": "configured" if os.environ.get("GROQ_API_KEY") else "missing",
        "gemini": "configured" if os.environ.get("GEMINI_API_KEY") else "missing",
        "elevenlabs": "configured" if eleven_key else "missing",
        "openai": "configured" if os.environ.get("OPENAI_API_KEY") else "missing",
        "elevenlabs_usage": eleven_usage
    }

    if vram_info["available"]:
        return {
            "status": "online",
            "gpu": vram_info["device"],
            "vram_total": f"{vram_info['total_gb']:.1f}GB",
            "vram_used": f"{vram_info['allocated_gb']:.1f}GB",
            "active_jobs": job_manager.get_active_job_count(),
            "total_jobs": job_manager.get_job_count(),
            "api_status": api_status
        }
    else:
        return {
            "status": "online",
            "gpu": "CPU Only (No CUDA)",
            "vram_total": "N/A",
            "vram_used": "N/A",
            "active_jobs": job_manager.get_active_job_count(),
            "total_jobs": job_manager.get_job_count(),
            "api_status": api_status
        }
