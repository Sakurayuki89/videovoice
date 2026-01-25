# 처리 파이프라인

VideoVoice의 8단계 처리 파이프라인 상세 설명입니다.

## 파이프라인 개요

```
1. Video Input → 2. Audio Extraction → 3. STT → 4. Translation
    → 5. Quality Validation → 6. TTS → 7. Audio Merge → 8. Video Output
```

## 단계별 상세

### 1단계: Video Input
- **입력**: MP4 파일 (10~15분)
- **검증**: 파일 존재, 코덱 호환성

### 2단계: Audio Extraction
- **도구**: FFmpeg
- **출력**: WAV (16kHz, mono, PCM 16-bit)
- **명령**: `ffmpeg -i input.mp4 -vn -ar 16000 -ac 1 audio.wav`

### 3단계: Speech-to-Text
- **도구**: WhisperX large-v3
- **출력**: JSON (타임스탬프 + 문장)
- **언어 감지**: 자동 (ko/en/ru)

### 4단계: Translation
- **도구**: Ollama + Qwen3:14b
- **처리 단위**: 문장별
- **규칙**: 길이 ±10%, 자연스러운 더빙용 번역

### 5단계: Quality Validation
- **도구**: Gemini API
- **평가**: 의미 정확도, 자연스러움, 더빙 적합성, 일관성
- **출력**: 1~100% 점수 + 권장사항

### 6단계: Text-to-Speech
- **도구**: XTTS v2
- **출력**: 문장별 WAV 파일
- **화자**: 프로젝트 고정 Speaker Embedding

### 7단계: Audio Merge
- **도구**: pydub
- **무음 삽입**: 문장 간 200~400ms
- **볼륨 정규화**: RMS 기준

### 8단계: Video Output
- **도구**: FFmpeg
- **처리**: 원본 비디오 스트림 복사 + 새 오디오 삽입
- **명령**: `ffmpeg -i original.mp4 -i new_audio.wav -c:v copy -map 0:v:0 -map 1:a:0 output.mp4`

## 세그멘테이션 정책

긴 영상은 30~60초 단위로 분할 처리:

```
전체 영상 → 세그먼트 분할 → 각 세그먼트 처리 → 최종 병합
```

## 에러 처리

| 단계 | 에러 유형 | 대응 |
|------|-----------|------|
| STT | 인식 실패 | 해당 구간 타임스탬프 기록 후 스킵 |
| 번역 | 응답 없음 | 3회 재시도 후 원문 유지 |
| TTS | 생성 실패 | 무음으로 대체 |
| 품질 | 60점 미만 | REVIEW_NEEDED 표시 |
