---
name: translation
description: Ollama + Qwen3 기반 로컬 번역 스킬
---

# Translation Skill

Ollama와 Qwen3 모델을 사용하여 문장 단위 로컬 번역을 수행합니다.

## Ollama API 호출

```python
import requests

def translate(text: str, source_lang: str, target_lang: str) -> str:
    prompt = f"""Translate the following {source_lang} text to {target_lang}.
This is for video dubbing, so:
- Keep the translation natural and conversational
- Maintain similar sentence length (±10%)
- Minimize filler words and interjections

Text: {text}

Translation:"""

    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "qwen3:14b",
            "prompt": prompt,
            "stream": False
        }
    )
    return response.json()["response"].strip()
```

## 언어 코드

| 언어 | 코드 | Ollama 지원 |
|------|------|-------------|
| 한국어 | ko | ✅ |
| 영어 | en | ✅ |
| 러시아어 | ru | ✅ |

## 더빙용 번역 규칙

1. **문장 단위 번역**: 전체 대본 일괄 번역 금지
2. **길이 제한**: 원문 대비 ±10% 이내
3. **자연스러움 우선**: 직역보다 더빙에 적합한 의역
4. **감탄사 최소화**: 불필요한 "음", "아" 등 제거
5. **일관성 유지**: 동일 용어는 동일하게 번역

## 프롬프트 템플릿

### 한국어 → 영어
```
Translate Korean to English for video dubbing. Keep it natural and similar length.
Korean: {text}
English:
```

### 한국어 → 러시아어
```
Translate Korean to Russian for video dubbing. Keep it natural and similar length.
Korean: {text}
Russian:
```

### 영어 → 한국어
```
Translate English to Korean for video dubbing. Keep it natural and similar length.
English: {text}
Korean:
```
