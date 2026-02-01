# VideoVoice Frontend Design Request

## 1. 프로젝트 개요

**VideoVoice**는 로컬 환경에서 동작하는 다국어 비디오 음성 변환 시스템입니다.

- **GitHub**: https://github.com/Sakurayuki89/videovoice
- **목표**: 영상의 음성을 다른 언어로 자동 변환 (더빙)
- **환경**: Windows / RTX 3060 12GB / CUDA 12.1 / 완전 로컬 처리

---

## 2. 백엔드 파이프라인 (구현 완료)

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Video In   │────▶│  WhisperX   │────▶│   Ollama    │────▶│   XTTS v2   │
│   (MP4)     │     │    (STT)    │     │ (Translate) │     │    (TTS)    │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
                           │                   │                   │
                           ▼                   ▼                   ▼
                      텍스트 추출          EN → KO 번역        한국어 음성
```

### 핵심 컴포넌트

| 컴포넌트 | 기술 | 역할 | VRAM |
|---------|------|------|------|
| Audio Extraction | FFmpeg | 영상에서 오디오 추출 (16kHz, mono) | - |
| STT | WhisperX large-v3 | 음성 → 텍스트 (타임스탬프 포함) | ~3.5GB |
| Translation | Ollama + Qwen3:14b | 텍스트 번역 (EN↔KO↔RU 등) | ~9.3GB |
| TTS | XTTS v2 | 텍스트 → 음성 (화자 음색 유지) | ~3GB |
| Video Merge | FFmpeg | 새 오디오 트랙 삽입 | - |

### VRAM 관리 전략
- **순차 처리**: 한 모델 사용 후 메모리 해제 → 다음 모델 로드
- **try-finally 패턴**: 예외 발생 시에도 VRAM 해제 보장
- **최대 동시 VRAM**: ~10GB (RTX 3060 12GB에 적합)

---

## 3. 현재 구현 상태

### 완료된 항목 ✅
- [x] 환경 설정 (Python, CUDA, 모든 의존성)
- [x] 파이프라인 검증 스크립트 (`tests/pipeline_verify.py`)
- [x] 환경 체크 스크립트 (`scripts/check_env.py`)
- [x] 에러 처리 (타임아웃, 재시도, 입력 검증)
- [x] VRAM 누수 방지
- [x] 문서화 (AGENT_HANDOVER.md, ADR 등)

### 미구현 항목 ⬜
- [ ] `src/` 모듈화 (현재 테스트 코드에만 구현됨)
- [ ] Config 관리 (config.yaml)
- [ ] Logging 시스템
- [ ] **Frontend UI** ← 이번 요청

---

## 4. Frontend 설계 요청

### 4.1 요구사항

**목적**: 로컬에서 실행되는 웹 기반 UI로 파이프라인을 제어

**기술 스택 제안**:
- Backend API: FastAPI 또는 Flask
- Frontend:
  - Option A: Gradio (빠른 프로토타이핑)
  - Option B: Streamlit (데이터 중심 UI)
  - Option C: React + Vite (풀 커스텀)
- 로컬 서버: `localhost:8000` 또는 유사

### 4.2 필요한 UI 기능

#### 메인 페이지
1. **비디오 업로드**
   - 드래그 앤 드롭 또는 파일 선택
   - 지원 포맷: MP4, MKV, AVI
   - 파일 크기 / 길이 표시

2. **언어 설정**
   - 소스 언어 선택 (자동 감지 / 수동 선택)
   - 타겟 언어 선택 (KO, EN, RU 등)

3. **처리 옵션**
   - 화자 음색 유지 여부
   - 번역 품질 검증 활성화 (Gemini API)
   - 출력 형식 선택

#### 진행 상태 표시
```
[████████░░░░░░░░] 50% - 번역 중...

Step 1: 오디오 추출      ✅ 완료 (2.3s)
Step 2: 음성 인식        ✅ 완료 (15.2s)
Step 3: 번역             🔄 진행 중... (3/10 문장)
Step 4: 음성 합성        ⏳ 대기
Step 5: 비디오 병합      ⏳ 대기
```

#### 결과 페이지
- 원본 / 변환 영상 비교 재생
- 자막 미리보기 (타임스탬프 포함)
- 다운로드 버튼
- 번역 품질 점수 (선택적)

#### 시스템 상태 (사이드바 또는 별도 탭)
- GPU VRAM 사용량 실시간 모니터
- Ollama 서버 상태
- 처리 큐 현황

### 4.3 API 엔드포인트 설계 (제안)

```
POST /api/upload          - 비디오 업로드
POST /api/process         - 파이프라인 시작
GET  /api/status/{job_id} - 진행 상태 조회
GET  /api/result/{job_id} - 결과 다운로드
GET  /api/system/health   - 시스템 상태 (VRAM, Ollama 등)
POST /api/cancel/{job_id} - 작업 취소
```

### 4.4 디렉토리 구조 (제안)

```
videovoice/
├── src/
│   ├── api/              # FastAPI 라우터
│   │   ├── __init__.py
│   │   ├── routes.py
│   │   └── models.py     # Pydantic 스키마
│   ├── core/             # 파이프라인 로직
│   │   ├── stt.py
│   │   ├── translate.py
│   │   ├── tts.py
│   │   └── pipeline.py
│   └── utils/
│       ├── vram.py
│       └── config.py
├── frontend/             # React/Gradio/Streamlit
│   └── ...
├── static/               # 업로드/출력 파일
│   ├── uploads/
│   └── outputs/
└── main.py               # 서버 엔트리포인트
```

---

## 5. 설계 시 고려사항

### 제약 조건
1. **순차 처리 필수**: GPU 메모리 제한으로 동시 처리 불가
2. **긴 처리 시간**: 10분 영상 기준 수 분 소요 → 비동기 처리 + 상태 폴링 필요
3. **로컬 전용**: 외부 네트워크 노출 불필요

### 사용자 경험
1. 처리 중 브라우저 닫아도 백그라운드 계속 진행
2. 에러 발생 시 명확한 메시지와 재시도 옵션
3. 이전 처리 결과 히스토리 저장

### 확장성
1. 배치 처리 (여러 파일 큐잉)
2. 설정 프리셋 저장/불러오기
3. 자막 파일 별도 내보내기 (SRT)

---

## 6. 참고 파일

- `tests/pipeline_verify.py` - 파이프라인 전체 흐름 참고
- `scripts/check_env.py` - 시스템 상태 체크 로직
- `docs/AGENT_HANDOVER.md` - 프로젝트 전체 컨텍스트
- `docs/pipeline.md` - 8단계 파이프라인 상세

---

## 7. 요청 사항

1. **기술 스택 추천**: Gradio vs Streamlit vs React 중 이 프로젝트에 적합한 것
2. **UI/UX 와이어프레임**: 각 페이지 레이아웃 설계
3. **API 스키마 설계**: 요청/응답 형식 상세화
4. **디렉토리 구조 확정**: src/ 모듈화 포함
5. **구현 우선순위**: MVP → 확장 기능 로드맵

필요한 추가 정보가 있으면 말씀해주세요!
