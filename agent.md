# Agent Specification: Local Multilingual Video Voice Transformation (KO / EN / RU)

## 1. Project Overview

본 프로젝트는 로컬 AI 환경(RTX 3060 12GB 기준)에서
10~15분 길이의 동영상을 입력으로 받아,
영상 편집 툴 없이 원본 음성을 완전히 제거하고
선택한 대상 언어(한국어, 영어, 러시아어) 음성으로 자동 변환하여
새로운 영상 파일(mp4)을 출력하는 것을 목표로 한다.

립싱크는 요구하지 않으며,
Audio Track Replacement(음성 트랙 교체) 방식을 사용한다.

**현재 상태**: 로컬 처리와 클라우드 API를 모두 지원하는 하이브리드 모드로 발전
- 로컬 전용 모드 지원 (Ollama + WhisperX + XTTS)
- 클라우드 API 선택 모드 지원 (Groq, OpenAI, ElevenLabs 등)
- 사용자가 UI에서 엔진 선택 가능

---

## 2. Supported Languages

### 2.1 Input Languages
- Korean (ko)
- English (en)
- Russian (ru)
- Japanese (ja)
- Chinese (zh)
- Auto-detect (자동 감지)

### 2.2 Output Languages
- Korean (ko)
- English (en)
- Russian (ru)
- Japanese (ja)
- Chinese (zh)
- German (de)
- French (fr)
- Spanish (es)
- Italian (it)
- Portuguese (pt)

입력 언어와 출력 언어는 동일할 수도 있고 상이할 수도 있다.

---

## 3. Current Architecture & Tech Stack

### 3.1 Backend (Python FastAPI)
- **Framework**: FastAPI
- **Location**: `src/web/main.py`, `src/web/routes.py`
- **Job Manager**: `src/web/manager.py` - 비동기 작업 관리
- **Port**: 8000 (기본값)
- **CORS**: 5173/5174 자동 포함 + `.env` CORS_ORIGINS 병합

### 3.2 Frontend (React + Vite)
- **Framework**: React 19.2.0
- **Build Tool**: Vite 7.2.4
- **Routing**: React Router DOM 7.13.0
- **Port**: 5173 (개발 서버)
- **Main Pages**:
  - `Home.jsx`: 파일 업로드 및 설정
  - `Process.jsx`: 실시간 진행 상황
  - `Result.jsx`: 결과 확인 및 다운로드

### 3.3 Recent UI Improvements (2026-02-01)
- ✅ 라디오 버튼 → 체크마크 스타일로 변경
- ✅ 선택 항목에 강한 glow 효과 및 scale 애니메이션
- ✅ 옵션 간 명확한 경계선(border-2) 추가
- ✅ 추천 설정 자동 적용 시스템 (언어 쌍 기반)
- ✅ 표 형식 레이아웃으로 정렬 개선
- ✅ 음성 추출 없이 바로 더빙 시작 가능 (서버 측 추출)
- ✅ 크로스 오리진 다운로드/재생 수정 (FileResponse + blob URL)

---

## 4. AI Engine Configuration

### 4.1 STT (Speech-to-Text) Engines

#### Local Option
- **WhisperX** (large-v3)
  - GPU 필요 (RTX 3060 12GB)
  - 최고 정확도 (한국어, 일본어, 중국어 특화)
  - 타임스탬프 정렬 자동화

#### Cloud Options
- **Groq API**
  - whisper-large-v3
  - 초고속 처리
  - API 키 필요: `GROQ_API_KEY`
  
- **OpenAI API**
  - whisper-1
  - 최고 정확도
  - API 키 필요: `OPENAI_API_KEY`

**현재 설정**: `.env`의 `VIDEOVOICE_STT_ENGINE` 또는 UI에서 선택

### 4.2 Translation Engines

#### Local Option
- **Ollama + Qwen3** (14B)
  - 모델: qwen3:14b
  - 호스트: http://localhost:11434
  - 완전 로컬 처리
  - 무료

