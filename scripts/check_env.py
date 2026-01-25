import torch
import sys
import subprocess
import os
import requests
import json
import time

def print_status(component, status, message=""):
    if status == "OK":
        color = "\033[92m"  # Green
    elif status == "WARNING":
        color = "\033[93m"  # Yellow
    else:
        color = "\033[91m"  # Red
    reset = "\033[0m"
    print(f"[{color}{status}{reset}] {component:<20} {message}")

def check_cuda():
    try:
        if torch.cuda.is_available():
            v = torch.version.cuda
            d = torch.cuda.get_device_name(0)
            print_status("CUDA", "OK", f"{d} (CUDA {v})")

            # VRAM 용량 검사
            total_vram = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            free_vram = (torch.cuda.get_device_properties(0).total_memory - torch.cuda.memory_allocated(0)) / (1024**3)

            if total_vram >= 10:
                print_status("VRAM", "OK", f"Total: {total_vram:.1f} GB (Recommended: 12GB+)")
            elif total_vram >= 8:
                print_status("VRAM", "WARNING", f"Total: {total_vram:.1f} GB (May need reduced batch_size)")
            else:
                print_status("VRAM", "FAIL", f"Total: {total_vram:.1f} GB (Minimum 8GB required)")
                return False

            return True
        else:
            print_status("CUDA", "FAIL", "Torch reported CUDA not available")
            return False
    except Exception as e:
        print_status("CUDA", "FAIL", str(e))
        return False

def check_ffmpeg():
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
        if result.returncode == 0:
            line = result.stdout.split('\n')[0]
            print_status("FFmpeg", "OK", line)
            return True
        else:
            print_status("FFmpeg", "FAIL", "Return code " + str(result.returncode))
            return False
    except FileNotFoundError:
        print_status("FFmpeg", "FAIL", "Command not found")
        return False

REQUIRED_OLLAMA_MODELS = ["qwen3:14b"]


def check_ollama():
    try:
        # Check standard port
        response = requests.get("http://localhost:11434/", timeout=5)
        if response.status_code == 200:
            # Check models
            list_resp = requests.get("http://localhost:11434/api/tags", timeout=5)
            if list_resp.status_code == 200:
                models = [m['name'] for m in list_resp.json()['models']]
                print_status("Ollama", "OK", f"Running. Models: {models}")

                # 필수 모델 검증
                missing_models = []
                for required in REQUIRED_OLLAMA_MODELS:
                    # qwen3:14b 또는 qwen3:14b-... 형태 매칭
                    found = any(m == required or m.startswith(required.replace(":14b", ":14b-")) or m.startswith(required + "-") for m in models)
                    if not found:
                        missing_models.append(required)

                if missing_models:
                    print_status("Ollama Models", "FAIL", f"Missing required: {missing_models}")
                    print(f"       Run: ollama pull {' '.join(missing_models)}")
                    return False
                else:
                    print_status("Ollama Models", "OK", f"Required models present: {REQUIRED_OLLAMA_MODELS}")
                    return True
            else:
                print_status("Ollama", "WARNING", "Running but failed to list models")
                return False
        else:
            print_status("Ollama", "FAIL", f"Status code {response.status_code}")
            return False
    except requests.exceptions.Timeout:
        print_status("Ollama", "FAIL", "Connection timeout")
        return False
    except requests.exceptions.ConnectionError:
        print_status("Ollama", "FAIL", "Connection refused (is it running?)")
        return False

def check_whisperx():
    print("Checking WhisperX import... ", end="")
    try:
        import whisperx
        print_status("WhisperX", "OK", "Imported successfully")
        return True
    except ImportError as e:
        print_status("WhisperX", "FAIL", str(e))
        return False
    except Exception as e:
        print_status("WhisperX", "FAIL", f"Error during import: {e}")
        return False

def check_tts():
    print("Checking TTS import... ", end="")
    try:
        from TTS.api import TTS
        print_status("TTS", "OK", "Imported successfully")
        return True
    except ImportError as e:
        print_status("TTS", "FAIL", str(e))
        return False
    except Exception as e:
        print_status("TTS", "FAIL", f"Error during import: {e}")
        return False

def main():
    print("=== VideoVoice Environment Check ===\n")
    
    cuda_ok = check_cuda()
    ffmpeg_ok = check_ffmpeg()
    ollama_ok = check_ollama()
    
    # Only check python libs if basic environment is sane
    whisper_ok = check_whisperx()
    tts_ok = check_tts()

    print("\n=== Summary ===")
    if all([cuda_ok, ffmpeg_ok, ollama_ok, whisper_ok, tts_ok]):
        print("\033[92mALL CHECKS PASSED. SYSTEM READY.\033[0m")
    else:
        print("\033[91mSOME CHECKS FAILED. PLEASE FIX BEFORE PROCEEDING.\033[0m")

if __name__ == "__main__":
    main()
