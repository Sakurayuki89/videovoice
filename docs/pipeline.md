# 처리 파이프라인

VideoVoice의 8단계 하이브리드 파이프라인 상세 설명입니다.

## 파이프라인 개요

```
1. Video Input → 2. Audio Extraction → 3. STT (Hybrid) → 4. Chunk Translation
    → 5. Quality Reliability System → 6. TTS (Hybrid) → 7. Audio Merge (Sync) → 8. Video Output
```

## 단계별 상세

### 1단계: Video Input
- **입력**: MP4, MKV 등 (10~15분 권장)
- **검증**: 파일 무결성 체크

### 2단계: Audio Extraction
- **도구**: FFmpeg (Server) 또는 FFmpeg.wasm (Client)
- **출력**: WAV (16kHz, mono)

### 3단계: Speech-to-Text (Hybrid)
- **Cloud**: Groq (whisper-large-v3), OpenAI (whisper-1) - **추천**
- **Local**: WhisperX large-v3 (타임스탬프 정밀도 우수)
- **출력**: 정밀 타임스탬프가 포함된 JSON

### 4단계: Translation (Chunk Processing)
- **전략**: 문맥 유지를 위한 400~800자 단위 청크 처리
- **Main Tool**: **Gemini 2.5 Flash**
- **Fallback**: Groq (Llama 3.3)
- **Local**: Ollama (Qwen3)
- **기능**: Few-shot 프롬프팅, JSON 포맷 강제

### 5단계: Quality Reliability System (신뢰성 검증)
- **평가 엔진**: Gemini 2.5 Flash
- **4단계 프로세스**:
  1. **Dual Evaluation**: Temperature 0.1로 2회 평가하여 평균 점수 산출
  2. **Term Check**: 숫자, 고유명사 보존율 자동 검사
  3. **Refinement**: 85점 미만 시 지적 사항 반영하여 자동 수정 (최대 3회)
  4. **Repair**: 잘린 JSON 응답 자동 복구

### 6단계: Text-to-Speech (Hybrid)
- **Cloud**: **ElevenLabs** (최고 품질), OpenAI
- **Local**: Edge TTS (한국어 추천), Silero (러시아어/고속), XTTS v2 (음성 클로닝)
- **선택**: 언어별 최적 엔진 자동 추천 시스템 적용

### 7단계: Audio Merge & Sync
- **도구**: pydub + FFmpeg
- **싱크 모드**:
  1. **Natural (Optimize)**: 원래 속도 유지 (자연스러움 중시)
  2. **Speed Sync**: 오디오 길이를 영상에 강제 맞춤 (기본값)
  3. **Video Stretch**: 영상을 느리게/빠르게 조절

### 8단계: Video Output
- **도구**: FFmpeg
- **처리**: 오디오 트랙 교체 및 비디오 리먹싱 (Re-muxing)

## 에러 복구 전략

| 단계 | 에러 유형 | 자동 대응 |
|------|-----------|------|
| API | 429 (Rate Limit) | 지수 백오프(Backoff) 및 예비 엔진(Fallback) 전환 |
| 번역 | JSON 깨짐 | LLM을 이용한 JSON Repair 자동 실행 |
| 품질 | 점수 미달 | 피드백 반영 리파인 루프 실행 (Max 3) |
| TTS | 생성 실패 | 백업 엔진(예: Edge TTS)으로 자동 전환 시도 |