#### Cloud Options
- **Gemini 2.5 Flash** ⭐ 기본 추천
  - 최고 품질 다국어 번역
  - API 키: `.env`의 `GEMINI_API_KEY` 참조
  - 429 에러 시 Groq 자동 폴백
  - 청크 단위 번역 (400자 타겟)
  - Few-shot 예시 포함 (KO/EN/RU)

- **Groq API**
  - llama-3.3-70b-versatile
  - 초고속 번역
  - API 키: `.env`의 `GROQ_API_KEY` 참조

### 4.3 TTS (Text-to-Speech) Engines

#### Local Options
- **XTTS v2**
  - 음성 복제 지원
  - 다국어 지원
  - GPU 필요
  
- **Edge TTS**
  - 한국어 최고 품질
  - 무료, 빠름
  - 음성: ko-KR-SunHiNeural
  
- **Silero**
  - 러시아어 특화
  - 초고속

#### Cloud Options
- **ElevenLabs**
  - API 키: `.env`의 `ELEVENLABS_API_KEY` 참조
  - 모델: eleven_multilingual_v2
  - 최상급 음질 및 음성 복제
  - 사용량 제한 있음
  
- **OpenAI TTS**
  - tts-1, tts-1-hd
  - 자연스러움
  - API 키 필요

**자동 추천 시스템**:
- ElevenLabs 키가 있으면 최우선 추천
- 한국어: Edge TTS
- 러시아어: Silero
- 음성 복제 ON: XTTS v2 또는 ElevenLabs

### 4.4 Quality Validation (Optional)
- **Gemini 2.5 Flash**
  - API 키: `.env`의 `GEMINI_API_KEY` 참조
  - 용도: 번역 품질 검증 (verify_translation 옵션)
  - **4단계 신뢰성 시스템**:
    1. 2회 평가 평균 (temperature 0.1, 점수 분산 ±2~3%)
    2. 리파인 전후 핵심 용어 보존율 체크 (숫자/고유명사 30%+ 소실 시 거부)
    3. 엄격한 채점 기준 (가중치 공식 명시, 불완전 문장 패널티)
    4. 잘린 JSON 자동 복구 (Gemini 출력 truncation 대응)
  - **품질 게이트**: 85% 최소 기준, 3라운드 번역→평가→리파인 루프
  - **비용**: 약 30~40원/10분 영상 (2회 평가 포함)

---

## 5. Core Processing Pipeline

```
1. 비디오 입력 (.mp4, .mkv, .avi, .mov, .webm 등)
   ↓
2. 오디오 추출 (FFmpeg) - 클라이언트 또는 서버
   ↓
3. STT (음성 → 텍스트)
   - Local: WhisperX large-v3
   - Cloud: Groq, OpenAI
   ↓
4. 청크 단위 번역 (400자 타겟)
   - Local: Ollama + Qwen3
   - Cloud: Gemini 2.5 Flash (기본), Groq API
   - Few-shot 예시 포함
   - 429 에러 시 Gemini → Groq 자동 폴백
   ↓
5. (선택) 4단계 품질 검증 (Gemini)
   - 2회 평가 평균 (temperature 0.1)
   - 85% 미달 시 청크 단위 리파인 → 재평가 (최대 3라운드)
   - 핵심 용어 보존율 체크
   ↓
6. TTS (텍스트 → 음성)
   - Local: XTTS, Edge TTS, Silero
   - Cloud: ElevenLabs, OpenAI
   ↓
7. 오디오 병합 + 싱크 조절
   - optimize: 자연스러운 속도
   - speed_audio: 영상 길이에 맞춤
   - stretch: 영상 속도 조절
   ↓
8. 비디오 재합성 (FFmpeg)
   ↓
9. 결과 다운로드 (.mp4)
```

---

## 6. Sync Mode Options

### 6.1 자연스러운 속도 (Natural)
- 원래 말하기 속도 유지
- 오디오가 짧으면 뒷부분이 비거나 싱크 불일치 가능
- 아이콘: Film

### 6.2 영상 길이에 맞춤 (Speed Sync) ⭐ 기본 추천
- 오디오 전체 길이를 영상에 강제로 맞춤
- 대화가 끊이지 않는 영상에 최적
- 아이콘: Gauge

