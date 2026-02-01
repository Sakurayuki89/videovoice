import os
import re
from datetime import datetime
import asyncio
from concurrent.futures import ThreadPoolExecutor
from .stt import STTModule
from .translate import Translator
from .tts import TTSModule
from .ffmpeg import FFmpegModule
from .quality import QualityValidator

def _check_key_term_preservation(original: str, refined: str) -> list[str]:
    """Check if key terms (numbers, proper nouns, technical terms) survived refinement.
    Returns list of lost terms. Empty list = OK."""
    import re as _re
    lost = []

    # Extract numbers and percentages
    orig_numbers = set(_re.findall(r'\d+[\.,]?\d*%?', original))
    refined_numbers = set(_re.findall(r'\d+[\.,]?\d*%?', refined))
    for n in orig_numbers:
        if n not in refined_numbers:
            lost.append(f"number:{n}")

    # Extract capitalized words (proper nouns, abbreviations) — 2+ chars
    orig_caps = set(_re.findall(r'\b[A-Z][A-Za-z]{1,}\b', original))
    refined_caps = set(_re.findall(r'\b[A-Z][A-Za-z]{1,}\b', refined))
    for term in orig_caps:
        if term not in refined_caps:
            lost.append(f"term:{term}")

    # If more than 30% of key terms are lost, flag it
    total = len(orig_numbers) + len(orig_caps)
    if total > 0 and len(lost) / total > 0.3:
        return lost
    return []


# Allowed directories for input/output files
UPLOAD_DIR = os.path.abspath("static/uploads")
OUTPUT_DIR = os.path.abspath("static/outputs")


class PipelineCancelledException(Exception):
    """Raised when a pipeline job is cancelled."""
    pass


