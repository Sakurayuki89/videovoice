import os
import sys
import time
import torch
import gc
import json
import requests

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.join(PROJECT_ROOT, "tests")
sys.path.append(PROJECT_ROOT)


def get_test_path(filename):
    """테스트 파일의 절대 경로 반환 (작업 디렉토리 무관하게 동작)"""
    return os.path.join(TESTS_DIR, filename)


def clear_vram(component_name):
    print(f"\n[{component_name}] Clearing VRAM...")
    gc.collect()
    torch.cuda.empty_cache()
    if torch.cuda.is_available():
        print(f"VRAM Allocated: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")
        print(f"VRAM Reserved:  {torch.cuda.memory_reserved() / 1024**3:.2f} GB")


def validate_file_exists(file_path, description="File"):
    """파일 존재 여부 검증"""
    if not file_path:
        print(f"[ERROR] {description} path is empty")
        return False
    if not os.path.exists(file_path):
        print(f"[ERROR] {description} not found: {file_path}")
        return False
    return True


def validate_text(text, description="Text"):
    """텍스트 유효성 검증"""
    if text is None:
        print(f"[ERROR] {description} is None")
        return False
    if not isinstance(text, str):
        print(f"[ERROR] {description} is not a string: {type(text)}")
        return False
    if not text.strip():
        print(f"[ERROR] {description} is empty or whitespace only")
        return False
    return True


def step_1_generate_input_audio(text, output_path):
    print("\n=== Step 1: Input Audio Setup ===")
    print(f"  [WARNING] Using dummy sine wave. For better TTS quality, use real speech audio.")

    # 출력 경로 검증
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        print(f"[ERROR] Output directory does not exist: {output_dir}")
        return False

    import subprocess
    try:
        print("Generating dummy sine wave audio using ffmpeg...")
        # Generate 5 seconds of sine wave
        subprocess.run(
            ["ffmpeg", "-f", "lavfi", "-i", "sine=frequency=1000:duration=5", output_path, "-y"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )
        print(f"Generated dummy audio to {output_path}")
        return True
    except FileNotFoundError:
        print("[ERROR] FFmpeg not found. Please install FFmpeg and add to PATH.")
        return False
    except subprocess.CalledProcessError as e:
        print(f"Step 1 Failed: FFmpeg returned error code {e.returncode}")
        return False
    except Exception as e:
        import traceback
        print(f"Step 1 Failed: {e}")
        traceback.print_exc()
        return False

def step_2_transcribe(audio_path):
    print("\n=== Step 2: STT (WhisperX) ===")

    # 입력 파일 검증
    if not validate_file_exists(audio_path, "Audio file"):
        return None

    start_time = time.time()
    model = None
    try:
        import whisperx
        device = "cuda"
        batch_size = 4
        compute_type = "float16"

        print("Loading WhisperX model...")
        model = whisperx.load_model("large-v3", device, compute_type=compute_type)

        print(f"Transcribing {audio_path}...")
        audio = whisperx.load_audio(audio_path)

        # Changed to English input
        result = model.transcribe(audio, batch_size=batch_size, language="en")

        transcribed_text = " ".join([seg["text"] for seg in result["segments"]])
        print(f"Detected Text: {transcribed_text}")

        return transcribed_text
    except Exception as e:
        import traceback
        print(f"Step 2 Failed: {e}")
        traceback.print_exc()
        return None
    finally:
        # VRAM 누수 방지: 예외 발생 여부와 관계없이 항상 메모리 해제
        if model is not None:
            del model
        clear_vram("WhisperX")

def strip_thinking_tags(text):
    """Qwen3 모델의 <think>...</think> 태그 제거"""
    import re
    # <think> 태그와 그 내용 제거 (멀티라인 포함)
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    return cleaned.strip()


def step_3_translate(text, max_retries=3):
    """Ollama를 통한 번역 (재시도 로직 포함)"""
    print("\n=== Step 3: Translation (Ollama) ===")

    if not text or not text.strip():
        print("Step 3 Skipped: Empty input text")
        return None

    import requests

    model = "qwen3:14b"
    prompt = f"Translate the following English text to Korean for a video dubbing script. Output ONLY the Korean text.\n\nText: {text}"

    for attempt in range(1, max_retries + 1):
        try:
            print(f"Sending request to Ollama ({model})... (attempt {attempt}/{max_retries})")
            response = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False
                },
                timeout=120
            )

            if response.status_code == 200:
                res_json = response.json()
                raw_response = res_json.get('response', '')
                translated_text = strip_thinking_tags(raw_response)

                if translated_text:
                    print(f"Translated Text: {translated_text}")
                    return translated_text
                else:
                    print(f"Warning: Empty translation response (attempt {attempt})")
            else:
                print(f"Ollama Error (attempt {attempt}): {response.status_code} - {response.text}")

        except requests.exceptions.Timeout:
            print(f"Timeout (attempt {attempt}): Ollama request exceeded 120s")
        except requests.exceptions.ConnectionError:
            print(f"Connection Error (attempt {attempt}): Is Ollama running?")
        except Exception as e:
            import traceback
            print(f"Unexpected Error (attempt {attempt}): {e}")
            traceback.print_exc()

        # 재시도 전 대기 (exponential backoff: 2초, 4초, 8초...)
        if attempt < max_retries:
            wait_time = 2 ** attempt
            print(f"Retrying in {wait_time} seconds...")
            time.sleep(wait_time)

    print(f"Step 3 Failed: All {max_retries} attempts exhausted")
    return None