### 6.3 영상 속도 조절 (Video Stretch)
- 영상을 느리게 재생해 음성 길이에 맞춤
- 아이콘: Clock

**추천 로직**:
- 기본값: `speed_audio` (무음 방지)
- 언어 쌍에 따라 자동 조정

---

## 7. Environment Variables (.env)

### 7.1 Server
```bash
VIDEOVOICE_HOST=0.0.0.0
VIDEOVOICE_PORT=8000
VIDEOVOICE_DEBUG=false
VIDEOVOICE_AUTH_ENABLED=true
VIDEOVOICE_API_KEYS=<your-api-keys>
```

### 7.2 AI APIs
```bash
# Gemini (품질 검증)
GEMINI_API_KEY=<your-gemini-api-key>
GEMINI_MODEL=gemini-2.5-flash

# Groq (번역/STT)
GROQ_API_KEY=<your-groq-api-key>
GROQ_MODEL=llama-3.3-70b-versatile

# ElevenLabs (TTS)
ELEVENLABS_API_KEY=<your-elevenlabs-api-key>
ELEVENLABS_MODEL=eleven_multilingual_v2

# OpenAI (STT/TTS)
OPENAI_API_KEY=<your-openai-api-key>
```

### 7.3 Local Models
```bash
# WhisperX
VIDEOVOICE_WHISPER_MODEL=large-v3
VIDEOVOICE_WHISPER_BATCH=4
VIDEOVOICE_WHISPER_COMPUTE=float16

# Ollama
VIDEOVOICE_OLLAMA_HOST=http://localhost:11434
VIDEOVOICE_OLLAMA_MODEL=qwen3:14b
VIDEOVOICE_OLLAMA_TIMEOUT=120

# TTS
VIDEOVOICE_TTS_ENGINE=auto
VIDEOVOICE_TTS_MODEL=tts_models/multilingual/multi-dataset/xtts_v2
```

---

## 8. File Locations

### 8.1 Backend Core
- `src/core/stt.py` - STT 엔진 통합
- `src/core/tts.py` - TTS 엔진 통합
- `src/core/translate.py` - 번역 엔진 (Gemini/Groq/Ollama, 청크 번역/리파인)
- `src/core/quality.py` - 번역 품질 검증 (2회 평가 평균, 잘린 JSON 복구)
- `src/core/pipeline.py` - 전체 파이프라인 오케스트레이션 (품질 게이트, 용어 보존 체크)
- `src/core/translation_cache.py` - 번역 캐시 (품질 점수 포함, 저품질 무효화)
- `src/config.py` - 환경 설정 로드

### 8.2 Frontend
- `frontend/src/pages/Home.jsx` - 메인 업로드 및 설정 페이지
- `frontend/src/pages/Process.jsx` - 실시간 진행 상황
- `frontend/src/pages/Result.jsx` - 결과 화면
- `frontend/src/utils/audioExtractor.js` - FFmpeg.wasm 오디오 추출
- `frontend/src/hooks/useSystemStatus.js` - 시스템 상태 확인

### 8.3 Static Files
- `static/` - 처리된 비디오 결과물 저장

---

## 9. Current Settings Summary (as of 2026-02-01)

### 9.1 Configured APIs
- ✅ Gemini Pro (품질 검증)
- ✅ Groq (번역/STT)
- ✅ ElevenLabs (TTS)
- ❌ OpenAI (미설정)

### 9.2 Default Engines
- **STT**: Groq (`.env`에서 설정)
- **Translation**: Gemini 2.5 Flash 우선 (429 시 Groq 폴백), Ollama 대체
- **TTS**: Auto (ElevenLabs 우선 → 언어별 최적 선택)
- **Quality**: Gemini 2.5 Flash (2회 평가 평균, 85% 게이트)

### 9.3 UI Features
- 체크마크 스타일 옵션 선택
- 언어별 추천 엔진 자동 표시
- 실시간 진행 상황 추적
- 결과 미리보기 및 다운로드

---

## 10. Hardware Constraints

- GPU: RTX 3060 12GB
- RAM: 64GB
- Storage: Local SSD
- Execution Mode: Hybrid (Local + Cloud API)

