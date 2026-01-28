import requests
import time
import re
import os

# Default configuration (can be overridden by environment variables)
DEFAULT_OLLAMA_HOST = os.environ.get("VIDEOVOICE_OLLAMA_HOST", "http://localhost:11434")
DEFAULT_OLLAMA_MODEL = os.environ.get("VIDEOVOICE_OLLAMA_MODEL", "qwen3:14b")
DEFAULT_OLLAMA_TIMEOUT = int(os.environ.get("VIDEOVOICE_OLLAMA_TIMEOUT", "120"))

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

    def translate(self, text: str, source_lang: str, target_lang: str, sync_mode: str = "optimize") -> str:
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
            # Concise translation mode - prioritize brevity to match original duration
            dubbing_constraint = """
Dubbing Constraint: Translate concisely to match the original speech duration.
- Prioritize brevity over literal accuracy
- Use natural contractions and shorter expressions
- Omit filler words and redundant phrases
- Keep the core meaning while reducing word count
- The translated text should take approximately the same time to speak as the original"""
        else:
            # Stretch mode - full translation without length constraints
            dubbing_constraint = """
Translation Requirement: Provide a complete and accurate translation.
- Preserve all information from the original text
- Maintain natural expression in the target language
- Do not abbreviate or omit any content"""

        # Use delimiter markers to clearly separate instruction from content
        prompt = f"""Translate the following {s_name} text to {t_name} for a video dubbing script.
{dubbing_constraint}

Output ONLY the translated text without any explanation or additional commentary.

<content_to_translate>
{sanitized_text}
</content_to_translate>

Translation:"""
        
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(
                    f"{self.host}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False
                    },
                    timeout=self.timeout
                )
                
                if response.status_code == 200:
                    res_json = response.json()
                    raw = res_json.get('response', '')
                    cleaned = self.strip_think_tags(raw)
                    if cleaned:
                        return cleaned
                
                print(f"Translation attempt {attempt} failed: {response.text}")
                
            except Exception as e:
                print(f"Translation error (attempt {attempt}): {e}")
            
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                
        raise Exception("Translation failed after retries")
