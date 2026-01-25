---
name: speech-to-text
description: WhisperX 기반 음성 인식(STT) 스킬
---

# Speech-to-Text Skill

WhisperX를 사용하여 음성을 타임스탬프 포함 텍스트로 변환합니다.

## 모델 설정

```python
import whisperx

# 모델 로드 (large-v3 권장)
model = whisperx.load_model("large-v3", device="cuda", compute_type="float16")

# 오디오 로드
audio = whisperx.load_audio("input.wav")

# 음성 인식
result = model.transcribe(audio, batch_size=16)
```

## 지원 언어

- 한국어 (ko)
- 영어 (en)
- 러시아어 (ru)

## 언어 자동 감지

```python
# 자동 감지 모드
result = model.transcribe(audio, language=None)
detected_language = result["language"]
```

## 출력 형식

```json
{
  "segments": [
    {
      "start": 0.0,
      "end": 2.5,
      "text": "안녕하세요",
      "words": [
        {"word": "안녕하세요", "start": 0.0, "end": 2.5}
      ]
    }
  ],
  "language": "ko"
}
```

## 규칙

1. **문장 단위 분할**: 세그먼트는 자연스러운 문장 단위로 분할
2. **타임스탬프 필수**: 모든 세그먼트에 start/end 시간 포함
3. **VRAM 관리**: batch_size 조절로 메모리 사용량 제어 (기본 16)