def get_engine_value(settings, field: str, default: str) -> str:
    """Safely extract engine value from settings, handling both enum and string types."""
    value = getattr(settings, field, default)
    return value.value if hasattr(value, 'value') else value



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
            stt_engine = get_engine_value(job.settings, 'stt_engine', 'local')
            log(f"Transcribing audio (engine: {stt_engine})...")

            stt = STTModule(engine=stt_engine)
            source_lang = job.settings.source_lang if job.settings.source_lang != 'auto' else None
            
            # Run blocking STT call in thread with timeout
            from ..config import STT_TIMEOUT
            try:
                text = await asyncio.wait_for(
                    asyncio.to_thread(stt.transcribe, temp_audio, language=source_lang),
                    timeout=STT_TIMEOUT
                )
            except asyncio.TimeoutError:
                raise PipelineStepError("transcribe", f"STT timed out after {STT_TIMEOUT} seconds")

            # Handle empty transcription
            if not text or not text.strip():
                log("WARNING: No speech detected in audio")
                raise PipelineStepError("transcribe", "No speech detected in the audio.")

            log(f"Transcribed {len(text)} characters")
            log(f"Preview: {text[:100]}...")
            job_manager.update_step(job_id, "transcribe", "done")
            job_manager.update_progress(job_id, 40)

            self._check_cancelled(job_id, job_manager)

            # Step 3: Translate (with cache)
            current_step = "translate"
            job_manager.update_step(job_id, "translate", "processing")
            sync_mode = getattr(job.settings, 'sync_mode', 'optimize')
            translation_engine = get_engine_value(job.settings, 'translation_engine', 'local')
            log(f"Translating to {job.settings.target_lang}... (sync_mode: {sync_mode}, engine: {translation_engine})")

            translator = Translator()

            # Initialize translation cache
            from ..config import TRANSLATION_CACHE_ENABLED, CACHE_DIR, CACHE_EXPIRATION_DAYS
            from .translation_cache import TranslationCache
            cache = TranslationCache(CACHE_DIR, CACHE_EXPIRATION_DAYS) if TRANSLATION_CACHE_ENABLED else None

            quality_result = None
            cache_hit = False

            # Skip translation if source and target are the same
            if job.settings.source_lang == job.settings.target_lang:
                log("Source and target languages are the same, skipping translation")
                translated_text = text
            else:
                # Check cache first
                CACHE_MIN_QUALITY = 60  # Discard cached translations below this score
                cached = cache.get(text, job.settings.source_lang, job.settings.target_lang, sync_mode) if cache else None
                if cached:
                    cached_quality = cached.get("quality_result")
                    cached_score = cached_quality.get("overall_score", 0) if cached_quality else None

                    if cached_score is not None and cached_score < CACHE_MIN_QUALITY:
                        # Low quality cache — discard and re-translate
                        log(f"Cache hit but quality too low ({cached_score}%) — re-translating")
                        if cache:
                            cache.invalidate(text, job.settings.source_lang, job.settings.target_lang, sync_mode)
                        cached = None
                    else:
                        translated_text = cached["translated_text"]
                        quality_result = cached_quality
                        cache_hit = True
                        log(f"Cache hit — using cached translation ({len(translated_text)} chars)")
                        if cached_quality:
                            log(f"Cached Quality Score: {cached_score}%")

                if not cached and not (job.settings.source_lang == job.settings.target_lang):
                    # Run blocking translation call in thread
                    translated_text = await asyncio.to_thread(
                        translator.translate, text, job.settings.source_lang, job.settings.target_lang, sync_mode, translation_engine
                    )

            # Handle empty translation
            if not translated_text or not translated_text.strip():
                raise PipelineStepError("translate", "Translation returned empty result.")

            log(f"Translated {len(translated_text)} characters")
            log(f"Preview: {translated_text[:100]}...")
            job_manager.update_step(job_id, "translate", "done")
            job_manager.update_progress(job_id, 55)

            self._check_cancelled(job_id, job_manager)

            # Step 3.5: Quality Validation (Optional) + Auto-Refinement with Quality Gate
            MIN_QUALITY_SCORE = 85  # Minimum score to proceed
            MAX_QUALITY_RETRIES = 3  # Max translate→evaluate→refine cycles

            if cache_hit and quality_result:
                score = quality_result.get("overall_score", 0)
                if score >= MIN_QUALITY_SCORE:
                    job_manager.set_quality_result(job_id, quality_result)
                    job_manager.update_progress(job_id, 60)
                    log(f"Cache hit with acceptable quality ({score}%)")
                else:
                    log(f"Cache hit but quality too low ({score}%) — will re-validate")
                    cache_hit = False
                    quality_result = None

            if not cache_hit and job.settings.verify_translation:
                log("Evaluating translation quality (Gemini API)...")
                try:
                    validator = QualityValidator()
                    best_text = translated_text
                    best_score = 0
                    best_quality = None

                    for qi in range(MAX_QUALITY_RETRIES):
                        self._check_cancelled(job_id, job_manager)

                        # Evaluate current translation
                        quality_result = await asyncio.to_thread(
                            validator.evaluate,
                            text, best_text,
                            job.settings.source_lang, job.settings.target_lang
                        )

                        score = quality_result.get("overall_score", 0)
                        recommendation = quality_result.get("recommendation", "REVIEW_NEEDED")
                        issues = quality_result.get("issues", [])
                        log(f"Quality round {qi+1}/{MAX_QUALITY_RETRIES}: {score}% ({recommendation})")

                        # Track best result
                        if score > best_score:
                            best_score = score
                            best_quality = quality_result
                            best_text_at_best = best_text

                        # Good enough — stop
                        if score >= MIN_QUALITY_SCORE:
                            log(f"Quality target reached ({score}% >= {MIN_QUALITY_SCORE}%)")
                            break

                        # Last retry — don't refine, just use best
                        if qi == MAX_QUALITY_RETRIES - 1:
                            log(f"Max retries reached. Using best result ({best_score}%)")
                            break

                        # Refine translation
                        if issues:
                            log(f"Score {score}% < {MIN_QUALITY_SCORE}% — refining (round {qi+2})...")
                            refined_text = await asyncio.to_thread(
                                translator.refine,
                                text, best_text,
                                job.settings.source_lang, job.settings.target_lang,
                                issues, sync_mode, translation_engine
                            )
                            if refined_text and refined_text.strip() and refined_text != best_text:
                                # Check refinement didn't truncate (shorter by >50% is suspicious)
                                if len(refined_text) < len(best_text) * 0.5:
                                    log(f"Refinement too short ({len(refined_text)} vs {len(best_text)} chars) — keeping previous")
                                else:
                                    # Check key term preservation
                                    lost = _check_key_term_preservation(best_text, refined_text)
                                    if lost:
                                        log(f"Refinement lost key terms: {', '.join(lost[:5])} — keeping previous")
                                    else:
                                        best_text = refined_text
                                        log(f"Refined: {len(best_text)} chars")
                            else:
                                # Refinement failed — try full re-translation
                                log("Refinement returned same/empty — re-translating from scratch")
                                retranslated = await asyncio.to_thread(
                                    translator.translate, text,
                                    job.settings.source_lang, job.settings.target_lang,
                                    sync_mode, translation_engine
                                )
                                if retranslated and retranslated.strip():
                                    best_text = retranslated
                                    log(f"Re-translated: {len(best_text)} chars")

                    # Use the best result across all rounds
                    if best_score > score:
                        translated_text = best_text_at_best
                        quality_result = best_quality
                        log(f"Using best result from earlier round ({best_score}%)")
                    else:
                        translated_text = best_text

                    job_manager.set_quality_result(job_id, quality_result)

                    # Only cache if quality is acceptable
                    if cache and job.settings.source_lang != job.settings.target_lang:
                        cache.put(text, job.settings.source_lang, job.settings.target_lang,
                                  sync_mode, translated_text, quality_result)
                        log(f"Translation cached (score: {quality_result.get('overall_score', 0)}%)")
                except Exception as e:
                    log(f"Quality validation failed: {e} (continuing anyway)")
                job_manager.update_progress(job_id, 60)
            else:
                # No quality validation, still cache the translation
                if cache and job.settings.source_lang != job.settings.target_lang and not cache_hit:
                    cache.put(text, job.settings.source_lang, job.settings.target_lang,
                              sync_mode, translated_text)
                    log("Translation cached to disk")
                job_manager.update_progress(job_id, 60)

            self._check_cancelled(job_id, job_manager)

            # Step 4: TTS
            current_step = "tts"
            job_manager.update_step(job_id, "tts", "processing")

            # Resolve TTS engine
            tts_engine = get_engine_value(job.settings, 'tts_engine', 'auto')
            clone_voice = getattr(job.settings, 'clone_voice', True)


            if tts_engine == "auto":
                from ..config import TTS_AUTO_SELECT, ELEVENLABS_API_KEY
                if ELEVENLABS_API_KEY:
                    tts_engine = "elevenlabs"
                elif clone_voice:
                    tts_engine = "xtts"
                else:
                    tts_engine = TTS_AUTO_SELECT.get(job.settings.target_lang, "edge")

            log(f"Generating Speech ({tts_engine.upper()}, clone_voice={clone_voice})...")
            tts = TTSModule(engine=tts_engine)

            # Use extracted audio as speaker reference for voice cloning
            speaker_ref = temp_audio

            # Edge TTS is natively async; others run in thread
            if tts_engine == "edge":
                await tts.generate_async(
                    translated_text, speaker_ref, output_wav,
                    language=job.settings.target_lang
                )
            else:
                await asyncio.to_thread(
                    tts.generate, translated_text, speaker_ref, output_wav,
                    language=job.settings.target_lang
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
