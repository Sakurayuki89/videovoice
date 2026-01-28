from pydantic import BaseModel
from typing import Optional, Dict, Any
from enum import Enum
from datetime import datetime

class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SyncMode(str, Enum):
    """Dubbing sync mode for handling audio/video length mismatch."""
    OPTIMIZE = "optimize"  # Translate concisely to fit original duration
    STRETCH = "stretch"    # Stretch video to fit longer audio


class JobSettings(BaseModel):
    source_lang: str = "auto"
    target_lang: str = "ko"
    clone_voice: bool = True
    verify_translation: bool = False
    sync_mode: SyncMode = SyncMode.OPTIMIZE  # Default to natural translation

class LogEntry(BaseModel):
    timestamp: datetime
    message: str


class QualityBreakdown(BaseModel):
    accuracy: int = 0
    naturalness: int = 0
    dubbing_fit: int = 0
    consistency: int = 0


class QualityResult(BaseModel):
    overall_score: int = 0
    breakdown: QualityBreakdown = QualityBreakdown()
    issues: list[str] = []
    recommendation: str = "REVIEW_NEEDED"  # APPROVED, REVIEW_NEEDED, REJECT
    error: Optional[str] = None


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: int
    current_step: str
    steps: Dict[str, str]
    created_at: datetime
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    logs: list[LogEntry] = []
    settings: Optional[JobSettings] = None
    output_file: Optional[str] = None  # Relative URL to output file
    input_filename: Optional[str] = None  # Original input filename
    quality_result: Optional[QualityResult] = None  # Translation quality score

