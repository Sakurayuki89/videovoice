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
from .subtitle import generate_srt, translate_segments, burn_subtitles

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

    async def _process_subtitle(self, job_id: str, job, input_path: str, job_manager, log):
        """Subtitle-only pipeline: Extract → STT (segments) → Translate → SRT → Burn-in."""
        temp_audio = os.path.join(UPLOAD_DIR, f"{job_id}_temp.wav")
        srt_path = os.path.join(OUTPUT_DIR, f"subtitle_{job_id}.srt")
        output_video = os.path.join(OUTPUT_DIR, f"subtitle_{job_id}.mp4")
        output_url = f"/static/outputs/subtitle_{job_id}.mp4"

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        current_step = "extract"

        try:
            # Step 1: Extract audio (20%)
            job_manager.update_step(job_id, "extract", "processing")
            log("영상에서 오디오를 추출하는 중...")
            success = await asyncio.to_thread(self.ffmpeg.extract_audio, input_path, temp_audio)
            if not success:
                raise PipelineStepError("extract", "비디오에서 오디오 추출에 실패했습니다.")
            job_manager.update_step(job_id, "extract", "done")
            job_manager.update_progress(job_id, 20)

            self._check_cancelled(job_id, job_manager)

            # Step 2: Transcribe with segments (40%)
            current_step = "transcribe"
            job_manager.update_step(job_id, "transcribe", "processing")
            stt_engine = get_engine_value(job.settings, 'stt_engine', 'local')
            log(f"음성 인식 시작 (엔진: {stt_engine})... 오디오 길이에 따라 수 분 소요될 수 있습니다.")

            stt = STTModule(engine=stt_engine)
            source_lang = job.settings.source_lang if job.settings.source_lang != 'auto' else None

            from ..config import STT_TIMEOUT
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(stt.transcribe, temp_audio, language=source_lang, with_segments=True),
                    timeout=STT_TIMEOUT
                )
            except asyncio.TimeoutError:
                raise PipelineStepError("transcribe", f"음성 인식이 {STT_TIMEOUT}초 후 시간 초과되었습니다.")

            text = result["text"] if isinstance(result, dict) else result
            segments = result.get("segments", []) if isinstance(result, dict) else []

            if not text or not text.strip():
                raise PipelineStepError("transcribe", "오디오에서 음성이 감지되지 않았습니다.")
            if not segments:
                raise PipelineStepError("transcribe", "STT에서 타임스탬프 세그먼트가 반환되지 않았습니다. 자막 모드에는 타임스탬프 데이터가 필요합니다.")

            log(f"Transcribed {len(text)} chars, {len(segments)} segments")
            job_manager.update_step(job_id, "transcribe", "done")
            job_manager.update_progress(job_id, 40)

            # Critical Fix: Clear VRAM after STT to free memory before translation
            from .utils.vram import clear_vram
            clear_vram("Subtitle-STT-to-Translate")

            self._check_cancelled(job_id, job_manager)

            # Step 3: Translate segments (60%)
            current_step = "translate"
            job_manager.update_step(job_id, "translate", "processing")
            translation_engine = get_engine_value(job.settings, 'translation_engine', 'gemini')
            
            # Warn if using local translation with many segments (slow)
            # Local translation is recommended only for videos under 5 minutes (~60 segments)
            if translation_engine == "local" and len(segments) > 60:
                log(f"⚠️ Warning: Local translation with {len(segments)} segments will be slow. Recommended for videos under 5 minutes only.")
            
            log(f"Translating {len(segments)} segments to {job.settings.target_lang} (engine: {translation_engine})...")

            translator = Translator()
            from ..config import TRANSLATION_TIMEOUT
            
            # Progress callback for incremental updates during translation
            def translation_progress(current_chunk, total_chunks):
                # Map translation progress to 40% → 60% range
                progress = 40 + int((current_chunk / total_chunks) * 20)
                job_manager.update_progress(job_id, progress)
            
            try:
                translated_segments, success_rate = await asyncio.wait_for(
                    asyncio.to_thread(
                        translate_segments, segments, translator,
                        job.settings.source_lang, job.settings.target_lang, translation_engine,
                        progress_callback=translation_progress
                    ),
                    timeout=TRANSLATION_TIMEOUT
                )
            except asyncio.TimeoutError:
                raise PipelineStepError("translate", f"번역이 {TRANSLATION_TIMEOUT}초 후 시간 초과되었습니다.")
            log(f"Translation complete ({len(translated_segments)} segments, {success_rate:.0f}% success)")

            # Quality gate: retry failed segments if success rate is below threshold
            from ..config import SUBTITLE_MIN_SUCCESS_RATE
            if success_rate < SUBTITLE_MIN_SUCCESS_RATE:
                log(f"⚠️ Success rate {success_rate:.0f}% < {SUBTITLE_MIN_SUCCESS_RATE}% — retrying failed segments...")
                # Identify failed segments (text unchanged from original)
                failed_indices = []
                for i, (orig, trans) in enumerate(zip(segments, translated_segments)):
                    if orig["text"].strip() and orig["text"].strip() == trans["text"].strip():
                        failed_indices.append(i)
                if failed_indices:
                    log(f"Retrying {len(failed_indices)} failed segments individually...")
                    for idx in failed_indices:
                        try:
                            # #4 Fix: Use job's sync_mode instead of hardcoded "optimize"
                            result = await asyncio.to_thread(
                                translator.translate,
                                segments[idx]["text"], job.settings.source_lang,
                                job.settings.target_lang, job.settings.sync_mode, translation_engine
                            )
                            if result and result.strip():
                                translated_segments[idx]["text"] = result.strip()
                        except Exception as e:
                            log(f"Retry failed for segment {idx}: {e}")
                    retried_ok = sum(1 for i in failed_indices if segments[i]["text"].strip() != translated_segments[i]["text"].strip())
                    log(f"Retry recovered {retried_ok}/{len(failed_indices)} segments")
            job_manager.update_step(job_id, "translate", "done")
            job_manager.update_progress(job_id, 60)

            self._check_cancelled(job_id, job_manager)

            # Step 3.5: Quality Validation (if enabled)
            if job.settings.verify_translation:
                log("Evaluating translation quality (Gemini API)...")
                try:
                    validator = QualityValidator()
                    # Combine all segments for quality evaluation
                    original_text = " ".join(seg["text"] for seg in segments if seg.get("text"))
                    translated_text = " ".join(seg["text"] for seg in translated_segments if seg.get("text"))
                    
                    quality_result = await asyncio.to_thread(
                        validator.evaluate,
                        original_text, translated_text,
                        job.settings.source_lang, job.settings.target_lang
                    )
                    
                    score = quality_result.get("overall_score", 0)
                    recommendation = quality_result.get("recommendation", "REVIEW_NEEDED")
                    log(f"Subtitle quality evaluation: {score}% ({recommendation})")
                    
                    job_manager.set_quality_result(job_id, quality_result)
                except Exception as e:
                    log(f"Quality evaluation failed (non-critical): {e}")
                    # Non-blocking: continue even if quality check fails
            
            job_manager.update_progress(job_id, 65)
            self._check_cancelled(job_id, job_manager)

            # Step 4: Generate SRT (70%)
            current_step = "subtitle"
            job_manager.update_step(job_id, "subtitle", "processing")
            log("Generating SRT subtitle file...")
            await asyncio.to_thread(generate_srt, translated_segments, srt_path)
            log(f"SRT file created: {srt_path}")
            job_manager.update_step(job_id, "subtitle", "done")
            job_manager.update_progress(job_id, 70)

            self._check_cancelled(job_id, job_manager)

            # Step 5: Embed subtitles into video (90%)
            current_step = "burn"
            job_manager.update_step(job_id, "burn", "processing")
            
            # Use soft subtitles (very fast: ~1 second) by default
            # Falls back to burn-in (slow: 20+ minutes) if soft embed fails
            from .subtitle import embed_soft_subtitles
            log("Embedding soft subtitles (instant, toggleable in player)...")
            try:
                success = await asyncio.wait_for(
                    asyncio.to_thread(embed_soft_subtitles, input_path, srt_path, output_video, job.settings.target_lang),
                    timeout=60  # Soft embed should only take seconds
                )
                if not success:
                    raise Exception("Soft subtitle embedding returned False")
            except Exception as soft_err:
                # Fallback: burn subtitles (slower but more compatible)
                log(f"Soft embed failed ({soft_err}), falling back to burn-in (slower)...")
                from ..config import FFMPEG_TIMEOUT
                try:
                    success = await asyncio.wait_for(
                        asyncio.to_thread(burn_subtitles, input_path, srt_path, output_video),
                        timeout=FFMPEG_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    raise PipelineStepError("burn", f"자막 삽입이 {FFMPEG_TIMEOUT}초 후 시간 초과되었습니다.")
                if not success:
                    raise PipelineStepError("burn", "비디오에 자막 삽입에 실패했습니다.")

            if not os.path.exists(output_video) or os.path.getsize(output_video) == 0:
                raise PipelineStepError("burn", "출력 비디오가 올바르게 생성되지 않았습니다.")

            job_manager.update_step(job_id, "burn", "done")
            job_manager.update_progress(job_id, 100)

            job_manager.set_output_file(job_id, output_url)
            job_manager.set_completed(job_id)
            log("Subtitle processing complete!")

        except PipelineCancelledException:
            log("Job cancelled by user")
            job_manager.update_step(job_id, current_step, "failed")

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
            self._cleanup_temp_files(temp_audio)
            # Clean up upload file after subtitle pipeline finishes
            self._cleanup_temp_files(input_path)

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

        # Determine mode
        job_mode = get_engine_value(job.settings, 'mode', 'dubbing')

        try:
            job_manager.update_status(job_id, "processing")

            # Check for cancellation before starting
            self._check_cancelled(job_id, job_manager)

            # ===== SUBTITLE MODE =====
            if job_mode == "subtitle":
                await self._process_subtitle(job_id, job, input_path, job_manager, log)
                return

            # ===== DUBBING MODE (original pipeline) =====
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
                    raise PipelineStepError("extract", "비디오에서 오디오 추출에 실패했습니다.")
                
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
                raise PipelineStepError("transcribe", f"음성 인식이 {STT_TIMEOUT}초 후 시간 초과되었습니다.")

            # Handle empty transcription
            if not text or not text.strip():
                log("WARNING: No speech detected in audio")
                raise PipelineStepError("transcribe", "오디오에서 음성이 감지되지 않았습니다.")

            log(f"Transcribed {len(text)} characters")
            log(f"Preview: {text[:100]}...")
            job_manager.update_step(job_id, "transcribe", "done")
            job_manager.update_progress(job_id, 40)

            # #1 Fix: Clear VRAM after STT to free memory before TTS
            from .utils.vram import clear_vram
            clear_vram("STT-to-TTS")

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
                    from ..config import TRANSLATION_TIMEOUT
                    try:
                        translated_text = await asyncio.wait_for(
                            asyncio.to_thread(
                                translator.translate, text, job.settings.source_lang, job.settings.target_lang, sync_mode, translation_engine
                            ),
                            timeout=TRANSLATION_TIMEOUT
                        )
                    except asyncio.TimeoutError:
                        raise PipelineStepError("translate", f"번역이 {TRANSLATION_TIMEOUT}초 후 시간 초과되었습니다.")

            # Handle empty translation
            if not translated_text or not translated_text.strip():
                raise PipelineStepError("translate", "번역 결과가 비어 있습니다.")

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
                    best_text_at_best = translated_text  # #3 Fix: Initialize to prevent NameError

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
                raise PipelineStepError("tts", "TTS 음성 생성에 실패했습니다.")

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
                    raise PipelineStepError("merge", "오디오와 비디오 병합에 실패했습니다.")

                # Verify final output
                if not os.path.exists(output_video) or os.path.getsize(output_video) == 0:
                    raise PipelineStepError("merge", "최종 비디오 파일이 올바르게 생성되지 않았습니다.")

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
            # Clean up temporary files
            if is_audio_input:
                # #1 Fix: Don't delete output_wav for audio input (it's the final output)
                pass
            else:
                self._cleanup_temp_files(temp_audio, output_wav)
            # Clean up upload file after pipeline finishes
            self._cleanup_temp_files(input_path)


# Global
pipeline = Pipeline()
