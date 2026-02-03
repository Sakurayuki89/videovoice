import uuid
import os
import json
import threading
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from .models import JobStatus, JobResponse, JobSettings, LogEntry, QualityResult, QualityBreakdown

# Configuration
MAX_LOGS_PER_JOB = 1000
JOB_EXPIRATION_HOURS = 24
MAX_JOBS = 1000  # Maximum jobs to keep in memory

# Allowed directories for file cleanup (safety check)
UPLOAD_DIR = os.path.abspath("static/uploads")
OUTPUT_DIR = os.path.abspath("static/outputs")

# Persistence
JOBS_PERSIST_FILE = os.path.join("static", "jobs.json")


class JobManager:
    def __init__(self):
        self._jobs: Dict[str, Dict] = {}
        self._cancelled: set = set()  # Track cancelled job IDs
        self._lock = threading.RLock()  # Reentrant lock for thread safety
        self._load_jobs()

    def _serialize_job(self, job: Dict) -> dict:
        """Convert a job dict to JSON-serializable format."""
        data = {}
        for k, v in job.items():
            if k == "settings":
                data[k] = v.model_dump() if hasattr(v, 'model_dump') else (v.dict() if hasattr(v, 'dict') else str(v))
            elif k == "quality_result" and v is not None:
                data[k] = v.model_dump() if hasattr(v, 'model_dump') else (v.dict() if hasattr(v, 'dict') else None)
            elif isinstance(v, datetime):
                data[k] = v.isoformat()
            elif isinstance(v, JobStatus):
                data[k] = v.value
            elif k == "logs":
                # Only persist last 20 logs to keep file small
                data[k] = [
                    {"timestamp": (lg["timestamp"].isoformat() if isinstance(lg["timestamp"], datetime) else lg["timestamp"]),
                     "message": lg["message"]}
                    for lg in (v[-20:] if v else [])
                ]
            else:
                data[k] = v
        return data

    def _deserialize_job(self, data: dict) -> Dict:
        """Convert JSON data back to a job dict."""
        job = dict(data)
        # Restore datetime fields
        for field in ("created_at", "completed_at"):
            if job.get(field):
                job[field] = datetime.fromisoformat(job[field])
            elif field == "created_at":
                job[field] = datetime.now()
        # Restore settings
        if isinstance(job.get("settings"), dict):
            job["settings"] = JobSettings(**job["settings"])
        # Restore quality_result
        if isinstance(job.get("quality_result"), dict):
            try:
                breakdown = QualityBreakdown(**job["quality_result"].get("breakdown", {}))
                job["quality_result"] = QualityResult(breakdown=breakdown, **{
                    k: v for k, v in job["quality_result"].items() if k != "breakdown"
                })
            except Exception:
                job["quality_result"] = None
        # Restore logs timestamps
        if job.get("logs"):
            for lg in job["logs"]:
                if isinstance(lg.get("timestamp"), str):
                    try:
                        lg["timestamp"] = datetime.fromisoformat(lg["timestamp"])
                    except (ValueError, TypeError):
                        lg["timestamp"] = datetime.now()
        return job

    def _save_jobs(self) -> None:
        """Persist all jobs to disk. Must be called with lock held."""
        try:
            os.makedirs(os.path.dirname(JOBS_PERSIST_FILE), exist_ok=True)
            serialized = {jid: self._serialize_job(j) for jid, j in self._jobs.items()}
            tmp_path = JOBS_PERSIST_FILE + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(serialized, f, ensure_ascii=False)
            os.replace(tmp_path, JOBS_PERSIST_FILE)
        except Exception as e:
            print(f"[JobManager] Failed to persist jobs: {e}")

    def _load_jobs(self) -> None:
        """Load jobs from disk on startup. Mark interrupted jobs as failed."""
        if not os.path.isfile(JOBS_PERSIST_FILE):
            return
        try:
            with open(JOBS_PERSIST_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for jid, data in raw.items():
                job = self._deserialize_job(data)
                # Mark interrupted jobs as failed
                if job.get("status") in (JobStatus.PROCESSING, "processing", JobStatus.QUEUED, "queued"):
                    job["status"] = JobStatus.FAILED
                    job["error"] = "서버가 재시작되어 작업이 중단되었습니다."
                    job["logs"] = job.get("logs", [])
                    job["logs"].append({
                        "timestamp": datetime.now(),
                        "message": "서버 재시작으로 작업 중단됨"
                    })
                # Restore cancelled status into _cancelled set
                if job.get("status") == JobStatus.CANCELLED:
                    self._cancelled.add(jid)
                self._jobs[jid] = job
            print(f"[JobManager] Loaded {len(self._jobs)} jobs from disk ({len(self._cancelled)} cancelled)")
        except Exception as e:
            print(f"[JobManager] Failed to load jobs: {e}")

    def _safe_remove(self, path: str) -> bool:
        """Safely remove a file if it exists within allowed directories."""
        if not path:
            return False
        try:
            abs_path = os.path.abspath(path.lstrip("/"))
            if not (abs_path.startswith(UPLOAD_DIR) or abs_path.startswith(OUTPUT_DIR)):
                return False
            if os.path.isfile(abs_path):
                os.remove(abs_path)
                return True
        except OSError:
            pass
        return False

    def _cleanup_job_files(self, job: Dict) -> None:
        """Remove all files associated with a job (input + output)."""
        # Clean input/upload file
        input_file = job.get("input_file")
        if input_file:
            self._safe_remove(input_file)

        # Clean output file (e.g. dubbed_xxx.mp4, subtitle_xxx.mp4)
        output_file = job.get("output_file")
        if output_file:
            self._safe_remove(output_file)

        # Clean associated SRT file for subtitle jobs
        job_id = job.get("id", "")
        srt_path = os.path.join(OUTPUT_DIR, f"subtitle_{job_id}.srt")
        self._safe_remove(srt_path)

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
            and job["status"] in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)  # #6 Fix: Use enum consistently
        ]

        # Remove expired jobs and their files
        for job_id in expired_ids:
            self._cleanup_job_files(self._jobs[job_id])
            del self._jobs[job_id]

        # If still over limit, remove oldest completed/failed jobs
        if len(self._jobs) > MAX_JOBS:
            completed_jobs = [
                (job_id, job["created_at"])
                for job_id, job in self._jobs.items()
                if job["status"] in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)  # #6 Fix: Use enum consistently
            ]
            completed_jobs.sort(key=lambda x: x[1])

            # Remove oldest until under limit
            remove_count = len(self._jobs) - MAX_JOBS
            for job_id, _ in completed_jobs[:remove_count]:
                self._cleanup_job_files(self._jobs[job_id])
                del self._jobs[job_id]

    def _validate_job_id(self, job_id: str) -> bool:
        """Validate job ID format."""
        try:
            uuid.UUID(job_id, version=4)
            return True
        except (ValueError, AttributeError):
            return False

    def create_job(self, settings: JobSettings, input_file: str, input_type: str = "video", original_filename: str = None) -> str:
        job_id = str(uuid.uuid4())
        input_filename = original_filename or (os.path.basename(input_file) if input_file else None)

        mode = getattr(settings, 'mode', 'dubbing')
        mode_value = mode.value if hasattr(mode, 'value') else mode

        if mode_value == "subtitle":
            steps = {
                "extract": "pending",
                "transcribe": "pending",
                "translate": "pending",
                "subtitle": "pending",
                "burn": "pending",
            }
        elif input_type == "audio":
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

        self._save_jobs()
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
            self._save_jobs()
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
        valid_steps = {"extract", "transcribe", "translate", "tts", "merge", "subtitle", "burn"}
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
            self._save_jobs()
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
            self._save_jobs()
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
            if job["status"] not in (JobStatus.QUEUED, JobStatus.PROCESSING):  # #6 Fix: Use enum consistently
                return False

            self._cancelled.add(job_id)
            job["status"] = JobStatus.CANCELLED
            self.append_log(job_id, "Job cancelled by user")
            self._save_jobs()
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
                if job["status"] in (JobStatus.QUEUED, JobStatus.PROCESSING)  # #6 Fix: Use enum consistently
            )


    def cleanup_expired_jobs(self) -> int:
        """Force cleanup of all expired jobs and their files. Returns count of cleaned jobs."""
        cleaned = 0
        now = datetime.now()
        expiration_threshold = now - timedelta(hours=JOB_EXPIRATION_HOURS)

        with self._lock:
            expired_ids = [
                job_id for job_id, job in self._jobs.items()
                if job["created_at"] < expiration_threshold
                and job["status"] in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)  # #6 Fix: Use enum consistently
            ]
            for job_id in expired_ids:
                self._cleanup_job_files(self._jobs[job_id])
                del self._jobs[job_id]
                cleaned += 1

        return cleaned

    def cleanup_orphan_files(self) -> dict:
        """Remove files in uploads/outputs that don't belong to any active job."""
        removed = {"uploads": 0, "outputs": 0}

        with self._lock:
            # Collect all known file paths from active jobs
            known_inputs = set()
            known_outputs = set()
            for job in self._jobs.values():
                inp = job.get("input_file")
                if inp:
                    known_inputs.add(os.path.abspath(inp))
                out = job.get("output_file")
                if out:
                    known_outputs.add(os.path.abspath(out.lstrip("/")))
                # Also keep SRT files for active subtitle jobs
                job_id = job.get("id", "")
                known_outputs.add(os.path.abspath(os.path.join(OUTPUT_DIR, f"subtitle_{job_id}.srt")))

        # Clean orphan uploads
        if os.path.isdir(UPLOAD_DIR):
            for fname in os.listdir(UPLOAD_DIR):
                fpath = os.path.join(UPLOAD_DIR, fname)
                if os.path.isfile(fpath) and fpath not in known_inputs:
                    try:
                        os.remove(fpath)
                        removed["uploads"] += 1
                    except OSError:
                        pass

        # Clean orphan outputs
        if os.path.isdir(OUTPUT_DIR):
            for fname in os.listdir(OUTPUT_DIR):
                fpath = os.path.join(OUTPUT_DIR, fname)
                if os.path.isfile(fpath) and fpath not in known_outputs:
                    try:
                        os.remove(fpath)
                        removed["outputs"] += 1
                    except OSError:
                        pass

        return removed


# Global instance
job_manager = JobManager()
