import os
import re
from datetime import datetime
import asyncio
from concurrent.futures import ThreadPoolExecutor
from .stt import STTModule
from .translate import Translator
from .tts import XTTSModule
from .ffmpeg import FFmpegModule
from .quality import QualityValidator

# Allowed directories for input/output files
UPLOAD_DIR = os.path.abspath("static/uploads")
OUTPUT_DIR = os.path.abspath("static/outputs")


class PipelineCancelledException(Exception):
    """Raised when a pipeline job is cancelled."""
    pass


class PipelineStepError(Exception):
    """Raised when a pipeline step fails with context."""
    def __init__(self, step: str, message: str):
        self.step = step
        self.message = message
        super().__init__(f"[{step}] {message}")


class Pipeline:
    def __init__(self):
        self.ffmpeg = FFmpegModule()

    def _validate_input_path(self, input_path: str) -> bool:
        """Validate that input path is within the allowed upload directory."""
        if not input_path:
            return False
        abs_path = os.path.abspath(input_path)
        return abs_path.startswith(UPLOAD_DIR) and os.path.isfile(abs_path)

    def _sanitize_job_id(self, job_id: str) -> str:
        """Ensure job_id only contains safe characters."""
        return re.sub(r'[^a-zA-Z0-9\-]', '', job_id)

    def _cleanup_temp_files(self, *paths):
        """Clean up temporary files."""
        for path in paths:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass  # Ignore cleanup errors

    def _check_cancelled(self, job_id: str, job_manager) -> None:
        """Check if job has been cancelled and raise if so."""
        if job_manager.is_cancelled(job_id):
            raise PipelineCancelledException("Job was cancelled by user")

    async def process_job(self, job_id: str):
        from ..web.manager import job_manager

        # Sanitize job_id
        safe_job_id = self._sanitize_job_id(job_id)
        if safe_job_id != job_id:
            print(f"Invalid job_id format: {job_id}")
            return

        job = job_manager.get_job(job_id)
        if not job:
            print(f"Job {job_id} not found")
            return

        # Get input file path from manager (not from response object)
        input_path = job_manager.get_input_file(job_id)

        # Validate input path is within allowed directory
        if not self._validate_input_path(input_path):
            job_manager.update_status(job_id, "failed", error="Invalid input file path")
            print(f"Security: Invalid input path for job {job_id}: {input_path}")
            return

        # Get input type (audio or video)
        input_type = job_manager.get_input_type(job_id)
        is_audio_input = (input_type == "audio")

        # Use job_id in temp file names to avoid collisions
        temp_audio = os.path.join(UPLOAD_DIR, f"{job_id}_temp.wav")
        output_wav = os.path.join(OUTPUT_DIR, f"dubbed_{job_id}.wav")
        output_video = os.path.join(OUTPUT_DIR, f"dubbed_{job_id}.mp4")
        
        # Output URL depends on input type
        if is_audio_input:
            output_url = f"/static/outputs/dubbed_{job_id}.wav"
        else:
            output_url = f"/static/outputs/dubbed_{job_id}.mp4"

        os.makedirs(OUTPUT_DIR, exist_ok=True)

        current_step = "init"

        def log(msg):
            print(f"[Job {job_id}] {msg}")
            job_manager.append_log(job_id, msg)

        try:
            job_manager.update_status(job_id, "processing")

            # Check for cancellation before starting
            self._check_cancelled(job_id, job_manager)

            # Step 1: Extract (skip for audio input)
            # Step 1: Extract (skip for audio input)
            if is_audio_input:
                log("Audio input detected - skipping extraction step")
                # Use input audio file directly
                temp_audio = input_path
                job_manager.update_progress(job_id, 10)
            else:
                current_step = "extract"
                job_manager.update_step(job_id, "extract", "processing")
                log("Extracting audio from video...")
                
                # Run blocking FFmpeg call in thread
                success = await asyncio.to_thread(self.ffmpeg.extract_audio, input_path, temp_audio)
                if not success:
                    raise PipelineStepError("extract", "Failed to extract audio from video.")
                
                job_manager.update_step(job_id, "extract", "done")
                job_manager.update_progress(job_id, 20)

            self._check_cancelled(job_id, job_manager)

            # Step 2: Transcribe
            current_step = "transcribe"
            job_manager.update_step(job_id, "transcribe", "processing")
            log("Transcribing audio (WhisperX)...")
            stt = STTModule()
            source_lang = job.settings.source_lang if job.settings.source_lang != 'auto' else None
            
            # Run blocking STT call in thread
            text = await asyncio.to_thread(stt.transcribe, temp_audio, language=source_lang)

            # Handle empty transcription
            if not text or not text.strip():
                log("WARNING: No speech detected in audio")
                raise PipelineStepError("transcribe", "No speech detected in the audio.")

            log(f"Transcribed {len(text)} characters")
            log(f"Preview: {text[:100]}...")
            job_manager.update_step(job_id, "transcribe", "done")
            job_manager.update_progress(job_id, 40)

            self._check_cancelled(job_id, job_manager)

            # Step 3: Translate
            current_step = "translate"
            job_manager.update_step(job_id, "translate", "processing")
            sync_mode = getattr(job.settings, 'sync_mode', 'optimize')
            log(f"Translating to {job.settings.target_lang}... (sync_mode: {sync_mode})")
            translator = Translator()

            # Skip translation if source and target are the same
            if job.settings.source_lang == job.settings.target_lang:
                log("Source and target languages are the same, skipping translation")
                translated_text = text
            else:
                # Run blocking translation call in thread
                # Pass sync_mode to control translation length
                translated_text = await asyncio.to_thread(
                    translator.translate, text, job.settings.source_lang, job.settings.target_lang, sync_mode
                )

            # Handle empty translation
            if not translated_text or not translated_text.strip():
                raise PipelineStepError("translate", "Translation returned empty result.")

            log(f"Translated {len(translated_text)} characters")
            log(f"Preview: {translated_text[:100]}...")
            job_manager.update_step(job_id, "translate", "done")
            job_manager.update_progress(job_id, 55)

            self._check_cancelled(job_id, job_manager)

            # Step 3.5: Quality Validation (Optional)
            if job.settings.verify_translation:
                log("Evaluating translation quality (Gemini API)...")
                try:
                    validator = QualityValidator()
                    
                    # Run blocking validation in thread
                    quality_result = await asyncio.to_thread(
                        validator.evaluate,
                        text,
                        translated_text,
                        job.settings.source_lang,
                        job.settings.target_lang
                    )
                    
                    job_manager.set_quality_result(job_id, quality_result)
                    score = quality_result.get("overall_score", 0)
                    recommendation = quality_result.get("recommendation", "REVIEW_NEEDED")
                    log(f"Quality Score: {score}% ({recommendation})")
                    if quality_result.get("issues"):
                        log(f"Issues: {', '.join(quality_result['issues'][:3])}")
                except Exception as e:
                    log(f"Quality validation failed: {e} (continuing anyway)")
                job_manager.update_progress(job_id, 60)
            else:
                job_manager.update_progress(job_id, 60)

            self._check_cancelled(job_id, job_manager)

            # Step 4: TTS
            current_step = "tts"
            job_manager.update_step(job_id, "tts", "processing")
            log("Generating Speech (XTTS)...")
            tts = XTTSModule()

            # Use extracted audio as speaker reference for voice cloning
            speaker_ref = temp_audio  # Always use original audio as reference

            # Run blocking TTS call in thread
            await asyncio.to_thread(
                tts.generate, translated_text, speaker_ref, output_wav, language=job.settings.target_lang
            )

            # Verify TTS output
            if not os.path.exists(output_wav) or os.path.getsize(output_wav) == 0:
                raise PipelineStepError("tts", "TTS failed to generate audio output.")

            job_manager.update_step(job_id, "tts", "done")
            job_manager.update_progress(job_id, 80)

            self._check_cancelled(job_id, job_manager)

            # Step 5: Merge (skip for audio input)
            if is_audio_input:
                log("Audio input - skipping merge step, outputting audio only")
                # For audio input, the output_wav is the final output
                # Copy/move to final output location (already at output_wav)
                import shutil
                final_audio_output = os.path.join(OUTPUT_DIR, f"dubbed_{job_id}.wav")
                if output_wav != final_audio_output:
                    try:
                        shutil.copy2(output_wav, final_audio_output)
                    except Exception as e:
                        log(f"Warning: Failed to copy output file: {e}")
                job_manager.update_progress(job_id, 100)
            else:
                current_step = "merge"
                job_manager.update_step(job_id, "merge", "processing")

                # Choose merge method based on sync_mode
                sync_mode = getattr(job.settings, 'sync_mode', 'optimize')

                if sync_mode == "stretch":
                    log("Merging audio and video (stretch mode - extending video if needed)...")
                    success = await asyncio.to_thread(
                        self.ffmpeg.extend_video_to_audio, input_path, output_wav, output_video
                    )
                elif sync_mode == "speed_audio":
                    log("Merging audio and video (speed_audio mode - adjusting audio speed)...")
                    success = await asyncio.to_thread(
                        self.ffmpeg.speed_audio_to_video, input_path, output_wav, output_video
                    )
                else:
                    log("Merging audio and video (optimize mode - standard merge)...")
                    success = await asyncio.to_thread(
                        self.ffmpeg.merge_video, input_path, output_wav, output_video
                    )

                if not success:
                    raise PipelineStepError("merge", "Failed to merge audio with video.")

                # Verify final output
                if not os.path.exists(output_video) or os.path.getsize(output_video) == 0:
                    raise PipelineStepError("merge", "Final video file was not created properly.")

                job_manager.update_step(job_id, "merge", "done")
                job_manager.update_progress(job_id, 100)

            # Set output file URL and mark as completed
            job_manager.set_output_file(job_id, output_url)
            job_manager.set_completed(job_id)
            log("Processing Complete!")

        except PipelineCancelledException:
            log("Job cancelled by user")
            job_manager.update_step(job_id, current_step, "failed")
            # Status already set to cancelled by cancel_job()

        except PipelineStepError as e:
            log(f"Step '{e.step}' failed: {e.message}")
            job_manager.update_step(job_id, e.step, "failed")
            job_manager.update_status(job_id, "failed", error=e.message)

        except Exception as e:
            error_msg = f"Unexpected error in '{current_step}': {str(e)}"
            log(error_msg)
            job_manager.update_step(job_id, current_step, "failed")
            job_manager.update_status(job_id, "failed", error=error_msg)
            import traceback
            traceback.print_exc()

        finally:
            # Clean up temporary files (but don't delete input audio file)
            if is_audio_input:
                # For audio input, temp_audio is the input file, don't delete it
                self._cleanup_temp_files(output_wav)
            else:
                self._cleanup_temp_files(temp_audio, output_wav)


# Global
pipeline = Pipeline()
