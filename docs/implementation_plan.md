# VideoVoice - 로컬/API 옵션 확장 및 최적화 계획

## 프로젝트 개요

VideoVoice는 AI 기반 로컬 비디오 더빙 시스템입니다.
주요 사용 시나리오: **입력(영어/한국어/일본어) → 출력(러시아어/한국어)**

---

## 현재 아키텍처 (구현 완료)

```
📁 src/
├── config.py              # 환경변수 설정 관리 (TTS 엔진 설정 포함)
├── core/
│   ├── stt.py             # Faster-Whisper (로컬)
│   ├── translate.py       # Ollama/Groq (로컬+API, config.py 통일)
│   ├── tts.py             # TTSModule 통합 (XTTS/Edge/Silero)
│   ├── quality.py         # Gemini API (외부)
│   ├── pipeline.py        # 파이프라인 (TTS 엔진 자동 선택)
│   └── ffmpeg.py          # 비디오/오디오 처리
├── web/
│   ├── models.py          # TTSEngine enum + JobSettings.tts_engine
│   ├── routes.py          # tts_engine Form 파라미터 + 밸리데이션
│   └── manager.py         # Job 관리
📁 frontend/src/           # Gemini 담당
```

---

## 구현 완료 현황

| 기능 | 로컬 | API/서비스 | 선택 UI | 사용 파일 |
|------|:----:|:----------:|:-------:|-----------|
| STT | ✅ Faster-Whisper | ❌ | ❌ | `stt.py` |
| 번역 | ✅ Ollama | ✅ Groq | ✅ | `translate.py` |
| TTS | ✅ XTTS v2 | ✅ Edge TTS | ✅ | `tts.py` |
| TTS (러시아어) | ✅ Silero | ✅ Edge TTS | ✅ | `tts.py` |
| 품질검증 | ❌ | ✅ Gemini | ✅ | `quality.py` |

---

## TTS 엔진 동작 방식

### 자동 선택 로직 (`tts_engine=auto`)

| 조건 | 선택되는 엔진 |
|------|:------------:|
| `clone_voice=true` (어떤 언어든) | **XTTS v2** (음성복제) |
| `clone_voice=false` + 한국어 | **Edge TTS** |
| `clone_voice=false` + 러시아어 | **Edge TTS** |
| `clone_voice=false` + 영어 | **XTTS v2** |
| `clone_voice=false` + 일본어 | **XTTS v2** |
| `clone_voice=false` + 기타 | **Edge TTS** |

### 수동 선택

| 엔진 | 설명 | GPU 필요 | 음성복제 | 한국어 | 러시아어 |
|------|------|:--------:|:--------:|:------:|:--------:|
| `xtts` | XTTS v2 로컬 | ✅ | ✅ | 보통 | 보통 |
| `edge` | Microsoft Edge TTS | ❌ | ❌ | 우수 | 우수 |
| `silero` | Silero 로컬 | ❌ | ❌ | ❌ | 우수 |

### Edge TTS 기본 음성

| 언어 | 음성 ID | 성별 |
|------|---------|:----:|
| 한국어 | `ko-KR-SunHiNeural` | 여 |
| 러시아어 | `ru-RU-SvetlanaNeural` | 여 |
| 영어 | `en-US-AriaNeural` | 여 |
| 일본어 | `ja-JP-NanamiNeural` | 여 |

음성은 `.env`에서 `EDGE_TTS_VOICE_KO`, `EDGE_TTS_VOICE_RU` 등으로 변경 가능.

---

## 환경변수 (.env)

```env
# TTS Engine: "auto", "xtts", "edge", "silero"
VIDEOVOICE_TTS_ENGINE=auto

# Edge TTS 음성 설정 (선택적 - 기본값 있음)
# EDGE_TTS_VOICE_KO=ko-KR-SunHiNeural
# EDGE_TTS_VOICE_RU=ru-RU-SvetlanaNeural
# EDGE_TTS_VOICE_EN=en-US-AriaNeural
# EDGE_TTS_VOICE_JA=ja-JP-NanamiNeural
```

---

## 작업 완료 내역

| # | 작업 | 파일 | 상태 |
|---|------|------|:----:|
| 1 | TTS 엔진 설정 + Edge TTS 음성 맵 | `config.py` | ✅ |
| 2 | TTSModule 통합 클래스 (edge/xtts/silero) | `tts.py` | ✅ |
| 3 | TTSEngine enum + JobSettings 확장 | `models.py` | ✅ |
| 4 | tts_engine 파라미터 + 밸리데이션 | `routes.py` | ✅ |
| 5 | TTS 엔진 선택 + clone_voice 분기 | `pipeline.py` | ✅ |
| 6 | 환경변수 중복 제거 (config.py import) | `translate.py` | ✅ |
| 7 | TTS 환경변수 추가 | `.env` | ✅ |
| 8 | edge-tts 패키지 설치 | pip | ✅ |
| 9 | 미사용 빈 디렉토리 삭제 | src/audio,speech,transcribe,translate | ✅ |
| 10 | Edge TTS 한국어/러시아어 생성 테스트 | - | ✅ |

---

## 향후 확장 (미구현, 선택적)

- **ElevenLabs API** - 유료, 고품질 음성복제
- **OpenAI TTS** - 유료, 다국어
- **STT API 옵션** - Groq Whisper, OpenAI Whisper API
