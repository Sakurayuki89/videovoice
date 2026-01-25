# AI Agent Handover & Project Context

**Last Updated:** 2026-01-25 (Revised)
**Project:** VideoVoice (Local Multilingual Video Voice Transformation)
**Target Hardware:** RTX 3060 12GB / Windows / CUDA 12.1

---

## 1. Project Status Dashboard
> 현재 프로젝트가 어떤 상태인지 요약합니다. 작업 시작 전 반드시 확인하세요.

| Phase | Status | Details |
|-------|--------|---------|
| **Environment Setup** | ✅ **Done** | Python, CUDA, WhisperX, TTS, FFmpeg, Ollama 설치 완료 (Green Light) |
| **Core Module Impl** | ⬜ Ready | `src/` 구조 설계 및 모듈 구현 전 |
| **Integration** | ⬜ Pending | 파이프라인 통합 전 |
| **Optimization** | ⬜ Pending | 10~15분 영상 처리 최적화 전 |

**Current Focus**: `src/` 디렉토리 내 핵심 모듈(STT, Translation, TTS) 스켈레톤 코드 작성 및 단위 테스트.

---

## 2. Error & Resolution Log
> 개발 중 마주친 에러와 해결책을 기록하여 삽질을 방지합니다.

| Date | Type | Symptom (Error Msg) | Root Cause | Solution | Prevention |
|------|------|---------------------|------------|----------|------------|
| 2026-01-25 | 🔴 Critical | `pip install TTS` Build Error (`cl.exe` missing) | C++ Build Tools 누락 | VS Build Tools 2022 설치 (C++ Desktop Workload) | Env Check Script에 확인 로직 추가 불가능(OS레벨) |
| 2026-01-25 | 🔴 Critical | `torch.cuda.is_available() == False` | `pip install torch`는 기본적으로 CPU 버전 설치 | CUDA 12.1용 Torch 재설치 (`--index-url` 지정) | `check_env.py`에서 CUDA 검사 수행 |
| 2026-01-25 | 🟠 Major | `numpy.core.multiarray failed to import` | Numpy 2.0과 TTS(Scipy) 호환성 문제 | `pip install "numpy<2.0"`으로 다운그레이드 | `requirements.txt`에 버전 명시 필요 |

### 2.1 Code Review & Fixes (2026-01-25)

잠재적 오류 요인 검토 후 아래 항목들을 수정함:

| Priority | Issue | Fix Applied | File |
|----------|-------|-------------|------|
| 🔴 Critical | Ollama API 타임아웃 없음 → 무한 대기 가능 | `timeout=120` 추가 + `Timeout` 예외 처리 | `pipeline_verify.py:113` |
| 🔴 Critical | VRAM 누수 (예외 시 `del model` 미실행) | `finally` 블록으로 메모리 해제 보장 | `pipeline_verify.py:76-80, 170-174` |
| 🔴 Critical | Qwen3 `<think>` 태그가 번역 결과에 포함 | `strip_thinking_tags()` 함수 추가 | `pipeline_verify.py:82-87` |
| 🟠 Major | 재시도 로직 부재 | Exponential backoff 3회 재시도 (2s→4s→8s) | `pipeline_verify.py:90-145` |
| 🟠 Major | 필수 모델 검증 누락 | `qwen3:14b` 존재 여부 검사 + 설치 가이드 | `check_env.py:42-82` |
| 🟠 Major | 경로 하드코딩 | `PROJECT_ROOT`, `get_test_path()` 도입 | `pipeline_verify.py:10-17` |
| 🟠 Major | Speaker Reference 품질 경고 없음 | 더미 sine wave 사용 시 WARNING 출력 | `pipeline_verify.py:31` |
| 🟡 Minor | 에러 스택 트레이스 누락 | `traceback.print_exc()` 추가 | 각 except 블록 |
| 🟡 Minor | 입력 검증 없음 | `validate_file_exists()`, `validate_text()` 함수 추가 | `pipeline_verify.py:29-51` |
| 🟡 Minor | FFmpeg 에러 처리 미흡 | `FileNotFoundError`, `CalledProcessError` 개별 처리 | `pipeline_verify.py:76-86` |
| 🟡 Minor | VRAM 용량 검사 없음 | `check_cuda()`에 VRAM 용량 검증 추가 (8GB 미만 경고) | `check_env.py:26-36` |
| 🟡 Minor | WARNING 상태 색상 없음 | `print_status()`에 노란색(WARNING) 추가 | `check_env.py:12-13` |

---

## 3. Architecture Decision Records (ADR)
> 왜 이런 기술/구조를 선택했는지에 대한 의사결정 기록입니다.

### ADR-001: Sequential Processing vs Parallel Processing
- **Context**: 12GB VRAM 제약 하에서 STT(Whisper large-v3), LLM(Qwen 14b), TTS(XTTS)를 운용해야 함.
- **Decision**: **완전 순차 처리 (Fully Sequential)** 및 **Explicit VRAM Clearing**.
- **Rationale**: 
  - 세 모델을 동시에 올리면 VRAM 부족(OOM) 확정. (Whisper ~3GB, Qwen ~9GB, TTS ~3GB -> Total > 12GB)
  - 한 단계가 끝나면 `del model`, `gc.collect()`, `torch.cuda.empty_cache()`를 수행하여 메모리를 비운 후 다음 모델 로드.
