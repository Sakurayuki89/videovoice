---
name: video-processing
description: FFmpeg를 활용한 비디오/오디오 처리 스킬
---

# Video Processing Skill

FFmpeg를 사용하여 비디오에서 오디오를 추출하고, 새로운 오디오 트랙으로 교체하는 방법을 정의합니다.

## 오디오 추출

```bash
ffmpeg -i input.mp4 -vn -acodec pcm_s16le -ar 16000 -ac 1 output.wav
```

**옵션 설명:**
- `-vn`: 비디오 스트림 제외
- `-acodec pcm_s16le`: 16비트 PCM 포맷
- `-ar 16000`: 16kHz 샘플링 (WhisperX 최적)
- `-ac 1`: 모노 채널

## 오디오 트랙 교체

```bash
ffmpeg -i original.mp4 -i new_audio.wav -c:v copy -map 0:v:0 -map 1:a:0 output.mp4
```

**옵션 설명:**
- `-c:v copy`: 비디오 스트림 무변환 복사 (재인코딩 금지)
- `-map 0:v:0`: 원본 비디오 스트림 사용
- `-map 1:a:0`: 새 오디오 파일 사용

## 규칙

1. **비디오 재인코딩 금지**: 항상 `-c:v copy` 사용
2. **오디오 포맷**: STT용은 16kHz WAV, TTS 출력은 원본과 동일한 샘플레이트
3. **타임스탬프 보존**: 원본 비디오의 타임스탬프 구조 유지
