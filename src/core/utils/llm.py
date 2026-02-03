"""
공통 LLM 호출 유틸리티

translate.py와 quality.py에서 중복되는 Gemini/Groq 호출 로직을 통합합니다.
"""
import os


class GeminiQuotaError(Exception):
    """Raised when Gemini API returns 429 / quota exceeded."""
    pass


def is_quota_error(error: Exception) -> bool:
    """Check if an exception indicates API quota/rate limit exceeded."""
    error_str = str(error).lower()
    return any(kw in error_str for kw in ["429", "quota", "resource exhausted", "rate limit"])


def call_gemini(
    prompt: str,
    api_key: str,
    model_name: str = "gemini-2.5-flash",
    system_prompt: str = None,
    temperature: float = 0.3,
    max_output_tokens: int = 8192,
    timeout: int = 60,
) -> str:
    """
    Call Gemini API with standardized error handling.

    Args:
        prompt: User prompt text
        api_key: Gemini API key
        model_name: Model name (default: gemini-2.5-flash)
        system_prompt: Optional system instruction
        temperature: Generation temperature (default: 0.3)
        max_output_tokens: Max tokens in response (default: 8192)
        timeout: Request timeout in seconds (default: 60)

    Returns:
        Generated text response

    Raises:
        GeminiQuotaError: When API quota is exceeded (429)
        Exception: For other API errors
    """
    if not api_key:
        raise Exception("GEMINI_API_KEY가 설정되지 않았습니다.")

    try:
        import google.generativeai as genai
    except ImportError:
        raise Exception("google-generativeai 패키지가 설치되지 않았습니다. pip install google-generativeai")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name,
        system_instruction=system_prompt if system_prompt else None,
    )

    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            ),
            request_options={"timeout": timeout}
        )
        return response.text.strip()
    except Exception as e:
        if is_quota_error(e):
            raise GeminiQuotaError(f"Gemini API 할당량 초과: {e}")
        raise


def call_groq(
    prompt: str,
    api_key: str,
    model_name: str = "llama-3.3-70b-versatile",
    system_prompt: str = None,
    temperature: float = 0.3,
    timeout: int = 60,
) -> str:
    """
    Call Groq API with standardized error handling.

    Args:
        prompt: User prompt text
        api_key: Groq API key
        model_name: Model name (default: llama-3.3-70b-versatile)
        system_prompt: Optional system prompt
        temperature: Generation temperature (default: 0.3)
        timeout: Request timeout in seconds (default: 60)

    Returns:
        Generated text response

    Raises:
        Exception: For API errors including rate limits
    """
    import requests

    if not api_key:
        raise Exception("GROQ_API_KEY가 설정되지 않았습니다.")

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": model_name,
            "messages": messages,
            "temperature": temperature
        },
        timeout=timeout
    )

    if response.status_code == 429:
        raise Exception(f"Groq API 요청 한도 초과 (429). 잠시 후 다시 시도해주세요.")
    if response.status_code != 200:
        raise Exception(f"Groq API 오류 ({response.status_code}): {response.text}")

    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


def call_llm_with_fallback(
    prompt: str,
    primary_engine: str,
    gemini_api_key: str = None,
    groq_api_key: str = None,
    **kwargs
) -> str:
    """
    Call LLM with automatic fallback from Gemini to Groq on quota error.

    Args:
        prompt: User prompt text
        primary_engine: Primary engine to use ("gemini" or "groq")
        gemini_api_key: Gemini API key (optional)
        groq_api_key: Groq API key (optional)
        **kwargs: Additional arguments passed to the LLM call

    Returns:
        Generated text response
    """
    gemini_key = gemini_api_key or os.environ.get("GEMINI_API_KEY", "")
    groq_key = groq_api_key or os.environ.get("GROQ_API_KEY", "")

    if primary_engine == "gemini" and gemini_key:
        try:
            return call_gemini(prompt, gemini_key, **kwargs)
        except GeminiQuotaError:
            if groq_key:
                print("[LLM] Gemini 할당량 초과 — Groq으로 폴백")
                return call_groq(prompt, groq_key, **kwargs)
            raise
    elif groq_key:
        return call_groq(prompt, groq_key, **kwargs)
    elif gemini_key:
        return call_gemini(prompt, gemini_key, **kwargs)
    else:
        raise Exception("사용 가능한 LLM API 키가 없습니다. GEMINI_API_KEY 또는 GROQ_API_KEY를 설정해주세요.")
