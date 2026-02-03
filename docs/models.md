# 사용 모델 명세

VideoVoice 하이브리드 파이프라인에서 사용하는 AI 모델들의 상세 사양입니다.

## 1. Cloud AI Models

### Gemini 2.5 Flash (Validation & Translation)
| 항목 | 값 |
|------|-----|
| 용도 | 번역 품질 검증, 문장 번역, 리파인 |
| 모델 | `gemini-2.5-flash` |
| 특징 | 압도적인 처리 속도, 1M 컨텍스트, 저렴한 비용 |
| 역할 | 4단계 신뢰성 시스템의 핵심 엔진 |

### Groq (Llama 3.3)
| 항목 | 값 |
|------|-----|
| 용도 | 초고속 STT, 번역 (Gemini 폴백) |
| 모델 | `llama-3.3-70b-versatile`, `distil-whisper-large-v3-en` |
| 속도 | 300+ token/s (실시간에 근접) |
| 비용 | 매우 저렴 (혹은 무료 티어) |

### ElevenLabs (Premium TTS)
| 항목 | 값 |
|------|-----|
| 용도 | 고품질 음성 합성, 음색 복제 |
| 모델 | `eleven_multilingual_v2` |
| 품질 | 현존 최고 수준의 자연스러움 |
| 비용 | 유료 (Character 단위 과금) |

## 2. Local AI Models

### WhisperX large-v3
| 항목 | 값 |
|------|-----|
| 용도 | Speech-to-Text (STT) 정밀 분석 |
| VRAM | ~4GB |
| 특징 | 단어 단위 타임스탬프, 화자 분리(Diarization) 준비됨 |

### Edge TTS (Microsoft)
| 항목 | 값 |
|------|-----|
| 용도 | 한국어/다국어 빠르고 자연스러운 TTS |
| 비용 | 무료 |
| 특징 | `ko-KR-SunHiNeural` 등 매우 자연스러운 목소리 제공 |

### XTTS v2 (Coqui)
| 항목 | 값 |
|------|-----|
| 용도 | 로컬 음성 복제 (Cloning) |
| VRAM | ~3GB |
| 특징 | 6~10초 샘플로 음색 복제 가능 |

### Silero
| 항목 | 값 |
|------|-----|
| 용도 | 러시아어 등 초고속 TTS |
| 속도 | CPU에서도 매우 빠름 |
| 특징 | 자원 소모 최소화 |

## 3. 총 시스템 리소스

- **Hybrid Mode**: VRAM 4GB 이하에서도 구동 가능 (Cloud API 활용 시)
- **Full Local Mode**: 최소 8GB~12GB VRAM 권장 (WhisperX + XTTS)
- **동시성**: 단계별 순차 실행으로 피크 메모리 사용량 관리됨