---

## 11. Development Commands

### 11.1 Backend
```bash
# 가상환경 활성화
c:\code\videovoice\venv\Scripts\activate

# 서버 실행
python -m uvicorn src.web.main:app --reload

# 또는
c:\code\videovoice\venv\Scripts\python -m uvicorn src.web.main:app --reload
```

### 11.2 Frontend
```bash
cd frontend
npm run dev
```

### 11.3 Ollama (로컬 번역)
```bash
ollama serve
ollama run qwen3:14b
```

---

## 12. Known Issues & Solutions

### 12.1 브라우저 환경 변수 문제
- 증상: `$HOME environment variable is not set`
- 영향: 브라우저 자동화 도구 실패
- 해결: 수동으로 브라우저에서 http://localhost:5173 접속

### 12.2 FFmpeg.wasm 메모리 이슈
- 증상: 대용량 파일(>500MB) 처리 시 메모리 부족
- 해결: 서버 측 오디오 추출 사용 또는 파일 크기 제한

---

## 13. For Claude Desktop Users

### 13.1 Quick Context
프로젝트 상태를 빠르게 파악하려면:
1. `.env` 파일에서 현재 API 키 확인
2. `frontend/src/pages/Home.jsx`에서 UI 로직 확인
3. `src/core/pipeline.py`에서 전체 플로우 확인

### 13.2 Common Tasks
- UI 수정: `frontend/src/pages/` 디렉토리
- 엔진 추가/수정: `src/core/` 디렉토리
- 설정 변경: `.env` 파일
- 추천 로직 수정: `frontend/src/pages/Home.jsx`의 `getRecommendedSettings` 함수

### 13.3 Testing
- Backend: http://127.0.0.1:8000/docs (Swagger UI)
- Frontend: http://localhost:5173
- System Status: http://127.0.0.1:8000/api/system/status

---

## 14. Validation Checklist

- [x] 입력 언어 자동 감지 정상
- [x] STT 타임스탬프 정상
- [x] 번역 의미 왜곡 없음
- [x] TTS 음색 변화 없음
- [x] 오디오 길이 과도한 불일치 없음
- [x] 원본 음성 완전 제거 확인
- [x] UI 직관성 개선 (체크마크 스타일)
- [x] 추천 엔진 자동 선택 기능

---

## 15. Backup & Restore Points

### v1.0-stable (2026-02-01) ⭐ 완성본 백업
- **커밋**: `bb0691c`
- **태그**: `v1.0-stable`
- **내용**: Gemini 번역 + 4단계 품질 신뢰성 시스템
- **품질 결과**: KO→RU 의학 콘텐츠 10분 영상 88% (정확도 90%, 자연스러움 88%, 더빙 적합성 85%, 일관성 92%)
- **주요 기능**:
  - Gemini 2.5 Flash 번역 (Groq 자동 폴백)
  - 청크 단위 번역/리파인 (400자 타겟)
  - 2회 평가 평균 (temperature 0.1)
  - 핵심 용어 보존율 체크
  - 잘린 JSON 자동 복구
  - 85% 품질 게이트 (3라운드)
  - Few-shot 번역 예시
  - 크로스 오리진 다운로드/재생 수정
  - CORS 동적 포트 지원

**복원 명령어:**
```bash
# 이 버전으로 복원 (읽기 전용)
git checkout v1.0-stable

# 현재 브랜치를 이 시점으로 되돌리기
git reset --hard v1.0-stable

# 태그 목록 확인
git tag -l
```

---

## 16. Next Plan: 화자 분리(Speaker Diarization) + XTTS 다중 화자 복제

### 16.0 배경 및 동기 (로컬 vs 클라우드 비교)
완전 로컬 파이프라인(WhisperX + Ollama + XTTS)의 도입을 위한 비용 및 품질 분석입니다.

