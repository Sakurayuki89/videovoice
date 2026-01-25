# 환경 설정 가이드

VideoVoice 시스템 실행을 위한 환경 설정 방법입니다.

## 1. Python 환경

```bash
# Python 3.10+ 권장
python -m venv venv
.\venv\Scripts\activate  # Windows

pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

## 2. FFmpeg 설치

```bash
# Windows (Chocolatey)
choco install ffmpeg

# 또는 수동 설치 후 PATH 추가
```

## 3. Ollama + Qwen3

```bash
# Ollama 설치 (https://ollama.ai)
# 모델 다운로드
ollama pull qwen3:14b

# 확인
ollama list
```

## 4. WhisperX

```bash
pip install git+https://github.com/m-bain/whisperX.git

# 추가 의존성
pip install faster-whisper
```

## 5. XTTS v2

```bash
pip install TTS

# 모델 자동 다운로드 (첫 실행 시)
python -c "from TTS.api import TTS; TTS('tts_models/multilingual/multi-dataset/xtts_v2')"
```

## 6. Gemini API

```bash
pip install google-generativeai

# API 키 설정 (환경변수)
set GEMINI_API_KEY=your_api_key_here
```

## 7. 추가 라이브러리

```bash
pip install pydub requests
```

## 환경 검증

```bash
# FFmpeg
ffmpeg -version

# Ollama
ollama run qwen3:14b "Hello"

# Python 패키지
python -c "import whisperx; import TTS; import google.generativeai; print('OK')"
```
