import requests
import time
import re

from ..config import (
    OLLAMA_HOST as DEFAULT_OLLAMA_HOST,
    OLLAMA_MODEL as DEFAULT_OLLAMA_MODEL,
    OLLAMA_TIMEOUT as DEFAULT_OLLAMA_TIMEOUT,
    GROQ_API_KEY,
    GROQ_MODEL,
)

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

    def _call_groq(self, prompt: str) -> str:
        """Call Groq API (OpenAI-compatible) and return the response text."""
        if not GROQ_API_KEY:
            raise Exception("GROQ_API_KEY is not set. Please set it in your .env file.")

        response = requests.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.4
            },
            timeout=self.timeout
        )

        if response.status_code != 200:
            raise Exception(f"Groq API error ({response.status_code}): {response.text}")

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
            raise Exception(f"Ollama error ({response.status_code}): {response.text}")

        raw = response.json().get('response', '')
        cleaned = self.strip_think_tags(raw)
        if not cleaned:
            raise Exception("Ollama returned empty response")
        return cleaned

    def _call_llm(self, prompt: str, engine: str = "local") -> str:
        """Route to the appropriate LLM backend."""
        if engine == "groq":
            return self._call_groq(prompt)
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

    def translate(self, text: str, source_lang: str, target_lang: str, sync_mode: str = "optimize", engine: str = "local") -> str:
        if not text or not text.strip():
            return ""

        # Sanitize input to prevent prompt injection
        sanitized_text = self.sanitize_input(text)
        if not sanitized_text:
            return ""

        # Map codes to names
        s_name = LANGUAGE_NAMES.get(source_lang, source_lang)
        t_name = LANGUAGE_NAMES.get(target_lang, target_lang)

        # Build prompt based on sync mode
        if sync_mode == "optimize":
            dubbing_constraint = """
Dubbing Constraint: CONCISE AND NATURAL.
- Translate concisely. Do NOT add unnecessary filler, elaboration, or paraphrasing.
- Preserve ALL original meaning and details — do not omit content.
- Preserve the exact narrative perspective (1st person stays 1st person, 3rd stays 3rd).
- Keep all medical and technical terms accurate."""
        else:
            # speed_audio and stretch both use full translation
            dubbing_constraint = """
Translation Requirement: FULL COMPLETENESS IS MANDATORY.
- You are FORBIDDEN from summarizing or omitting ANY content.
- Every single sentence, clause, and nuance from the source must be present.
- Medical details, examples, and small talk must be preserved exactly.
- Maintain the original narrative voice (Do not switch from "He said" to "I said").
- Misinterpretation or omission of medical terms is a critical failure.
- The goal is a rich, full translation that fills the audio track."""

        lang_instructions = self._get_language_specific_instructions(target_lang, source_lang)
        lang_block = f"\nLANGUAGE-SPECIFIC RULES:\n{lang_instructions}" if lang_instructions else ""

        # Use delimiter markers to clearly separate instruction from content
        prompt = f"""You are a professional video translator and dubbing scriptwriter.
Your task is to translate {s_name} text to {t_name} for a video dubbing script.

{dubbing_constraint}

CRITICAL RULES:
1. NO OMISSIONS: Do not summarize. Translate every single detail.
2. NO HALLUCINATIONS: Do not add facts not present in the text.
3. NARRATIVE VOICE: Keep the original speaker's perspective (I -> I, He -> He).
4. TONE: Match the original speaker's tone (Medical/Professional/Casual).
{lang_block}

<content_to_translate>
{sanitized_text}
</content_to_translate>

Output ONLY the translated text without any explanation or additional commentary.
Translation:"""
        
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                result = self._call_llm(prompt, engine)
                if result:
                    return result
                print(f"Translation attempt {attempt} returned empty")
            except Exception as e:
                print(f"Translation error (attempt {attempt}): {e}")

            if attempt < max_retries:
                time.sleep(2 ** attempt)

        raise Exception("Translation failed after retries")

    def refine(self, original_text: str, translated_text: str,
               source_lang: str, target_lang: str,
               issues: list, sync_mode: str = "optimize", engine: str = "local") -> str:
        """Refine a translation based on quality feedback."""
        if not issues:
            return translated_text

        s_name = LANGUAGE_NAMES.get(source_lang, source_lang)
        t_name = LANGUAGE_NAMES.get(target_lang, target_lang)

        sanitized_original = self.sanitize_input(original_text)
        sanitized_translated = self.sanitize_input(translated_text)
        issues_text = "\n".join(f"- {issue}" for issue in issues[:10])

        if sync_mode == "optimize":
            dubbing_constraint = "Translate concisely without unnecessary filler. Preserve all original meaning."
        else:
            dubbing_constraint = "Provide a complete and accurate translation without omitting any content."

        lang_instructions = self._get_language_specific_instructions(target_lang, source_lang)
        lang_block = f"\nLANGUAGE-SPECIFIC RULES:\n{lang_instructions}" if lang_instructions else ""

        prompt = f"""You are refining a {s_name} to {t_name} translation for video dubbing.

The previous translation had these quality issues:
{issues_text}

{dubbing_constraint}

REFINEMENT GUIDE:
- If the issue is about accuracy: fix mistranslations, restore omitted content.
- If the issue is about naturalness: rephrase to sound native, fix awkward phrasing.
- If the issue is about dubbing fit: adjust length without losing meaning.
- If the issue is about consistency: unify terminology, tone, and style.

CRITICAL RULES:
1. NO OMISSIONS: Do not summarize. Translate every single detail.
2. NO HALLUCINATIONS: Do not add facts not present in the original.
3. NARRATIVE VOICE: Keep the original speaker's perspective (I -> I, He -> He).
4. TONE: Match the original speaker's tone.
{lang_block}

Original ({s_name}):
<content_to_translate>
{sanitized_original}
</content_to_translate>

Previous Translation ({t_name}):
{sanitized_translated}

Provide an improved translation that fixes the issues above.
Output ONLY the improved translated text without any explanation.

Improved Translation:"""

        max_retries = 2
        for attempt in range(1, max_retries + 1):
            try:
                result = self._call_llm(prompt, engine)
                if result:
                    return result
                print(f"Refinement attempt {attempt} returned empty")
            except Exception as e:
                print(f"Refinement error (attempt {attempt}): {e}")

            if attempt < max_retries:
                time.sleep(2 ** attempt)

        # If refinement fails, return original translation
        print("Refinement failed, keeping original translation")
        return translated_text
