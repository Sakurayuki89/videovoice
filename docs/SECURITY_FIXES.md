# VideoVoice Security & Code Quality Fixes

**Date:** 2026-01-26
**Reviewed by:** Claude Code Analysis

이 문서는 VideoVoice 코드베이스에서 발견된 보안 취약점 및 코드 품질 문제와 그 수정 내용을 기록합니다.

---

## 목차

1. [Critical Severity (즉시 수정 필요)](#1-critical-severity)
2. [High Severity (중요)](#2-high-severity)
3. [Medium Severity (개선 필요)](#3-medium-severity)
4. [Low Severity (사소한 개선)](#4-low-severity)
5. [설정 파일](#5-설정-파일)
6. [사용 방법](#6-사용-방법)

---

## 1. Critical Severity

### 1.1 CORS 전체 허용 → 제한된 Origin만 허용

**파일:** `src/web/main.py`

**이전:**
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 도메인 허용 - CSRF 공격 가능
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**수정 후:**
```python
ALLOWED_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,  # 환경변수로 설정 가능
    allow_credentials=True,
    allow_methods=["GET", "POST"],  # 필요한 메서드만
    allow_headers=["Content-Type"],  # 필요한 헤더만
)
```

---

### 1.2 Path Traversal 취약점 → 파일명 검증

**파일:** `src/web/routes.py`

**이전:**
```python
file_path = os.path.join(UPLOAD_DIR, file.filename)  # 위험: ../../../etc/passwd 가능
```

**수정 후:**
```python
def sanitize_filename(filename: str) -> str:
    filename = os.path.basename(filename)  # 디렉토리 경로 제거
    filename = filename.replace("\x00", "")  # Null byte 제거
    name, ext = os.path.splitext(filename)
    safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', name)  # 안전한 문자만
    unique_prefix = uuid.uuid4().hex[:8]  # 충돌 방지
    return f"{unique_prefix}_{safe_name}{ext.lower()}"

# Defense in depth: 최종 경로 검증
abs_upload_dir = os.path.abspath(UPLOAD_DIR)
abs_file_path = os.path.abspath(file_path)
if not abs_file_path.startswith(abs_upload_dir):
    raise HTTPException(status_code=400, detail="Invalid file path")
```

---

### 1.3 파일 크기 무제한 → 500MB 제한

**파일:** `src/web/routes.py`

**수정 후:**
```python
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB

# 청크 단위로 읽으면서 크기 검증
total_size = 0
with open(file_path, "wb") as buffer:
    while chunk := await file.read(1024 * 1024):  # 1MB 청크
        total_size += len(chunk)
        if total_size > MAX_FILE_SIZE:
            os.remove(file_path)
            raise HTTPException(status_code=413, detail="File too large")
        buffer.write(chunk)
```

---

### 1.4 파일 타입 무검증 → 화이트리스트 검증

**파일:** `src/web/routes.py`

**수정 후:**
```python
ALLOWED_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm"}
ALLOWED_LANGUAGES = {"auto", "en", "ko", "ja", "ru", "zh", "es", "fr", "de"}

def validate_file_extension(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS

def validate_language(lang: str) -> bool:
    return lang in ALLOWED_LANGUAGES
```

---

### 1.5 Prompt Injection → 입력 새니타이즈

**파일:** `src/core/translate.py`

**수정 후:**
```python
def sanitize_input(self, text: str) -> str:
    # 길이 제한
    text = text[:self.MAX_TEXT_LENGTH]

    # 코드 블록 제거
    text = re.sub(r'```[\s\S]*?```', '[code block removed]', text)

    # Injection 패턴 필터링
    injection_patterns = [
        (r'(?i)ignore\s+(all\s+)?(previous|above)\s+instructions?', '[filtered]'),
        (r'(?i)disregard\s+(all\s+)?(previous|above)', '[filtered]'),
        (r'(?i)new\s+instructions?:', '[filtered]'),
        (r'(?i)system\s*:', '[filtered]'),
    ]
    for pattern, replacement in injection_patterns:
        text = re.sub(pattern, replacement, text)

    return text.strip()

# 컨텐츠 격리
prompt = f"""...
<content_to_translate>
{sanitized_text}
</content_to_translate>
Translation:"""
```

---

### 1.6 FFmpeg Command Injection → 경로 검증 및 타임아웃

**파일:** `src/core/ffmpeg.py`

**수정 후:**
```python
TIMEOUT_SECONDS = 600  # 10분

def _validate_path(self, path: str, must_exist: bool = True) -> bool:
    if "\x00" in path:  # Null byte
        return False
    if ".." in os.path.normpath(path).split(os.sep):  # Path traversal
        return False
    if re.search(r'[|;&$`]', os.path.basename(path)):  # Shell metacharacters
        return False
    return True

# 타임아웃 적용
subprocess.run(cmd, check=True, timeout=self.TIMEOUT_SECONDS, ...)

# 상세 에러 메시지
except subprocess.CalledProcessError as e:
    stderr_msg = e.stderr.decode('utf-8', errors='replace')
    print(f"FFmpeg Failed: {stderr_msg[:500]}")
```

---

## 2. High Severity

### 2.1 인증 없음 → API Key 인증

**파일:** `src/web/routes.py`

**수정 후:**
```python
AUTH_ENABLED = os.environ.get("VIDEOVOICE_AUTH_ENABLED", "false").lower() == "true"
API_KEYS = set(os.environ.get("VIDEOVOICE_API_KEYS", "dev-key").split(","))

async def verify_api_key(request: Request, api_key: str = Depends(API_KEY_HEADER)):
    if not AUTH_ENABLED:
        return
    if not api_key or api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API key")

@router.post("/jobs", dependencies=[Depends(verify_api_key)])
async def create_job(...):
```

**사용법:**
```bash
export VIDEOVOICE_AUTH_ENABLED=true
export VIDEOVOICE_API_KEYS=my-secret-key

curl -H "X-API-Key: my-secret-key" http://localhost:8000/api/jobs
```

---

### 2.2 Rate Limiting 없음 → IP 기반 제한

**파일:** `src/web/routes.py`

**수정 후:**
```python
RATE_LIMIT_REQUESTS = 10  # 분당 최대 요청 수
RATE_LIMIT_WINDOW = 60     # 윈도우 (초)

def check_rate_limit(request: Request) -> None:
    client_ip = get_client_ip(request)
    # IP별 요청 기록 및 제한 체크
    if len(requests) >= RATE_LIMIT_REQUESTS:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
```

---

### 2.3 CUDA 필수 → CPU 폴백 지원

**파일:** `src/core/stt.py`, `src/core/tts.py`

**수정 후:**
```python
class STTModule:
    def __init__(self, device: str = None):
        # 자동 감지
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        # CPU용 설정
        self.compute_type = "float16" if self.device == "cuda" else "int8"
        self.batch_size = 4 if self.device == "cuda" else 1

        if self.device == "cpu":
            print("WARNING: Running on CPU. This will be slower.")
```

---

### 2.4 Job ID 검증 없음 → UUID 형식 검증

**파일:** `src/web/routes.py`, `src/web/manager.py`

**수정 후:**
```python
def validate_job_id(job_id: str) -> str:
    try:
        parsed = uuid.UUID(job_id, version=4)
        return str(parsed)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")
```

---

## 3. Medium Severity

### 3.1 Job 취소 불가 → Cancel API 추가

**파일:** `src/web/routes.py`, `src/web/manager.py`, `src/core/pipeline.py`

**수정 후:**
```python
# routes.py
@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    success = job_manager.cancel_job(job_id)
    return {"message": "Job cancelled"}

# manager.py
def cancel_job(self, job_id: str) -> bool:
    self._cancelled.add(job_id)
    job["status"] = JobStatus.CANCELLED

def is_cancelled(self, job_id: str) -> bool:
    return job_id in self._cancelled

# pipeline.py
def _check_cancelled(self, job_id: str, job_manager):
    if job_manager.is_cancelled(job_id):
        raise PipelineCancelledException()
```

---

### 3.2 동시성 문제 → Thread Lock 적용

**파일:** `src/web/manager.py`

**수정 후:**
```python
class JobManager:
    def __init__(self):
        self._jobs: Dict[str, Dict] = {}
        self._lock = threading.RLock()

    def update_status(self, job_id: str, status: str):
        with self._lock:
            self._jobs[job_id]["status"] = status
```

---

### 3.3 로그 무제한 → 크기 제한

**파일:** `src/web/manager.py`

**수정 후:**
```python
MAX_LOGS_PER_JOB = 1000

def append_log(self, job_id: str, message: str):
    with self._lock:
        logs = self._jobs[job_id]["logs"]

        # 메시지 길이 제한
        if len(message) > 500:
            message = message[:500] + "..."

        # 로그 수 제한
        if len(logs) >= MAX_LOGS_PER_JOB:
            self._jobs[job_id]["logs"] = logs[100:]  # 오래된 10% 삭제

        self._jobs[job_id]["logs"].append({
            "timestamp": datetime.now(),
            "message": message
        })
```

---

### 3.4 빈 텍스트 처리 안됨 → 검증 추가

**파일:** `src/core/pipeline.py`

**수정 후:**
```python
# STT 결과 검증
text = stt.transcribe(temp_audio, language=source_lang)
if not text or not text.strip():
    raise PipelineStepError("transcribe", "No speech detected in the audio.")

# Translation 결과 검증
translated_text = translator.translate(text, source_lang, target_lang)
if not translated_text or not translated_text.strip():
    raise PipelineStepError("translate", "Translation returned empty result.")
```

---

### 3.5 출력 파일 경로 하드코딩 → Job에 저장

**파일:** `src/web/manager.py`, `src/core/pipeline.py`

**수정 후:**
```python
# manager.py
class JobResponse(BaseModel):
    output_file: Optional[str] = None  # 출력 파일 URL
    completed_at: Optional[datetime] = None

def set_output_file(self, job_id: str, output_file: str):
    self._jobs[job_id]["output_file"] = output_file

# pipeline.py
job_manager.set_output_file(job_id, f"/static/outputs/dubbed_{job_id}.mp4")
job_manager.set_completed(job_id)
```

---

### 3.6 프론트엔드 에러 처리 개선

**파일:** `frontend/src/services/api.js`

**수정 후:**
```javascript
api.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error.response) {
            switch (error.response.status) {
                case 400: throw new Error(data.detail || 'Invalid request');
                case 401: throw new Error('Authentication required');
                case 429: throw new Error('Rate limit exceeded');
                case 413: throw new Error('File too large');
            }
        } else if (error.request) {
            throw new Error('Network error. Check your connection.');
        }
    }
);
```

---

### 3.7 네트워크 재시도 로직

**파일:** `frontend/src/pages/Process.jsx`

**수정 후:**
```javascript
const MAX_RETRIES = 3;

const fetchStatus = async () => {
    try {
        const data = await getJob(jobId);
        setRetryCount(0);  // 성공 시 리셋
    } catch (err) {
        if (retryCount < MAX_RETRIES) {
            setRetryCount(prev => prev + 1);
        } else {
            setError(err.message);
        }
    }
};
```

---

## 4. Low Severity

### 4.1 System Status 링크 비활성 → 기능 구현

**파일:** `frontend/src/components/Layout.jsx`, `frontend/src/hooks/useSystemStatus.js`

**수정 후:**
```jsx
// useSystemStatus.js
export function useSystemStatus(autoRefresh = false) {
    const [status, setStatus] = useState(null);
    // GPU, VRAM, 활성 Job 정보 반환
    return { status, loading, error, refresh, isOnline };
}

// Layout.jsx - 클릭 시 상태 팝업
<SystemStatusPopup isOpen={showStatus} onClose={() => setShowStatus(false)} />
```

---

### 4.2 설정 하드코딩 → Config 파일 분리

**Backend:** `src/config.py`
```python
HOST = os.environ.get("VIDEOVOICE_HOST", "0.0.0.0")
PORT = int(os.environ.get("VIDEOVOICE_PORT", "8000"))
WHISPER_MODEL = os.environ.get("VIDEOVOICE_WHISPER_MODEL", "large-v3")
OLLAMA_HOST = os.environ.get("VIDEOVOICE_OLLAMA_HOST", "http://localhost:11434")
```

**Frontend:** `frontend/src/config.js`
```javascript
export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';
export const MAX_FILE_SIZE = 500 * 1024 * 1024;
export const JOB_POLL_INTERVAL = 2000;
export const LANGUAGES = { source: [...], target: [...] };
```

---

### 4.3 언어 매핑 불완전 → 18개 언어 지원

**파일:** `src/core/translate.py`

**수정 후:**
```python
LANGUAGE_NAMES = {
    "en": "English", "ko": "Korean", "ja": "Japanese",
    "zh": "Chinese", "ru": "Russian", "es": "Spanish",
    "fr": "French", "de": "German", "it": "Italian",
    "pt": "Portuguese", "nl": "Dutch", "pl": "Polish",
    "tr": "Turkish", "vi": "Vietnamese", "th": "Thai",
    "ar": "Arabic", "hi": "Hindi", "auto": "detected language",
}
```

---

### 4.4 Start Script 개선

**파일:** `scripts/start_app.py`

**수정 후:**
```python
# 사전 조건 확인
def check_command_exists(command: str) -> bool
def is_port_in_use(port: int) -> bool

# npm 의존성 자동 설치
if not os.path.exists(node_modules):
    subprocess.run(["npm", "install"], ...)

# 우아한 종료
try:
    backend.wait()
except KeyboardInterrupt:
    backend.terminate()
    frontend.terminate()
```

---

### 4.5 Python 패키지 구조 정리

```
src/
├── __init__.py          # 패키지 버전
├── config.py            # 중앙 설정
├── core/
│   ├── __init__.py      # 모듈 export
│   └── utils/
│       └── __init__.py
└── web/
    └── __init__.py
```

---

## 5. 설정 파일

### Backend (`.env`)
```bash
# Server
VIDEOVOICE_HOST=0.0.0.0
VIDEOVOICE_PORT=8000

# Security
VIDEOVOICE_AUTH_ENABLED=true
VIDEOVOICE_API_KEYS=your-api-key-here
CORS_ORIGINS=http://localhost:5173

# Rate Limiting
VIDEOVOICE_RATE_LIMIT=10
VIDEOVOICE_RATE_WINDOW=60

# AI Models
VIDEOVOICE_WHISPER_MODEL=large-v3
VIDEOVOICE_OLLAMA_HOST=http://localhost:11434
VIDEOVOICE_OLLAMA_MODEL=qwen3:14b

# File Limits
VIDEOVOICE_MAX_FILE_SIZE=524288000
```

### Frontend (`.env`)
```bash
VITE_API_URL=http://localhost:8000/api
VITE_API_KEY=your-api-key-here
```

---

## 6. 사용 방법

### 기본 실행
```bash
python scripts/start_app.py
```

### 프로덕션 실행 (인증 활성화)
```bash
export VIDEOVOICE_AUTH_ENABLED=true
export VIDEOVOICE_API_KEYS=secure-key-1,secure-key-2
python scripts/start_app.py
```

### API 호출 (인증 필요 시)
```bash
curl -X POST http://localhost:8000/api/jobs \
  -H "X-API-Key: secure-key-1" \
  -F "file=@video.mp4" \
  -F "source_lang=en" \
  -F "target_lang=ko"
```

---

## 수정된 파일 목록

| 파일 | 변경 내용 |
|------|----------|
| `src/web/main.py` | CORS 제한, 실제 시스템 상태 API |
| `src/web/routes.py` | 인증, Rate Limiting, 입력 검증, Cancel API |
| `src/web/manager.py` | Thread Lock, 로그 제한, 취소 기능 |
| `src/web/models.py` | LogEntry, output_file, completed_at 추가 |
| `src/core/pipeline.py` | 취소 확인, 에러 처리, 출력 파일 설정 |
| `src/core/stt.py` | CPU 폴백, 입력 검증, Config 지원 |
| `src/core/tts.py` | CPU 폴백, 입력 검증, Config 지원 |
| `src/core/translate.py` | Prompt Injection 방어, 언어 확장 |
| `src/core/ffmpeg.py` | 경로 검증, 타임아웃, 에러 처리 |
| `src/core/utils/vram.py` | CUDA 체크, 디바이스 정보 |
| `src/config.py` | 중앙 설정 (신규) |
| `src/__init__.py` | 패키지 초기화 (신규) |
| `scripts/start_app.py` | 에러 처리, 의존성 확인 |
| `frontend/src/config.js` | 프론트엔드 설정 (신규) |
| `frontend/src/services/api.js` | 에러 처리, Config 사용 |
| `frontend/src/pages/Home.jsx` | 파일 검증, Config 사용 |
| `frontend/src/pages/Process.jsx` | 취소 기능, 재시도 로직 |
| `frontend/src/pages/Result.jsx` | 출력 URL 동적 처리 |
| `frontend/src/components/Layout.jsx` | System Status 팝업 |
| `frontend/src/hooks/useSystemStatus.js` | 상태 Hook (신규) |
| `.env.example` | 환경변수 예제 (신규) |
| `frontend/.env.example` | 프론트엔드 환경변수 (신규) |
