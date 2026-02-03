import requests
import time
import re

from ..config import (
    OLLAMA_HOST as DEFAULT_OLLAMA_HOST,
    OLLAMA_MODEL as DEFAULT_OLLAMA_MODEL,
    OLLAMA_TIMEOUT as DEFAULT_OLLAMA_TIMEOUT,
    GROQ_API_KEY,
    GROQ_MODEL,
    GEMINI_API_KEY,
    GEMINI_MODEL,
)
from .utils.llm import GeminiQuotaError, is_quota_error

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Full language name mapping
LANGUAGE_NAMES = {
    "en": "English",
    "ko": "Korean",
    "ja": "Japanese",
    "zh": "Chinese",
    "ru": "Russian",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "pl": "Polish",
    "tr": "Turkish",
    "vi": "Vietnamese",
    "th": "Thai",
    "ar": "Arabic",
    "hi": "Hindi",
    "auto": "detected language",
}


class Translator:
    # Maximum text length to prevent resource exhaustion
    MAX_TEXT_LENGTH = 50000

    def __init__(self, model: str = None, host: str = None, timeout: int = None):
        self.model = model or DEFAULT_OLLAMA_MODEL
        self.host = host or DEFAULT_OLLAMA_HOST
        self.timeout = timeout or DEFAULT_OLLAMA_TIMEOUT

    def strip_think_tags(self, text):
        cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        return cleaned.strip()

    def sanitize_input(self, text: str) -> str:
        """
        Sanitize input text to mitigate prompt injection attacks.
        - Removes potential instruction-like patterns
        - Escapes special markers
        - Truncates to maximum length
        """
        if not text:
            return ""

        # Truncate to maximum length
        text = text[:self.MAX_TEXT_LENGTH]

        # Remove or escape patterns that could be used for prompt injection
        # Remove markdown code blocks that might contain instructions
        text = re.sub(r'```[\s\S]*?```', '[code block removed]', text)

        # Escape common prompt injection patterns
        injection_patterns = [
            (r'(?i)ignore\s+(all\s+)?(previous|above)\s+instructions?', '[filtered]'),
            (r'(?i)disregard\s+(all\s+)?(previous|above)', '[filtered]'),
            (r'(?i)new\s+instructions?:', '[filtered]'),
            (r'(?i)system\s*:', '[filtered]'),
            (r'(?i)assistant\s*:', '[filtered]'),
            (r'(?i)user\s*:', '[filtered]'),
        ]

        for pattern, replacement in injection_patterns:
            text = re.sub(pattern, replacement, text)

        return text.strip()

    def _call_groq(self, prompt: str, system_prompt: str = None) -> str:
        """Call Groq API (OpenAI-compatible) and return the response text."""
        if not GROQ_API_KEY:
            raise Exception("GROQ_API_KEY가 설정되지 않았습니다. .env 파일에 설정해주세요.")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = requests.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": GROQ_MODEL,
                "messages": messages,
                "temperature": 0.3
            },
            timeout=self.timeout
        )

        # #9 Fix: Handle Groq rate limit errors explicitly
        if response.status_code == 429:
            raise Exception(f"Groq API 요청 한도 초과 (429). 'local' 또는 'gemini' 엔진을 사용해보세요.")
        if response.status_code != 200:
            raise Exception(f"Groq API 오류 ({response.status_code}): {response.text}")

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return self.strip_think_tags(content).strip()

    def _call_ollama(self, prompt: str) -> str:
        """Call Ollama API and return the response text."""
        response = requests.post(
            f"{self.host}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False
            },
            timeout=self.timeout
        )

        if response.status_code != 200:
            raise Exception(f"Ollama 오류 ({response.status_code}): {response.text}")

        raw = response.json().get('response', '')
        cleaned = self.strip_think_tags(raw)
        if not cleaned:
            raise Exception("Ollama가 빈 응답을 반환했습니다")
        return cleaned

    def _call_gemini(self, prompt: str, system_prompt: str = None) -> str:
        """Call Gemini API and return the response text. Raises GeminiQuotaError on 429."""
        if not GEMINI_API_KEY:
            raise Exception("GEMINI_API_KEY가 설정되지 않았습니다. .env 파일에 설정해주세요.")

        try:
            import google.generativeai as genai
        except ImportError:
            raise Exception("google-generativeai 패키지가 설치되지 않았습니다. pip install google-generativeai")

        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(
            GEMINI_MODEL,
            system_instruction=system_prompt if system_prompt else None,
        )

        try:
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.3,
                    max_output_tokens=8192,
                ),
                request_options={"timeout": 60}
            )
            text = response.text
            return self.strip_think_tags(text).strip()
        except Exception as e:
            if is_quota_error(e):
                raise GeminiQuotaError(f"Gemini API 할당량 초과: {e}")
            raise

    def _call_llm(self, prompt: str, engine: str = "local", system_prompt: str = None) -> str:
        """Route to the appropriate LLM backend."""
        if engine == "gemini":
            return self._call_gemini(prompt, system_prompt=system_prompt)
        if engine == "groq":
            return self._call_groq(prompt, system_prompt=system_prompt)
        return self._call_ollama(prompt)

    def _get_language_specific_instructions(self, target_lang: str, source_lang: str) -> str:
        """Return language-specific translation instructions."""
        instructions = []
        if target_lang == "ko":
            instructions.append("- Use natural spoken Korean (구어체). Maintain polite speech level (존댓말) unless the source is clearly casual.")
            if source_lang == "ja":
                instructions.append("- Preserve the honorific/politeness level from the Japanese source (경어 레벨 보존).")
            elif source_lang == "ru":
                instructions.append("- Translate Russian formal/informal register (ты/Вы) to matching Korean speech level (반말/존댓말).")
        elif target_lang == "ru":
            instructions.append("- Ensure correct grammatical case (격변화) and gender agreement (성별 일치) throughout.")
            if source_lang == "ko":
                instructions.append("- Map Korean speech levels (존댓말/반말) to appropriate Russian register (Вы/ты).")
            elif source_lang == "ja":
                instructions.append("- Map Japanese politeness levels (敬語/丁寧語/普通体) to appropriate Russian register (Вы/ты).")
        elif target_lang == "ja":
            instructions.append("- Use appropriate politeness level (敬語/丁寧語/普通体) matching the source tone.")
            if source_lang == "ko":
                instructions.append("- Map Korean speech levels (존댓말/반말) to matching Japanese politeness (丁寧語/普通体).")
        return "\n".join(instructions)

    # Max characters per chunk for chunked translation
    # Increased to prevent breaking subtitle batches and for modern LLM context windows
    CHUNK_THRESHOLD = 8000   # Split texts longer than this into chunks (used for dubbing long scripts)
    CHUNK_TARGET_SIZE = 6000 # Target size per chunk

    def _split_into_chunks(self, text: str) -> list[str]:
        """Split text into sentence-based chunks for better translation quality."""
        # Split by sentence-ending punctuation (Korean, English, etc.)
        sentences = re.split(r'(?<=[.!?。！？])\s+', text)

        chunks = []
        current_chunk = ""
        for sentence in sentences:
            if current_chunk and len(current_chunk) + len(sentence) > self.CHUNK_TARGET_SIZE:
                chunks.append(current_chunk.strip())
                current_chunk = sentence
            else:
                current_chunk = f"{current_chunk} {sentence}" if current_chunk else sentence

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks if chunks else [text]

    # Few-shot examples for common language pairs to anchor quality
    FEW_SHOT_EXAMPLES = {
        ("ko", "ru"): {
            "source": "이 증상이 계속되면 디스크가 바깥쪽으로 밀려나오게 됩니다.",
            "target": "Если эти симптомы будут продолжаться, диск начнёт выпячиваться наружу."
        },
        ("ko", "en"): {
            "source": "목을 숙이는 자세를 반복하면 섬유륜에 상처가 발생합니다.",
            "target": "Repeatedly tilting your head forward can cause damage to the annulus fibrosus."
        },
        ("en", "ko"): {
            "source": "Repeatedly tilting your head forward can cause damage to the annulus fibrosus.",
            "target": "목을 앞으로 숙이는 자세를 반복하면 섬유륜에 손상이 발생할 수 있습니다."
        },
        ("en", "ru"): {
            "source": "This condition is known as a herniated disc in the cervical spine.",
            "target": "Это состояние известно как грыжа межпозвоночного диска шейного отдела позвоночника."
        },
    }

    def _build_system_prompt(self, s_name: str, t_name: str, sync_mode: str, target_lang: str, source_lang: str) -> str:
        """Build system prompt for translation with optional few-shot example."""
        if sync_mode == "optimize":
            constraint = "Translate concisely. Preserve ALL meaning without unnecessary filler."
        else:
            constraint = "Translate COMPLETELY. Every sentence, detail, and nuance must be preserved. Do NOT summarize."

        lang_instructions = self._get_language_specific_instructions(target_lang, source_lang)
        lang_block = f"\n{lang_instructions}" if lang_instructions else ""

        # Add few-shot example if available
        example_block = ""
        example = self.FEW_SHOT_EXAMPLES.get((source_lang, target_lang))
        if example:
            example_block = f"""

EXAMPLE:
Input: {example['source']}
Output: {example['target']}"""

        return f"""You are a professional {s_name}-to-{t_name} video dubbing translator.

RULES:
- {constraint}
- Translate ALL medical/technical terms accurately.
- Keep the original speaker's perspective (1st person stays 1st person).
- Match the original tone (professional/casual/humorous).
- NEVER leave a sentence incomplete or cut off.
- Do NOT add explanations. Output ONLY the translation.{lang_block}{example_block}"""

    def translate(self, text: str, source_lang: str, target_lang: str, sync_mode: str = "optimize", engine: str = "local") -> str:
        if not text or not text.strip():
            return ""

        sanitized_text = self.sanitize_input(text)
        if not sanitized_text:
            return ""

        s_name = LANGUAGE_NAMES.get(source_lang, source_lang)
        t_name = LANGUAGE_NAMES.get(target_lang, target_lang)

        system_prompt = self._build_system_prompt(s_name, t_name, sync_mode, target_lang, source_lang)

        # For long texts, translate in chunks to prevent reordering/omissions
        if len(sanitized_text) > self.CHUNK_THRESHOLD:
            chunks = self._split_into_chunks(sanitized_text)
            print(f"[Translator] Long text ({len(sanitized_text)} chars) split into {len(chunks)} chunks")
            translated_chunks = []
            for i, chunk in enumerate(chunks):
                print(f"[Translator] Translating chunk {i+1}/{len(chunks)} ({len(chunk)} chars)")
                result = self._translate_chunk(chunk, system_prompt, engine)
                # Truncation check: translation should be at least 40% of source length
                if len(result) < len(chunk) * 0.4:
                    print(f"[Translator] WARNING: Chunk {i+1} may be truncated ({len(result)} vs {len(chunk)} source chars), retrying...")
                    result2 = self._translate_chunk(chunk, system_prompt, engine)
                    if len(result2) > len(result):
                        result = result2
                translated_chunks.append(result)
            return "\n".join(translated_chunks)
        else:
            return self._translate_chunk(sanitized_text, system_prompt, engine)

    def translate_raw(self, user_text: str, system_prompt: str, engine: str = "local") -> str:
        """Translate with explicit system prompt and user text (no wrapping).

        Used by subtitle batch translation where the prompt structure is pre-built.
        Auto-fallback from Gemini to Groq on quota error.
        """
        max_retries = 3
        current_engine = engine
        for attempt in range(1, max_retries + 1):
            try:
                result = self._call_llm(user_text, current_engine, system_prompt=system_prompt)
                if result:
                    return result
            except GeminiQuotaError:
                if GROQ_API_KEY:
                    current_engine = "groq"
                    continue
                raise
            except Exception as e:
                print(f"translate_raw error (attempt {attempt}): {e}")
            if attempt < max_retries:
                time.sleep(2 ** attempt)
        raise Exception("translate_raw가 재시도 후에도 실패했습니다")

    def _translate_chunk(self, text: str, system_prompt: str, engine: str) -> str:
        """Translate a single chunk of text. Auto-fallback from Gemini to Groq on quota error."""
        prompt = f"""Translate the following text:

<text>
{text}
</text>

Translation:"""

        max_retries = 3
        current_engine = engine

        for attempt in range(1, max_retries + 1):
            try:
                result = self._call_llm(prompt, current_engine, system_prompt=system_prompt)
                if result:
                    return result
                print(f"Translation attempt {attempt} returned empty")
            except GeminiQuotaError as e:
                print(f"[Translator] Gemini quota exceeded — falling back to Groq")
                if GROQ_API_KEY:
                    current_engine = "groq"
                    continue
                else:
                    print(f"[Translator] No Groq API key for fallback")
                    raise
            except Exception as e:
                print(f"Translation error (attempt {attempt}): {e}")

            if attempt < max_retries:
                time.sleep(2 ** attempt)

        raise Exception("번역이 재시도 후에도 실패했습니다")

    def _split_parallel_chunks(self, original: str, translated: str) -> list[tuple[str, str]]:
        """Split original and translated texts into aligned chunk pairs for refinement."""
        orig_chunks = self._split_into_chunks(original)
        trans_chunks = self._split_into_chunks(translated)

        # If chunk counts match, pair them directly
        if len(orig_chunks) == len(trans_chunks):
            return list(zip(orig_chunks, trans_chunks))

        # Otherwise, distribute translated text proportionally across original chunks
        total_orig_len = sum(len(c) for c in orig_chunks)
        pairs = []
        trans_joined = " ".join(trans_chunks)
        pos = 0
        for i, oc in enumerate(orig_chunks):
            ratio = len(oc) / total_orig_len if total_orig_len else 1 / len(orig_chunks)
            take = int(len(trans_joined) * ratio)
            if i == len(orig_chunks) - 1:
                tc = trans_joined[pos:]
            else:
                # Find nearest space to avoid cutting words
                end = pos + take
                space = trans_joined.rfind(" ", pos, end + 50)
                if space > pos:
                    end = space
                tc = trans_joined[pos:end]
                pos = end
            pairs.append((oc.strip(), tc.strip()))
        return pairs

    def refine(self, original_text: str, translated_text: str,
               source_lang: str, target_lang: str,
               issues: list, sync_mode: str = "optimize", engine: str = "local") -> str:
        """Refine a translation based on quality feedback. Uses chunking for long texts."""
        if not issues:
            return translated_text

        s_name = LANGUAGE_NAMES.get(source_lang, source_lang)
        t_name = LANGUAGE_NAMES.get(target_lang, target_lang)

        issues_text = "\n".join(f"- {issue}" for issue in issues[:10])

        if sync_mode == "optimize":
            dubbing_constraint = "Translate concisely without unnecessary filler. Preserve all original meaning."
        else:
            dubbing_constraint = "Provide a complete and accurate translation without omitting any content."

        lang_instructions = self._get_language_specific_instructions(target_lang, source_lang)
        lang_block = f"\nLANGUAGE-SPECIFIC RULES:\n{lang_instructions}" if lang_instructions else ""

        system_prompt = f"""You are a professional {s_name}-to-{t_name} translation refiner for video dubbing.
Fix the identified issues while preserving all content. Output ONLY the improved translation."""

        sanitized_original = self.sanitize_input(original_text)
        sanitized_translated = self.sanitize_input(translated_text)

        # For long texts, refine in chunks
        if len(sanitized_original) > self.CHUNK_THRESHOLD:
            pairs = self._split_parallel_chunks(sanitized_original, sanitized_translated)
            print(f"[Translator] Refining in {len(pairs)} chunks")
            refined_chunks = []
            for i, (orig_chunk, trans_chunk) in enumerate(pairs):
                print(f"[Translator] Refining chunk {i+1}/{len(pairs)}")
                chunk_result = self._refine_chunk(
                    orig_chunk, trans_chunk, s_name, t_name,
                    issues_text, dubbing_constraint, lang_block,
                    system_prompt, engine
                )
                refined_chunks.append(chunk_result)
            return "\n".join(refined_chunks)
        else:
            return self._refine_chunk(
                sanitized_original, sanitized_translated, s_name, t_name,
                issues_text, dubbing_constraint, lang_block,
                system_prompt, engine
            )

    def _refine_chunk(self, original: str, translated: str,
                      s_name: str, t_name: str,
                      issues_text: str, dubbing_constraint: str,
                      lang_block: str, system_prompt: str, engine: str) -> str:
        """Refine a single chunk. Auto-fallback from Gemini to Groq on quota error."""
        prompt = f"""The previous translation had these issues:
{issues_text}

{dubbing_constraint}

Fix these issues:
- Accuracy problems: fix mistranslations, restore omitted content.
- Naturalness: rephrase to sound native.
- Dubbing fit: adjust length without losing meaning.
- Consistency: unify terminology and tone.
{lang_block}

Original ({s_name}):
<text>
{original}
</text>

Previous Translation ({t_name}):
<text>
{translated}
</text>

Improved Translation:"""

        max_retries = 2
        current_engine = engine
        for attempt in range(1, max_retries + 1):
            try:
                result = self._call_llm(prompt, current_engine, system_prompt=system_prompt)
                if result:
                    return result
                print(f"Refinement attempt {attempt} returned empty")
            except GeminiQuotaError:
                print(f"[Translator] Gemini quota exceeded during refinement — falling back to Groq")
                if GROQ_API_KEY:
                    current_engine = "groq"
                    continue
                raise
            except Exception as e:
                print(f"Refinement error (attempt {attempt}): {e}")

            if attempt < max_retries:
                time.sleep(2 ** attempt)

        # If refinement fails, return original translation
        print("Refinement chunk failed, keeping original")
        return translated
