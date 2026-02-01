"""
Translation Quality Validation using Gemini API

Evaluates translation quality and provides a score from 1-100%.
"""
import os
import json
import re
from pathlib import Path

# Load .env from project root
try:
    from dotenv import load_dotenv
    # Find project root (parent of src directory)
    project_root = Path(__file__).parent.parent.parent
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"[QualityValidator] Loaded .env from {env_path}")
    else:
        print(f"[QualityValidator] .env not found at {env_path}")
except ImportError:
    print("[QualityValidator] python-dotenv not installed")

# Configuration
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
print(f"[QualityValidator] GEMINI_API_KEY from env: {'SET' if GEMINI_API_KEY else 'NOT SET'}")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")


class QualityValidator:
    """Validates translation quality using Gemini API."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or GEMINI_API_KEY
        self._model = None
        print(f"[QualityValidator] Initialized with API key: {'SET (' + self.api_key[:10] + '...)' if self.api_key else 'NOT SET'}")

    def _get_model(self):
        """Lazy load the Gemini model."""
        if self._model is None:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self._model = genai.GenerativeModel(GEMINI_MODEL)
            except ImportError:
                raise RuntimeError(
                    "google-generativeai package not installed. "
                    "Install with: pip install google-generativeai"
                )
            except Exception as e:
                raise RuntimeError(f"Failed to initialize Gemini API: {e}")
        return self._model

    def evaluate(
        self,
        original_text: str,
        translated_text: str,
        source_lang: str,
        target_lang: str
    ) -> dict:
        """
        Evaluate translation quality.

        Args:
            original_text: Original text before translation
            translated_text: Translated text
            source_lang: Source language code (e.g., 'en')
            target_lang: Target language code (e.g., 'ko')

        Returns:
            dict with overall_score, breakdown, issues, recommendation
        """
        if not self.api_key:
            return self._default_result("Gemini API key not configured")

        if not original_text or not translated_text:
            return self._default_result("Empty text provided")

        # Truncate long texts for API call
        max_len = 5000
        original_text = original_text[:max_len]
        translated_text = translated_text[:max_len]

        prompt = self._build_prompt(
            original_text, translated_text, source_lang, target_lang
        )

        try:
            model = self._get_model()
            response = model.generate_content(prompt)

            # Parse JSON from response
            result = self._parse_response(response.text)
            return result

        except Exception as e:
            print(f"Quality evaluation failed: {e}")
            return self._default_result(f"API error: {str(e)}")

    def _build_prompt(
        self,
        original: str,
        translated: str,
        source_lang: str,
        target_lang: str
    ) -> str:
        """Build the evaluation prompt."""
        lang_names = {
            "en": "English", "ko": "Korean", "ja": "Japanese",
            "zh": "Chinese", "ru": "Russian", "es": "Spanish",
            "fr": "French", "de": "German", "it": "Italian",
            "pt": "Portuguese", "nl": "Dutch", "pl": "Polish",
            "tr": "Turkish", "vi": "Vietnamese", "th": "Thai",
            "ar": "Arabic", "hi": "Hindi", "auto": "Auto-detected",
        }
        src_name = lang_names.get(source_lang, source_lang)
        tgt_name = lang_names.get(target_lang, target_lang)

        # Language-specific evaluation notes
        lang_notes = ""
        if target_lang == "ko":
            lang_notes = """
Additional criteria for Korean:
- Sentence endings (어미/어투) should sound natural and spoken, not literary.
- Polite speech level (존댓말) should be consistent unless the source is casual.
- Dubbing fit: Korean is often shorter than English — check if padding feels forced."""
        elif target_lang == "ru":
            lang_notes = """
Additional criteria for Russian:
- Grammatical case and gender agreement must be correct.
- Formal/informal register (ты/Вы) should match the source tone."""
        elif target_lang == "ja":
            lang_notes = """
Additional criteria for Japanese:
- Politeness level (敬語/丁寧語/普通体) should match the source tone.
- Sentence-final particles should sound natural for spoken Japanese."""

        return f"""You are a translation quality evaluator for video dubbing.

Evaluate the following translation and provide a score from 1-100.

Original ({src_name}):
{original}

Translation ({tgt_name}):
{translated}

Evaluate based on:
1. Accuracy (40%): Does the translation preserve the original meaning?
2. Naturalness (30%): Does it sound natural in the target language?
3. Dubbing Fit (20%): Is the length appropriate for dubbing? Easy to speak aloud? Does it match a natural speaking rhythm?
4. Consistency (10%): Are terms and tone consistent?
{lang_notes}

Respond ONLY in this JSON format (no markdown, no code blocks):
{{
  "overall_score": <1-100>,
  "breakdown": {{
    "accuracy": <1-100>,
    "naturalness": <1-100>,
    "dubbing_fit": <1-100>,
    "consistency": <1-100>
  }},
  "issues": ["issue1", "issue2"],
  "recommendation": "APPROVED" | "REVIEW_NEEDED" | "REJECT"
}}"""

    def _parse_response(self, response_text: str) -> dict:
        """Parse JSON response from Gemini."""
        # Remove markdown code blocks if present
        text = response_text.strip()
        text = re.sub(r'^```json\s*', '', text)
        text = re.sub(r'^```\s*', '', text)
        text = re.sub(r'\s*```$', '', text)

        try:
            result = json.loads(text)

            # Validate response structure
            if "overall_score" not in result:
                return self._default_result("Invalid response format")

            # Ensure score is within range
            result["overall_score"] = max(0, min(100, int(result["overall_score"])))

            # Ensure breakdown exists
            if "breakdown" not in result:
                result["breakdown"] = {
                    "accuracy": result["overall_score"],
                    "naturalness": result["overall_score"],
                    "dubbing_fit": result["overall_score"],
                    "consistency": result["overall_score"]
                }

            # Ensure issues is a list
            if "issues" not in result or not isinstance(result["issues"], list):
                result["issues"] = []

            # Ensure recommendation exists
            if "recommendation" not in result:
                score = result["overall_score"]
                if score >= 85:
                    result["recommendation"] = "APPROVED"
                elif score >= 60:
                    result["recommendation"] = "REVIEW_NEEDED"
                else:
                    result["recommendation"] = "REJECT"

            return result

        except json.JSONDecodeError as e:
            print(f"Failed to parse Gemini response: {e}")
            print(f"Response was: {text[:500]}")
            return self._default_result("Failed to parse API response")

    def _default_result(self, error_message: str) -> dict:
        """Return a default result when evaluation fails."""
        return {
            "overall_score": 0,
            "breakdown": {
                "accuracy": 0,
                "naturalness": 0,
                "dubbing_fit": 0,
                "consistency": 0
            },
            "issues": [error_message],
            "recommendation": "REVIEW_NEEDED",
            "error": error_message
        }


# Global instance for convenience
quality_validator = QualityValidator()
