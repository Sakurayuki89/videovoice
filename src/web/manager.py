import uuid
import os
import threading
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from .models import JobStatus, JobResponse, JobSettings, LogEntry, QualityResult, QualityBreakdown

# Configuration
MAX_LOGS_PER_JOB = 1000
JOB_EXPIRATION_HOURS = 24
MAX_JOBS = 1000  # Maximum jobs to keep in memory


class JobManager:
    def __init__(self):
        self._jobs: Dict[str, Dict] = {}
        self._cancelled: set = set()  # Track cancelled job IDs
        self._lock = threading.RLock()  # Reentrant lock for thread safety

    def _cleanup_old_jobs(self) -> None:
        """Remove expired jobs to prevent memory growth. Must be called with lock held."""
        if len(self._jobs) <= MAX_JOBS:
            return

        now = datetime.now()
        expiration_threshold = now - timedelta(hours=JOB_EXPIRATION_HOURS)

        # Find expired jobs
        expired_ids = [
            job_id for job_id, job in self._jobs.items()
            if job["created_at"] < expiration_threshold
            and job["status"] in ("completed", "failed")
        ]

        # Remove expired jobs
        for job_id in expired_ids:
            del self._jobs[job_id]

        # If still over limit, remove oldest completed/failed jobs
        if len(self._jobs) > MAX_JOBS:
            completed_jobs = [
                (job_id, job["created_at"])
                for job_id, job in self._jobs.items()
                if job["status"] in ("completed", "failed")
            ]
            completed_jobs.sort(key=lambda x: x[1])

            # Remove oldest until under limit
            remove_count = len(self._jobs) - MAX_JOBS
            for job_id, _ in completed_jobs[:remove_count]:
                del self._jobs[job_id]

    def _validate_job_id(self, job_id: str) -> bool:
        """Validate job ID format."""
        try:
            uuid.UUID(job_id, version=4)
            return True
        except (ValueError, AttributeError):
            return False

    def create_job(self, settings: JobSettings, input_file: str, input_type: str = "video") -> str:
        job_id = str(uuid.uuid4())
        input_filename = os.path.basename(input_file) if input_file else None

        # For audio input, skip extract and merge steps
        if input_type == "audio":
            steps = {
                "transcribe": "pending",
                "translate": "pending",
                "tts": "pending",
            }
        else:
            steps = {
                "extract": "pending",
                "transcribe": "pending",
                "translate": "pending",
                "tts": "pending",
                "merge": "pending"
            }

        with self._lock:
            # Cleanup old jobs if needed
            self._cleanup_old_jobs()

            self._jobs[job_id] = {
                "id": job_id,
                "status": JobStatus.QUEUED,
                "progress": 0,
                "current_step": "init",
                "steps": steps,
                "created_at": datetime.now(),
                "completed_at": None,
                "settings": settings,
                "input_file": input_file,
                "input_filename": input_filename,
                "input_type": input_type,
                "output_file": None,
                "logs": [],
                "error": None,
                "quality_result": None
            }

        return job_id

    def get_job(self, job_id: str) -> Optional[JobResponse]:
        if not self._validate_job_id(job_id):
            return None

        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None

            # Convert logs to LogEntry format (last 100)
            log_entries = [
                LogEntry(timestamp=log["timestamp"], message=log["message"])
                if isinstance(log, dict) else LogEntry(timestamp=datetime.now(), message=str(log))
                for log in job["logs"][-100:]
            ]

            return JobResponse(
                job_id=job["id"],
                status=job["status"],
                progress=job["progress"],
                current_step=job["current_step"],
                steps=job["steps"].copy(),
                created_at=job["created_at"],
                completed_at=job.get("completed_at"),
                error=job["error"],
                logs=log_entries,
                settings=job["settings"],
                output_file=job.get("output_file"),
                input_filename=job.get("input_filename"),
                quality_result=job.get("quality_result")
            )

    def update_status(self, job_id: str, status: str, error: str = None) -> bool:
        if not self._validate_job_id(job_id):
            return False

        with self._lock:
            if job_id not in self._jobs:
                return False
            self._jobs[job_id]["status"] = status
            if error:
                # Truncate error message to prevent memory issues
                self._jobs[job_id]["error"] = error[:1000] if len(error) > 1000 else error
            return True

    def update_progress(self, job_id: str, progress: int) -> bool:
        if not self._validate_job_id(job_id):
            return False

        # Validate progress range
        progress = max(0, min(100, progress))

        with self._lock:
            if job_id not in self._jobs:
                return False
            self._jobs[job_id]["progress"] = progress
            return True

    def update_step(self, job_id: str, step_key: str, status: str) -> bool:
        if not self._validate_job_id(job_id):
            return False

        # Validate step key
        valid_steps = {"extract", "transcribe", "translate", "tts", "merge"}
        if step_key not in valid_steps:
            return False

        # Validate status
        valid_statuses = {"pending", "processing", "done", "failed"}
        if status not in valid_statuses:
            return False

        with self._lock:
            if job_id not in self._jobs:
                return False
            self._jobs[job_id]["steps"][step_key] = status
            if status == "processing":
                self._jobs[job_id]["current_step"] = step_key
            return True

    def append_log(self, job_id: str, message: str) -> bool:
        if not self._validate_job_id(job_id):
            return False

        with self._lock:
            if job_id not in self._jobs:
                return False

            logs = self._jobs[job_id]["logs"]

            # Truncate message if too long
            if len(message) > 500:
                message = message[:500] + "..."

            # Keep only last MAX_LOGS_PER_JOB entries
            if len(logs) >= MAX_LOGS_PER_JOB:
                # Remove oldest 10% when limit reached
                remove_count = MAX_LOGS_PER_JOB // 10
                self._jobs[job_id]["logs"] = logs[remove_count:]

            # Store log with timestamp
            self._jobs[job_id]["logs"].append({
                "timestamp": datetime.now(),
                "message": message
            })
            return True

    def set_output_file(self, job_id: str, output_file: str) -> bool:
        """Set the output file path for a completed job."""
        if not self._validate_job_id(job_id):
            return False

        with self._lock:
            if job_id not in self._jobs:
                return False
            # Store as relative URL path
            self._jobs[job_id]["output_file"] = output_file
            return True

    def set_completed(self, job_id: str) -> bool:
        """Mark a job as completed with timestamp."""
        if not self._validate_job_id(job_id):
            return False

        with self._lock:
            if job_id not in self._jobs:
                return False
            self._jobs[job_id]["status"] = JobStatus.COMPLETED
            self._jobs[job_id]["completed_at"] = datetime.now()
            return True

    def set_quality_result(self, job_id: str, quality_result: dict) -> bool:
        """Set the quality validation result for a job."""
        if not self._validate_job_id(job_id):
            return False

        with self._lock:
            if job_id not in self._jobs:
                return False

            # Convert dict to QualityResult model
            try:
                breakdown = QualityBreakdown(**quality_result.get("breakdown", {}))
                result = QualityResult(
                    overall_score=quality_result.get("overall_score", 0),
                    breakdown=breakdown,
                    issues=quality_result.get("issues", []),
                    recommendation=quality_result.get("recommendation", "REVIEW_NEEDED"),
                    error=quality_result.get("error")
                )
                self._jobs[job_id]["quality_result"] = result
                return True
            except Exception as e:
                print(f"Failed to set quality result: {e}")
                return False

    def cancel_job(self, job_id: str) -> bool:
        """Request cancellation of a job."""
        if not self._validate_job_id(job_id):
            return False

        with self._lock:
            if job_id not in self._jobs:
                return False

            job = self._jobs[job_id]
            # Can only cancel queued or processing jobs
            if job["status"] not in (JobStatus.QUEUED, "processing"):
                return False

            self._cancelled.add(job_id)
            job["status"] = JobStatus.CANCELLED
            self.append_log(job_id, "Job cancelled by user")
            return True

    def is_cancelled(self, job_id: str) -> bool:
        """Check if a job has been cancelled."""
        with self._lock:
            return job_id in self._cancelled

    def get_input_file(self, job_id: str) -> Optional[str]:
        """Get the input file path for a job."""
        if not self._validate_job_id(job_id):
            return None

        with self._lock:
            job = self._jobs.get(job_id)
            return job["input_file"] if job else None

    def get_input_type(self, job_id: str) -> Optional[str]:
        """Get the input type (audio/video) for a job."""
        if not self._validate_job_id(job_id):
            return None

        with self._lock:
            job = self._jobs.get(job_id)
            return job.get("input_type", "video") if job else None

    def get_job_count(self) -> int:
        """Get current number of jobs."""
        with self._lock:
            return len(self._jobs)

    def get_active_job_count(self) -> int:
        """Get number of active (queued or processing) jobs."""
        with self._lock:
            return sum(
                1 for job in self._jobs.values()
                if job["status"] in (JobStatus.QUEUED, "processing")
            )


# Global instance
job_manager = JobManager()