- **Consequences**: 처리 속도는 느려지나 안정성 확보. 실시간 처리가 아닌 Offline Processing이므로 허용 가능.

### ADR-002: Translate Engine Selection (Ollama)
- **Context**: 로컬 LLM 구동을 위한 런타임 필요.
- **Decision**: **Ollama** 사용.
- **Rationale**: Python 라이브러리 직접 로드보다 프로세스 격리가 쉬워 VRAM 관리에 유리하며, REST API 래핑이 되어 있어 연동이 간편함.

### ADR-003: VRAM 해제 패턴 (try-finally)
- **Context**: 예외 발생 시 모델 객체가 삭제되지 않아 VRAM 누수 발생 가능.
- **Decision**: **try-finally 패턴** 적용. 모델 변수를 `None`으로 초기화 후, `finally` 블록에서 조건부 삭제.
- **Rationale**:
  - 예외 발생 여부와 관계없이 메모리 해제 보장.
  - Context manager (`with` 문) 대비 기존 코드 변경 최소화.
- **Pattern**:
  ```python
  model = None
  try:
      model = load_model()
      result = model.run()
      return result
  finally:
      if model is not None:
          del model
      clear_vram()
  ```

### ADR-004: API 재시도 전략 (Exponential Backoff)
- **Context**: 네트워크 일시 오류, Ollama 서버 과부하 시 즉시 실패하면 사용자 경험 저하.
- **Decision**: **3회 재시도 + Exponential Backoff (2초, 4초, 8초)**.
- **Rationale**:
  - 일시적 오류 복구 기회 제공.
  - 과도한 재시도로 인한 서버 부하 방지 (지수 증가 대기).
  - 총 최대 대기 시간: 14초 (2+4+8) + 요청 시간.
- **Consequences**: 최악의 경우 응답 시간 증가, 하지만 Offline Processing이므로 허용 가능.

---

## 4. Stability & Performance Metrics (To be filled)
> 실제 구동 데이터를 기록하여 안정성을 모니터링합니다.

| Component | VRAM Usage (Peak) | Processing Speed (RT Factor) | GPU Util | Notes |
|-----------|-------------------|------------------------------|----------|-------|
| WhisperX  | ~3.5 GB           | Fast                         | N/A      | Loaded 'large-v3' (float16). Sine wave input produced valid empty/noise result. |
| Qwen3:14b | ~9.3 GB (Ollama)  | Fast (Text-to-Text)          | N/A      | Successfully translated EN->KO via local API. |
| XTTS v2   | ~3 GB             | ~1.03x (RTF)                 | N/A      | Successfully generated KO audio. Sequential execution required. |

**Verification Result (2026-01-25)**: `tests/pipeline_verify.py` successfully completed the full loop (Input -> STT -> Translate -> TTS) on RTX 3060 12GB using sequential processing. VRAM was cleared effectively between steps.

**Code Review (2026-01-25)**: 잠재적 오류 요인 검토 완료. Critical 3건, Major 4건, Minor 5건 수정됨. 상세 내용은 섹션 2.1 참조.

---

## 5. Scalability & Tech Debt
> 확장성을 위한 인터페이스 변경이나 해결해야 할 기술 부채를 기록합니다.

### Resolved
- ✅ **Error Handling**: try-finally 패턴으로 VRAM 누수 방지 (ADR-003)
- ✅ **Retry Logic**: Exponential backoff 재시도 구현 (ADR-004)
- ✅ **Path Handling**: 절대 경로 사용으로 작업 디렉토리 독립성 확보
- ✅ **Model Validation**: `check_env.py`에서 필수 Ollama 모델 검증
- ✅ **Input Validation**: `validate_file_exists()`, `validate_text()` 함수로 입력 검증
- ✅ **VRAM Capacity Check**: `check_env.py`에서 GPU 메모리 용량 검사 (8GB 미만 경고)
- ✅ **Detailed Error Messages**: FFmpeg, Ollama 등 개별 에러 타입별 명확한 메시지

### Pending
- **[Pending] Config Management**: 현재 하드코딩된 설정값들이 존재할 수 있음. `config.yaml` 등으로 중앙화 필요.
- **[Pending] Logging System**: 단순 `print` 대신 `logging` 모듈을 통한 체계적인 파일 로깅 필요.
- **[Pending] Project Structure**: `src` 폴더 내부가 아직 비어있음. 표준 패키지 구조(`__init__.py` 등) 준수 필요.

---

## 6. How to Use This Document (For Agents)
1. 새로운 작업을 시작하기 전, **1. Project Status**와 **2. Error Log**를 읽고 컨텍스트를 로드하세요.
2. 중요한 기술적 결정(모델 변경, 라이브러리 교체 등)을 할 때는 **3. ADR**에 항목을 추가하세요.
3. 작업이 끝나면 완료된 내역을 바탕으로 각 섹션을 업데이트하세요.