**비용 비교 (10분 영상 기준)**
| 항목 | 현재 (클라우드 하이브리드) | 완전 로컬 전용 |
| :--- | :--- | :--- |
| **STT** | Groq API (무료 한도) | WhisperX (무료) |
| **번역** | Gemini (~40원) | Ollama (무료) |
| **품질검증** | Gemini (~20원) | 없음 (또는 Ollama) |
| **TTS** | ElevenLabs (유료 한도) | XTTS (무료) |
| **총 비용** | **약 60원** | **0원** |

**로컬 전용 모드 단점 및 고려사항**
| 항목 | 영향 및 내용 |
| :--- | :--- |
| **번역 품질** | Ollama (Qwen3 14B)는 Gemini 대비 품질이 낮음 (약 80-85% 수준) |
| **처리 시간** | 10분 영상 기준 약 30~40분 소요 (GPU 풀가동 필요) |
| **VRAM 관리** | WhisperX와 XTTS 동시 로드 불가 → 순차적 로드/언로드 필수 |
| **TTS 품질** | XTTS는 ElevenLabs 대비 일본어/한국어 자연스러움이 다소 부족함 |
| **구현 난이도** | 화자 분리 및 세그먼트별 음성 복제 로직 구현 필요 |

**결론**
효율성은 극대화되나 품질 타협이 필요합니다. 따라서 **최고 품질(Gemini/ElevenLabs)**과 **완전 무료(WhisperX/XTTS)** 옵션을 사용자가 선택할 수 있도록 하이브리드 구조를 유지하며 화자 분리 기능을 추가합니다.

### 16.1 목표
영상 내 여러 화자를 자동 분리하여 각 화자의 음색을 개별 복제, 더빙 시 화자별 목소리를 유지하는 기능 구현.

### 16.2 구현 흐름
```
1. WhisperX STT + diarization
   → 텍스트 + 타임스탬프 + 화자 라벨 (SPEAKER_00, SPEAKER_01, ...)
   ↓
2. 화자별 음성 샘플 추출
   → 각 화자의 발화 구간에서 6~15초 참조 음성 추출 (FFmpeg)
   → static/uploads/{job_id}_speaker_00.wav, _speaker_01.wav ...
   ↓
3. 화자별 번역 세그먼트 구성
   → 화자 라벨 유지하며 청크 단위 번역
   → [{speaker: "SPEAKER_00", text: "...", start: 0.0, end: 5.2}, ...]
   ↓
4. 화자별 XTTS 음성 생성
   → SPEAKER_00 세그먼트 → XTTS(speaker_wav=speaker_00.wav)
   → SPEAKER_01 세그먼트 → XTTS(speaker_wav=speaker_01.wav)
   → VRAM 관리: 화자 전환 시 모델 재로드 불필요 (speaker_wav만 교체)
   ↓
5. 타임라인 병합
   → 각 세그먼트를 원본 타임스탬프에 맞춰 배치
   → 구간 사이 무음 삽입 (silence padding)
   → FFmpeg로 최종 오디오 트랙 생성
   ↓
6. 비디오 재합성 (기존 merge 로직 재사용)
```

### 16.3 수정 대상 파일
| 파일 | 변경 내용 |
|------|----------|
| `src/core/stt.py` | WhisperX diarization 옵션 추가 (`diarize=True` 파라미터) |
| `src/core/pipeline.py` | 화자별 세그먼트 처리 루프, 화자 샘플 추출 로직 |
| `src/core/tts.py` | 세그먼트 단위 TTS 생성 메서드 추가 |
| `src/core/ffmpeg.py` | 화자별 음성 샘플 추출, 타임라인 기반 오디오 병합 |
| `src/web/models.py` | `diarize` 옵션 추가 (JobSettings) |
| `src/web/routes.py` | `diarize` 폼 파라미터 추가 |
| `frontend/src/pages/Home.jsx` | 화자 분리 ON/OFF 체크박스 추가 |

### 16.4 기술 요구사항
- **WhisperX diarization**: `pyannote/speaker-diarization-3.1` 모델 필요
  - HuggingFace 토큰 필요 (`HF_TOKEN` 환경변수)
  - 최초 실행 시 모델 다운로드 (~600MB)
- **VRAM 관리**: WhisperX(~4GB) → 언로드 → XTTS(~4GB) 순차 로드
  - RTX 3060 12GB로 충분
