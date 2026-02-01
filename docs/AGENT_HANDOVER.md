# VideoVoice 더빙 비디오 출력 문제 수정 요청

## 현재 상황

VideoVoice는 AI 기반 로컬 비디오 더빙 시스템입니다. 사용자가 비디오를 업로드하면 음성을 추출하고, 번역하고, TTS로 새 음성을 생성하여 더빙된 비디오를 출력하는 것이 목표입니다.

### 워크플로우 (현재)

1. **Home 페이지:** 사용자가 비디오 파일 선택
2. **"음성 추출" 버튼:** 클라이언트에서 FFmpeg WASM으로 오디오 추출 (MP3)
3. **"더빙 시작" 버튼:** 추출된 오디오(MP3)를 서버에 업로드
4. **서버 처리:** STT → 번역 → TTS → 결과 출력 (오디오만!)
5. **결과:** WAV 오디오만 다운로드 가능, **비디오 없음**

## 문제점

### 핵심 문제
`frontend/src/pages/Home.jsx`의 `handleStartDubbing` 함수에서 **추출된 오디오(extractedAudio)**를 업로드합니다:

```javascript
// Home.jsx 약 192라인
const fileToUpload = extractedAudio || file;
```

서버(`src/core/pipeline.py`)는 입력 파일 타입을 확인하여:
- **비디오 입력:** Extract → STT → 번역 → TTS → **Merge(비디오 병합)** → MP4 출력
- **오디오 입력:** STT → 번역 → TTS → **Merge 건너뜀** → WAV 출력

현재는 오디오만 업로드되므로 **비디오 병합이 수행되지 않습니다.**

## 해결 방안 (Option A)

**원본 비디오 파일을 업로드**하도록 수정합니다.
"음성 추출"은 미리듣기/확인 용도로 유지하고, 실제 처리는 원본 비디오 기반으로 수행합니다.

## 수정 사항

### 파일: `frontend/src/pages/Home.jsx`

`handleStartDubbing` 함수 내에서 `fileToUpload` 변수 수정:

**Before (약 192라인):**
```javascript
const fileToUpload = extractedAudio || file;
```

**After:**
```javascript
// 항상 원본 파일을 업로드 (서버에서 비디오 병합 가능하도록)
// extractedAudio는 미리듣기 용도로만 사용
const fileToUpload = file;
```

## 테스트 방법

1. 서버 실행: `venv\Scripts\python.exe -u scripts\start_app.py`
2. 브라우저에서 `http://localhost:5173` 접속
3. 짧은 비디오 파일(30초 이하) 업로드
4. "음성 추출" 클릭 → 완료 확인 (선택사항, 미리듣기용)
5. "더빙 시작" 클릭
6. 처리 완료 후 결과 페이지에서 **"MP4 다운로드"** 버튼 확인
7. 다운로드된 비디오 재생하여 더빙 음성 확인

## 예상 결과

- 결과 페이지에서 **"미디어를 불러올 수 없습니다"** 대신 비디오 미리보기 표시
- **"MP4 다운로드"** 버튼 활성화
- 다운로드된 MP4 파일에 목표 언어로 더빙된 음성 포함

## 관련 파일

- `frontend/src/pages/Home.jsx` - 수정 대상
- `src/core/pipeline.py` - `process_job` 함수 (참고용, 수정 불필요)
- `src/web/routes.py` - 업로드 처리 (참고용, 수정 불필요)

## 주의사항

- "음성 추출" 기능은 그대로 유지 (미리듣기와 자막 확인 용도)
- 변수 `canStartDubbing`, `isExtractionComplete` 등은 수정하지 않음
- 버튼 렌더링 조건도 수정하지 않음 (추출 완료 후에만 더빙 시작 활성화)
