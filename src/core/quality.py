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

# Import constants from config (with fallback for standalone usage)
try:
    from ..config import QUALITY_EVAL_TIMEOUT, QUALITY_MAX_TEXT_LENGTH
except ImportError:
    QUALITY_EVAL_TIMEOUT = 120  # 2 minutes default
    QUALITY_MAX_TEXT_LENGTH = 10000  # Max chars for quality eval


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
                self._genai = genai
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

        # #8 Fix: Sample long texts (front/middle/end) instead of simple truncation
        original_text = self._sample_long_text(original_text, QUALITY_MAX_TEXT_LENGTH)
        translated_text = self._sample_long_text(translated_text, QUALITY_MAX_TEXT_LENGTH)

        prompt = self._build_prompt(
            original_text, translated_text, source_lang, target_lang
        )

        try:
            model = self._get_model()
            gen_config = self._genai.types.GenerationConfig(
                temperature=0.1,
                max_output_tokens=2048,
            )

            # Dual evaluation for reliability — run twice and average
            results = []
            gemini_quota_error = False
            for i in range(2):
                try:
                    response = model.generate_content(
                        prompt,
                        generation_config=gen_config,
                        request_options={"timeout": QUALITY_EVAL_TIMEOUT}
                    )
                    parsed = self._parse_response(response.text)
                    if parsed.get("error"):
                        continue
                    results.append(parsed)
                except Exception as e:
                    error_str = str(e).lower()
                    # #2 Fix: Detect Gemini quota errors
                    if "429" in error_str or "resource exhausted" in error_str or "quota" in error_str:
                        gemini_quota_error = True
                        print(f"[QualityValidator] Gemini quota exceeded")
                        break
                    try:
                        print(f"[QualityValidator] Round {i+1} error: {e}")
                    except UnicodeEncodeError:
                        print(f"[QualityValidator] Round {i+1} error (encoding issue)")
                    continue

            # #2 Fix: Fallback to Groq if Gemini quota exceeded
            if gemini_quota_error or not results:
                result = self._fallback_groq_evaluate(prompt)
                if result and not result.get("error"):
                    return result
                if not results:
                    return self._default_result("All evaluation rounds failed")

            if len(results) == 1:
                return results[0]

            # Average the two evaluations
            return self._merge_evaluations(results)

        except Exception as e:
            print(f"Quality evaluation failed: {e}")
            return self._default_result(f"API error: {str(e)}")

    def _merge_evaluations(self, results: list) -> dict:
        """Merge multiple evaluation results by averaging scores."""
        n = len(results)
        avg_score = round(sum(r["overall_score"] for r in results) / n)

        avg_breakdown = {}
        for key in ["accuracy", "naturalness", "dubbing_fit", "consistency"]:
            avg_breakdown[key] = round(
                sum(r.get("breakdown", {}).get(key, 0) for r in results) / n
            )

        # Collect unique issues from all rounds
        all_issues = []
        seen = set()
        for r in results:
            for issue in r.get("issues", []):
                normalized = issue.strip().lower()[:80]
                if normalized not in seen:
                    seen.add(normalized)
                    all_issues.append(issue)

        # Recommendation based on averaged score
        if avg_score >= 85:
            recommendation = "APPROVED"
        elif avg_score >= 60:
            recommendation = "REVIEW_NEEDED"
        else:
            recommendation = "REJECT"

        print(f"[QualityValidator] Dual eval scores: {[r['overall_score'] for r in results]} -> avg {avg_score}%")

        return {
            "overall_score": avg_score,
            "breakdown": avg_breakdown,
            "issues": all_issues,
            "recommendation": recommendation,
        }

    def _sample_long_text(self, text: str, max_len: int) -> str:
        """#8 Fix: Sample front/middle/end sections for long texts instead of truncating."""
        if len(text) <= max_len:
            return text
        
        # Split into 3 equal sections: front, middle, end
        section_len = max_len // 3
        front = text[:section_len]
        middle_start = (len(text) - section_len) // 2
        middle = text[middle_start:middle_start + section_len]
        end = text[-section_len:]
        
        return f"{front}\n[...중략...]\n{middle}\n[...중략...]\n{end}"

    def _fallback_groq_evaluate(self, prompt: str) -> dict:
        """#2 Fix: Fallback to Groq API when Gemini quota is exceeded."""
        from ..config import GROQ_API_KEY
        if not GROQ_API_KEY:
            print("[QualityValidator] No GROQ_API_KEY for fallback")
            return None
        
        import requests
        print("[QualityValidator] Falling back to Groq for quality evaluation...")
        try:
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1
                },
                timeout=60
            )
            if response.status_code != 200:
                print(f"[QualityValidator] Groq fallback failed: {response.status_code}")
                return None
            
            content = response.json()["choices"][0]["message"]["content"]
            return self._parse_response(content)
        except Exception as e:
            print(f"[QualityValidator] Groq fallback error: {e}")
            return None

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

        return f"""You are a strict translation quality evaluator for video dubbing.

Evaluate the following {src_name} → {tgt_name} translation.

Original ({src_name}):
{original}

Translation ({tgt_name}):
{translated}

SCORING RUBRIC (be strict and consistent):

1. Accuracy (40% weight):
   - 90-100: Every sentence fully translated, no omissions, no mistranslations
   - 70-89: Minor inaccuracies but all sentences present
   - 50-69: Some sentences missing or significantly mistranslated
   - Below 50: Major omissions or incomplete sentences (e.g. sentence cut off mid-word)
   CRITICAL: If ANY sentence is incomplete or cut off, accuracy MUST be 70 or below.

2. Naturalness (30% weight):
   - 90-100: Sounds like a native speaker wrote it, natural spoken style
   - 70-89: Grammatically correct but slightly stiff or literal
   - 50-69: Awkward phrasing that a native would notice immediately
   - Below 50: Machine-translation quality, unnatural word order

3. Dubbing Fit (20% weight):
   - 90-100: Length matches original, easy to speak aloud at natural pace
   - 70-89: Slightly longer/shorter but still speakable
   - 50-69: Noticeably too long or too short for the video timing
   - Below 50: Completely mismatched length

4. Consistency (10% weight):
   - 90-100: Same terms and tone throughout, no contradictions
   - 70-89: Minor inconsistencies in terminology
   - Below 70: Different terms used for the same concept, tone shifts
{lang_notes}

overall_score = accuracy*0.4 + naturalness*0.3 + dubbing_fit*0.2 + consistency*0.1

List ONLY actionable issues that can be fixed (max 5). Be specific: quote the problematic text.

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
  "recommendation": "APPROVED" or "REVIEW_NEEDED" or "REJECT"
}}"""

    def _parse_response(self, response_text: str) -> dict:
        """Parse JSON response from Gemini, with truncation recovery."""
        # Remove markdown code blocks if present
        text = response_text.strip()
        text = re.sub(r'^```json\s*', '', text)
        text = re.sub(r'^```\s*', '', text)
        text = re.sub(r'\s*```$', '', text)

        result = None
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            # Gemini often truncates the issues array — try to recover
            result = self._recover_truncated_json(text)

        if not result:
            print(f"Failed to parse Gemini response (even after recovery)")
            print(f"Response was: {text[:500]}")
            return self._default_result("Failed to parse API response")

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

    def _recover_truncated_json(self, text: str) -> dict | None:
        """Try to recover a truncated JSON response by closing open brackets."""
        # Strategy 1: Cut at last complete field before issues, add empty issues
        score_match = re.search(r'"overall_score"\s*:\s*(\d+)', text)
        if not score_match:
            return None

        # Try to extract breakdown
        breakdown = {}
        for key in ["accuracy", "naturalness", "dubbing_fit", "consistency"]:
            m = re.search(rf'"{key}"\s*:\s*(\d+)', text)
            if m:
                breakdown[key] = int(m.group(1))

        # Try to extract recommendation
        rec_match = re.search(r'"recommendation"\s*:\s*"(\w+)"', text)

        # Try to extract any complete issue strings
        issues = re.findall(r'"issues"\s*:\s*\[(.*)', text, re.DOTALL)
        issue_list = []
        if issues:
            # Find complete quoted strings in the issues array
            issue_list = re.findall(r'"([^"]{5,})"', issues[0])

        score = int(score_match.group(1))
        result = {
            "overall_score": score,
            "breakdown": breakdown if breakdown else {
                "accuracy": score, "naturalness": score,
                "dubbing_fit": score, "consistency": score
            },
            "issues": issue_list,
            "recommendation": rec_match.group(1) if rec_match else (
                "APPROVED" if score >= 85 else "REVIEW_NEEDED" if score >= 60 else "REJECT"
            ),
        }
        print(f"[QualityValidator] Recovered truncated JSON - score: {score}%")
        return result

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
