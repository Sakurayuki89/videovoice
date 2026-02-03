# 문제 해결 가이드

VideoVoice 실행 중 자주 발생하는 문제와 해결 방법입니다.

## API 관련 문제

### Gemini 429 (Resource Exhausted)
- **증상**: `ResourceExhausted: 429` 에러 발생하며 검증 실패
- **원인**: Gemini 무료 티어 할당량 초과
- **자동 해결**: 시스템이 자동으로 **Groq API**로 폴백(Fallback)하여 처리를 계속합니다.
- **수동 해결**: `.env`에서 `GROQ_API_KEY`가 올바르게 설정되었는지 확인하세요.

### ollama 연결 실패
- **증상**: `Connection refused`
- **해결**: `ollama serve`가 백그라운드에서 실행 중인지 확인하세요.

## 프론트엔드/브라우저 문제

### 파일 다운로드 실패 (CORS)
- **증상**: 결과 다운로드 버튼 클릭 시 반응 없음
- **해결**: 최신 버전(2026-02-01)에서 `Blob URL` 방식으로 수정되었습니다. 
  - 개발자 도구(F12) > Console에서 에러 메시지 확인
  - 백엔드 CORS 설정에 `localhost:5173` 포함 여부 확인

### 브라우저 자동화 에러 ($HOME not set)
- **증상**: `$HOME environment variable is not set`
- **해결**: 브라우저 자동화 도구 대신 직접 Chrome/Edge를 열고 `http://localhost:5173`에 접속하세요.

## AI 품질/성능 문제

### VRAM 부족 (CUDA out of memory)
- **증상**: WhisperX 또는 XTTS 실행 중 프로세스 종료
- **해결**:
  1. `config.py`에서 `WHISPER_BATCH_SIZE=4`로 감소
  2. 로컬 LLM(Ollama) 대신 클라우드 API(Groq/Gemini) 사용 권장

### 번역 품질 저하
- **증상**: 직역투 이거나 용어가 틀림
- **해결**: 
  - `.env`에서 `VIDEOVOICE_GEN_ENGINE=gemini` 설정 확인
  - 품질 검증 로그(`quality_report.json`) 확인

### 오디오 싱크 불일치
- **증상**: 입모양과 소리가 안 맞음
- **해결**: UI 설정에서 `Sync Mode`를 **Speed Sync** (영상 길이에 맞춤)로 변경하세요. 자연스러운 속도(Natural) 모드는 오디오가 짧을 경우 뒤가 빌 수 있습니다.

## 일반 디버깅

```bash
# 실시간 로그 확인
export VIDEOVOICE_DEBUG=true
python -m uvicorn src.web.main:app

# GPU 사용량 모니터링
nvidia-smi -l 1
```
