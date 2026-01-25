# Agent Specification: Local Multilingual Video Voice Transformation (KO / EN / RU)

## 1. Project Overview

본 프로젝트는 로컬 AI 환경(RTX 3060 12GB 기준)에서
10~15분 길이의 동영상을 입력으로 받아,
영상 편집 툴 없이 원본 음성을 완전히 제거하고
선택한 대상 언어(한국어, 영어, 러시아어) 음성으로 자동 변환하여
새로운 영상 파일(mp4)을 출력하는 것을 목표로 한다.

립싱크는 요구하지 않으며,
Audio Track Replacement(음성 트랙 교체) 방식을 사용한다.

본 프로젝트는 **클라우드 API나 외부 서비스에 의존하지 않는
완전 로컬 AI 처리**를 전제로 한다.

---

## 2. Supported Languages

### 2.1 Input Languages
- Korean (ko)
- English (en)
- Russian (ru)

### 2.2 Output Languages
- Korean (ko)
- English (en)
- Russian (ru)

입력 언어와 출력 언어는 동일할 수도 있고 상이할 수도 있다.

---

## 3. Local AI Execution Policy

본 프로젝트의 모든 언어·음성 처리 과정은
클라우드 API 없이 로컬 AI 모델만 사용한다.

### 3.1 Local LLM (Translation Engine)

- Runtime: Ollama
- Model: Qwen3 (14B 또는 30B, Quantized)
- Quantization: Q4 또는 Q5
- GPU Target: RTX 3060 12GB
- Task:
  - 한국어 ↔ 영어
  - 한국어 ↔ 러시아어
  - 영어 ↔ 러시아어

번역은 반드시 문장 단위 또는 짧은 구간 단위로 수행하며,
전체 대본을 한 번에 번역하는 방식은 사용하지 않는다.

### 3.2 Local Speech-to-Text (STT)

- Model: WhisperX (large-v3)
- Execution: Local GPU
- Language Detection: Automatic (ko / en / ru)
- Output: 타임스탬프 포함 문장 단위 텍스트

### 3.3 Local Text-to-Speech (TTS)

- Model: XTTS v2 (또는 동급 다국어 TTS)
- Speaker embedding: 프로젝트 단위로 고정
- Generation Unit: 문장 단위
- Sentence gap: 200~400ms 무음 삽입

### 3.4 No External Dependency Rule

- 클라우드 API 사용 금지
- 외부 번역 서비스 사용 금지
- 네트워크 연결 없이 실행 가능해야 함

---

## 4. Core Processing Pipeline (No GUI Editing)

1. Video Input (.mp4)
2. Audio Extraction (FFmpeg)
3. Speech-to-Text (WhisperX)
4. Sentence-level Translation (Ollama + Qwen3)
5. Sentence-level TTS Generation
6. Audio Merge (concatenation)
7. Audio Track Replacement (FFmpeg)
8. Final Video Output (.mp4)

---

## 5. Reliability Strategy (10–15 Minute Guarantee)

본 프로젝트의 신뢰성 기준은 다음과 같다:

“RTX 3060 12GB 단일 GPU 환경에서  
Ollama + Qwen3 기반 로컬 번역을 사용하여  
10~15분 영상의 음성 교체 결과물이  
재작업 없이 바로 사용 가능한 상태로 출력되는 것”

### 5.1 Segmentation Policy

- 전체 영상은 30~60초 단위로 분할 처리
- STT → 번역 → TTS는 문장 단위로 수행
- 모든 오디오는 최종 단계에서 병합

### 5.2 Translation Stability Rules

- 문장 길이 변화 ±10% 이내 유지
- 직역보다 더빙용 자연스러운 번역 우선
- 불필요한 감탄사, 접속사 최소화

### 5.3 TTS Consistency Rules

- 동일 speaker embedding 유지
- 말 속도 변화 ±10% 이내 제한
- RMS 볼륨 자동 정규화

### 5.4 Audio Replacement Policy

- 원본 오디오 트랙 완전 제거
- 새 음성 트랙만 영상에 삽입
- 비디오 스트림 재인코딩 금지

---

## 6. Hardware Constraints

- GPU: RTX 3060 12GB
- RAM: 64GB
- Storage: Local SSD
- Execution Mode: Single GPU, Local-only

---

## 7. Output Requirements

- 한국어 원음 완전 제거
- 대상 언어 음성만 존재
- 음색 및 말투 일관성 유지
- 영상과 음성 싱크 자연스러움
- 단일 mp4 파일로 출력

---

## 8. Validation Checklist

- [ ] 입력 언어 자동 감지 정상
- [ ] STT 타임스탬프 정상
- [ ] 번역 의미 왜곡 없음
- [ ] TTS 음색 변화 없음
- [ ] 오디오 길이 과도한 불일치 없음
- [ ] 원본 음성 완전 제거 확인

---

## 9. Review & Approval Flow

1. 자동 처리 결과 생성
2. 언어별 30초 샘플 검증
3. 전체 영상 검토
4. 사용자 승인 또는 수정 요청 반영

---

## 10. Comparison Reference (Gemini Documentation Use)

본 agent.md는 실행 기준 문서이며,
Gemini를 사용할 경우에는 다음 목적에 한해 보조적으로 활용한다.

- 설계 설명 보완
- 비기술 이해관계자 공유용 문서
- 구조적 요약 및 정리

단, 구현 기준과 판단 기준은
본 agent.md를 최우선으로 한다.