- **최적 참조 음성**: 화자당 6~15초 (너무 짧으면 복제 품질 저하)
  - 발화 구간이 6초 미만인 화자는 여러 구간 연결

### 16.5 제약사항 및 고려사항
- 화자 수 제한: 2~4명 권장 (5명 이상은 분리 정확도 저하)
- 화자 분리 정확도: 90%+ (대화 겹침 없는 경우)
- 겹치는 발화(overlap): 현재 미지원, 긴 쪽 화자에 할당
- 처리 시간 증가: 10분 영상 기준 +5~10분 (diarization + 화자별 TTS)
- 완전 무료 로컬 파이프라인과 결합 가능 (WhisperX + Ollama + XTTS = 0원)

### 16.6 구현 우선순위
1. **Phase 1**: WhisperX diarization 통합 (STT에서 화자 라벨 반환)
2. **Phase 2**: 화자별 참조 음성 자동 추출
3. **Phase 3**: 세그먼트 단위 XTTS 생성 + 타임라인 병합
4. **Phase 4**: UI 옵션 추가 + 테스트

### 16.7 예상 비용 (완전 로컬)
| 항목 | 비용 |
|------|------|
| WhisperX + diarization | 0원 (GPU) |
| Ollama 번역 | 0원 |
| XTTS 화자별 복제 | 0원 (GPU) |
| **합계** | **0원** |

---

## 17. Bug Fixes & Code Quality Improvements (2026-02-03)

### 17.1 수정 완료 목록 (9건)

| # | 우선순위 | 파일 | 수정 내용 |
|---|----------|------|-----------|
| 1 | Critical | `pipeline.py` | STT 완료 후 `clear_vram("STT-to-TTS")` 호출하여 GPU 메모리 해제 |
| 2 | Critical | `quality.py` | Gemini quota 초과 시 Groq API로 자동 fallback (`_fallback_groq_evaluate`) |
| 3 | Critical | `tts.py` | TTS concat 실패 시 silent fallback 대신 `RuntimeError` 발생 |
| 4 | Medium | `pipeline.py` | 자막 번역 재시도 시 하드코딩된 `"optimize"` → `job.settings.sync_mode` 사용 |
| 5 | Medium | `config.py` + `subtitle.py` | `SUBTITLE_BATCH_THRESHOLD` 환경변수 추가 (기본 60%) |
| 6 | Medium | `stt.py` | Gemini STT JSON 파싱 실패 시 더미 세그먼트 대신 빈 segments 반환 |
| 7 | Medium | `tts.py` | ElevenLabs 음성 삭제 실패 로깅 (이미 구현됨) |
| 8 | Low | `quality.py` | 10,000자 초과 텍스트 앞/중/뒤 샘플링 (`_sample_long_text`) |
| 9 | Low | `translate.py` | Groq 429 에러 명시적 처리 및 안내 메시지 |

### 17.2 새로 추가된 환경변수

```bash
# 자막 배치 번역 성공률 임계값 (0-100, 기본 60%)
VIDEOVOICE_SUBTITLE_BATCH_THRESHOLD=60
```

### 17.3 주요 변경 사항

#### VRAM 관리 개선 (#1)
```python
# pipeline.py - STT 완료 후
from .utils.vram import clear_vram
clear_vram("STT-to-TTS")
```

#### 품질 검증 Fallback (#2, #8)
- Gemini quota 초과 (429) 감지 → Groq API fallback
- 긴 텍스트 샘플링: 앞 3,333자 + 중간 3,333자 + 뒤 3,333자

#### TTS 안정성 (#3)
- 청크 concat 실패 시 부분 오디오 사용 금지
- `RuntimeError` 발생하여 파이프라인에서 명확한 에러 처리

### 17.4 검증 상태
- ✅ 모든 파일 Python 구문 검증 통과
- ✅ 서버 `--reload` 자동 리로드 완료

---

**Last Updated**: 2026-02-03
**Version**: 2.2 (Bug Fixes + Code Quality)
**Status**: Production Ready - Stable
**Next**: Speaker Diarization + Multi-voice XTTS (Phase 1~4)
