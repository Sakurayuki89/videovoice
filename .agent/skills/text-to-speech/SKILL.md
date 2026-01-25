---
name: text-to-speech
description: XTTS v2 기반 다국어 음성 합성 스킬
---

# Text-to-Speech Skill

XTTS v2를 사용하여 다국어 텍스트를 음성으로 변환합니다.

## 기본 사용법

```python
from TTS.api import TTS

# XTTS v2 모델 로드
tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cuda")

# 음성 생성
tts.tts_to_file(
    text="안녕하세요",
    speaker_wav="speaker_reference.wav",  # 화자 음색 참조
    language="ko",
    file_path="output.wav"
)
```

## 지원 언어

- 한국어: `ko`
- 영어: `en`
- 러시아어: `ru`

## Speaker Embedding

프로젝트 전체에서 동일한 화자 음색을 유지하기 위해 참조 오디오를 사용합니다.

```python
# 프로젝트별 화자 참조 파일 설정
SPEAKER_REFERENCE = "project_speaker.wav"  # 5~15초 클린 음성
```

## 문장 단위 생성

```python
def generate_audio_segments(sentences: list, speaker_wav: str, language: str):
    outputs = []
    for i, sentence in enumerate(sentences):
        output_path = f"segment_{i:04d}.wav"
        tts.tts_to_file(
            text=sentence,
            speaker_wav=speaker_wav,
            language=language,
            file_path=output_path
        )
        outputs.append(output_path)
    return outputs
```

## 오디오 병합

```python
from pydub import AudioSegment

def merge_audio(segments: list, gap_ms: int = 300) -> AudioSegment:
    silence = AudioSegment.silent(duration=gap_ms)
    combined = AudioSegment.empty()
    
    for seg_path in segments:
        audio = AudioSegment.from_wav(seg_path)
        combined += audio + silence
    
    return combined
```

## 규칙

1. **동일 Speaker Embedding**: 프로젝트 내 모든 TTS에 동일 참조 사용
2. **무음 삽입**: 문장 간 200~400ms 무음
3. **말 속도**: 원본 대비 ±10% 이내
4. **볼륨 정규화**: RMS 기준 자동 정규화
