---
name: quality-validation
description: Gemini API 기반 번역 품질 평가 스킬
---

# Quality Validation Skill

Gemini API를 사용하여 로컬 번역 결과의 품질을 평가하고 1~100% 점수를 산출합니다.

## Gemini API 호출

```python
import google.generativeai as genai

genai.configure(api_key="YOUR_API_KEY")
model = genai.GenerativeModel("gemini-2.0-flash")

def evaluate_translation(original: str, translated: str, source_lang: str, target_lang: str) -> dict:
    prompt = f"""You are a translation quality evaluator for video dubbing.

Evaluate the following translation and provide a score from 1-100.

Original ({source_lang}):
{original}

Translation ({target_lang}):
{translated}

Evaluate based on:
1. Accuracy (40%): Does the translation preserve the original meaning?
2. Naturalness (30%): Does it sound natural in the target language?
3. Dubbing Fit (20%): Is the length appropriate? Easy to pronounce?
4. Consistency (10%): Are terms and tone consistent?

Respond ONLY in this JSON format:
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

    response = model.generate_content(prompt)
    return json.loads(response.text)
```

## 평가 기준

| 항목 | 가중치 | 설명 |
|------|--------|------|
| 의미 정확도 | 40% | 원문 의미 정확히 전달 |
| 자연스러움 | 30% | 대상 언어에서 자연스러움 |
| 더빙 적합성 | 20% | 길이, 발음 용이성 |
| 일관성 | 10% | 용어/어조 일관성 |

## 권장사항 기준

- **APPROVED**: 85점 이상, 바로 사용 가능
- **REVIEW_NEEDED**: 60~84점, 수동 검토 권장
- **REJECT**: 60점 미만, 재번역 필요

## 배치 평가

```python
def evaluate_batch(segments: list) -> dict:
    results = []
    for seg in segments:
        result = evaluate_translation(
            seg["original"], 
            seg["translated"],
            seg["source_lang"],
            seg["target_lang"]
        )
        results.append(result)
    
    avg_score = sum(r["overall_score"] for r in results) / len(results)
    return {
        "average_score": avg_score,
        "segments": results,
        "overall_recommendation": "APPROVED" if avg_score >= 85 else 
                                  "REVIEW_NEEDED" if avg_score >= 60 else "REJECT"
    }
```

## 리포트 생성

평가 결과는 JSON 파일로 저장되어 사용자 검토에 활용됩니다.