def step_4_tts_output(text, speaker_wav, output_path=None):
    print("\n=== Step 4: TTS Output (XTTS v2) ===")

    # 입력 검증
    if not validate_text(text, "TTS input text"):
        return False
    if not validate_file_exists(speaker_wav, "Speaker reference audio"):
        return False

    tts = None
    try:
        from TTS.api import TTS
        print("Loading XTTS v2 model...")
        tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cuda")

        if output_path is None:
            output_path = get_test_path("output_ko.wav")
        print(f"Generating Korean speech to {output_path}...")

        # Use the input English audio as the speaker reference
        # Target language is Korean ('ko')
        tts.tts_to_file(text=text, file_path=output_path, speaker_wav=speaker_wav, language="ko")

        print(f"Done. Saved to {output_path}")
        return True
    except Exception as e:
        import traceback
        print(f"Step 4 Failed: {e}")
        traceback.print_exc()
        return False
    finally:
        # VRAM 누수 방지: 예외 발생 여부와 관계없이 항상 메모리 해제
        if tts is not None:
            del tts
        clear_vram("XTTS")

def main():
    print("Starting Pipeline Verification (Flow: EN -> STT -> KO -> TTS)...")
    print(f"Project Root: {PROJECT_ROOT}")
    print(f"Tests Directory: {TESTS_DIR}")

    os.makedirs(TESTS_DIR, exist_ok=True)
    input_wav = get_test_path("test_input_en.wav")
    input_text = "Hello, this is a test message for the video voice project pipeline verification."
    
    # 1. Generate Input (EN)
    if not step_1_generate_input_audio(input_text, input_wav):
        return
    
    # 2. Transcribe (EN)
    transcribed_text = step_2_transcribe(input_wav)
    if not transcribed_text:
        print("STT returned empty text (expected for sine wave). Using dummy text for verification.")
        transcribed_text = "Hello, this is a fallback text because automatic speech recognition did not detect any speech in the dummy audio."
        
    # 3. Translate (EN -> KO)
    translated_text = step_3_translate(transcribed_text)
    if not translated_text:
        return
        
    # 4. Generate Output (KO)
    step_4_tts_output(translated_text, input_wav)
    
    print("\n=== VERIFICATION COMPLETE ===")


if __name__ == "__main__":
    main()
