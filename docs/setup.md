# 환경 설정 가이드

VideoVoice 하이브리드 시스템 실행을 위한 환경 설정 방법입니다.

## 1. Python 환경 & 의존성 설치

```bash
# Python 3.10+ 권장
python -m venv venv
.\venv\Scripts\activate  # Windows

# 핵심 패키지 (PyTorch + CUDA)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# 프로젝트 의존성 설치 (WhisperX, Gemini, ElevenLabs 등 포함)
pip install -r requirements.txt
```

## 2. API 키 설정 (클라우드/하이브리드 모드)

`.env` 파일을 프로젝트 루트에 생성하고 아래 내용을 채워주세요.

```bash
# Gemini (필수: 번역 및 품질 검증)
GEMINI_API_KEY=your_gemini_key_here
GEMINI_MODEL=gemini-2.5-flash

# Groq (추천: 초고속 STT/번역)
GROQ_API_KEY=your_groq_key_here
GROQ_MODEL=llama-3.3-70b-versatile

# ElevenLabs (선택: 고품질 TTS)
ELEVENLABS_API_KEY=your_elevenlabs_key_here

# OpenAI (선택)
OPENAI_API_KEY=your_openai_key_here
```

## 3. 로컬 엔진 설정 (선택 사항)

클라우드 API만 사용할 경우 아래 로컬 도구는 필요하지 않을 수 있습니다.

**FFmpeg (필수)**
```bash
# Windows
choco install ffmpeg
```

**Ollama (로컬 번역)**
```bash
# https://ollama.ai 다운로드 후
ollama pull qwen3:14b
```

**XTTS v2 (로컬 TTS)**
```bash
# 첫 실행 시 모델 자동 다운로드 (약 2GB)
# requirements.txt에 포함된 TTS 패키지 사용
```

## 환경 검증

```bash
# FFmpeg
ffmpeg -version

# Python 환경 확인
python -c "import whisperx; import elevenlabs; import google.generativeai; print('System Ready')"
```
