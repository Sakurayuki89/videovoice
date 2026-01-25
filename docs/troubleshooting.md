# 문제 해결 가이드

VideoVoice 실행 중 발생할 수 있는 문제와 해결 방법입니다.

## VRAM 부족

### 증상
```
CUDA out of memory
```

### 해결
1. **WhisperX batch_size 줄이기**: `batch_size=8` 또는 `4`
2. **더 작은 모델 사용**: `qwen3:8b`
3. **순차 실행 보장**: 한 단계 완료 후 다음 단계

## Ollama 연결 실패

### 증상
```
Connection refused: localhost:11434
```

### 해결
```bash
# Ollama 실행 확인
ollama serve

# 모델 확인
ollama list
```

## STT 언어 감지 오류

### 증상
잘못된 언어로 인식

### 해결
```python
# 언어 명시적 지정
result = model.transcribe(audio, language="ko")
```

## TTS 음색 불일치

### 증상
문장마다 다른 목소리

### 해결
- 동일한 `speaker_wav` 파일 사용
- 참조 오디오: 5~15초, 깨끗한 단일 화자

## 번역 품질 저하

### 증상
- 직역으로 어색함
- 문장 길이 차이 큼

### 해결
1. 프롬프트에 "for dubbing" 명시
2. 길이 제한 추가
3. 품질 60점 미만 시 재번역

## 오디오 싱크 불일치

### 증상
영상과 음성 타이밍 어긋남

### 해결
- 타임스탬프 기반 정렬
- 문장 간 무음 길이 조정 (200~400ms)
- TTS 속도 조절

## Gemini API 오류

### 증상
```
ResourceExhausted: 429
```

### 해결
- 요청 간격 늘리기 (1초 이상)
- 배치 처리로 호출 수 줄이기
- API 키 할당량 확인

## 일반 디버깅 팁

```bash
# 로그 활성화
export PYTHONUNBUFFERED=1

# GPU 상태 확인
nvidia-smi

# 중간 파일 확인
ls -la output/segments/
```
