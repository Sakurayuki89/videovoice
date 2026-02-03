# 시스템 아키텍처

VideoVoice 로컬/클라우드 하이브리드 비디오 음성 변환 시스템의 전체 구조를 설명합니다.

## 시스템 개요 (Hybrid Architecture)

```mermaid
flowchart TD
    A[입력 비디오 MP4] --> B[오디오 추출]
    B --> C[음성 인식 STT]
    C --> D[청크 단위 번역]
    D --> E[품질 검증 & 리파인]
    E --> F[음성 합성 TTS]
    F --> G[오디오 병합 & 싱크]
    G --> H[오디오 트랙 교체]
    H --> I[출력 비디오 MP4]
    
    subgraph 로컬 AI (Local)
        C --> |WhisperX| C
        D --> |Ollama Qwen3| D
        F --> |XTTS v2 / Edge TTS| F
    end
    
    subgraph 클라우드 AI (Cloud)
        C --> |Groq / OpenAI| C
        D --> |Gemini 2.5 / Groq| D
        E --> |Gemini 2.5 Reliability| E
        F --> |ElevenLabs / OpenAI| F
    end
```

## 컴포넌트

| 컴포넌트 | 기술 (Local / Cloud) | 역할 |
|----------|------|------|
| 오디오 추출 | FFmpeg / FFmpeg.wasm | 비디오에서 오디오 분리 |
| 음성 인식 | WhisperX / Groq / OpenAI | 음성 → 타임스탬프 텍스트 |
| 번역 | Ollama / Gemini / Groq | 청크 단위 다국어 번역 |
| 품질 검증 | **Gemini 2.5 Flash** | 4단계 신뢰성 평가 및 리파인 |
| 음성 합성 | XTTS / Edge / ElevenLabs | 텍스트 → 음성 생성 |
| 오디오 병합 | FFmpeg (Sync Modes) | 속도 최적화 및 비디오 결합 |

## 하드웨어 요구사항 (Hybrid Mode)

- **GPU**: RTX 3060 12GB (로컬 모델 사용 시 필수)
- **RAM**: 32GB (권장 64GB)
- **저장소**: 로컬 SSD
- **네트워크**: 필수 (Gemini, Groq, ElevenLabs API 호출용)

## 데이터 흐름

```
input.mp4
    ↓
audio.wav (16kHz, mono)
    ↓
transcription.json (타임스탬프 포함)
    ↓
translation_chunks.json (400자 단위 청크)
    ↓
quality_report_v2.json (2회 평가 평균 + 리파인 결과)
    ↓
segments/*.wav (TTS 오디오 - 자동/XTTS/Edge/11Labs)
    ↓
merged_audio.wav (Sync: Natural/Speed/Stretch)
    ↓
output.mp4
```
