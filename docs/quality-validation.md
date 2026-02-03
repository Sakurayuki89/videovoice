# 번역 품질 신뢰성 시스템 (Reliability System)

Gemini 2.5 Flash를 활용한 4단계 고신뢰성 품질 검증 시스템입니다.

## 개요

단순한 1회성 평가를 넘어, **다중 평가(Dual Eval)**와 **자동 리파인(Auto-Refine)** 루프를 통해 번역 품질을 85% 이상으로 보장합니다.

## 4단계 신뢰성 프로세스

### 1. Dual Evaluation (이중 평가)
- Temperature 0.1로 2회 독립 평가 수행
- 두 점수의 평균을 최종 점수로 채택 (평가 편향 제거)
- 점수 차이가 20점 이상일 경우 3차 평가 수행

### 2. Term Preservation Check (용어 보존)
- 원문과 번역문의 **숫자, 고유명사, 영문 용어** 추출 및 비교
- 보존율이 30% 미만일 경우 점수와 관계없이 **REJECT** 처리

### 3. Logic Gate (품질 게이트)
- **85점 이상**: 즉시 통과 (PASS)
- **85점 미만**: 리파인 루프 진입

### 4. Auto-Refine Loop (자동 개선)
- 평가 피드백(Issues)을 반영하여 다시 번역 요청
- 최대 3라운드 수행
- 개선되지 않으면 원본 사용 혹은 사용자 경고

## 평가 기준 (Scoring Rubric)

| 항목 | 가중치 | 체크 포인트 |
|------|--------|------|
| **의미 정확도** | 40% | 오역 없음, 핵심 정보 누락 없음 |
| **자연스러움** | 30% | 도착 언어 원어민 화자 기준 자연스러움 |
| **더빙 적합성** | 20% | 문장 길이 비율(±15%), 호흡 적절성 |
| **일관성** | 10% | 문체(경어/평어) 및 용어 통일성 |

## 출력 형식 (JSON)

```json
{
  "overall_score": 88,
  "breakdown": { "accuracy": 90, "naturalness": 85, ... },
  "issues": ["의학 용어 'myelopathy'가 일반 용어로 번역됨"],
  "recommendation": "APPROVED",
  "term_preservation": {
    "score": 1.0,
    "missing": []
  }
}
```

## 비용 최적화 전략 (Caching)

- **Translation Cache**: 번역문 + 품질 점수를 해시값으로 저장
- **Validity Check**: 캐시된 번역의 점수가 85점 미만이면 무효화하고 재번역
- **Network**: Gemini 2.5 Flash 사용으로 비용 최소화 (약 40원/10분)
