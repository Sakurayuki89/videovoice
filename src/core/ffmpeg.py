import subprocess
import os
import re
import json


class FFmpegModule:
    # Timeout for FFmpeg operations (10 minutes)
    TIMEOUT_SECONDS = 600

    def get_media_duration(self, file_path: str) -> float:
        """Get duration of media file in seconds using ffprobe."""
        if not self._validate_path(file_path, must_exist=True):
            print(f"FFprobe Failed: Invalid or missing path: {file_path}")
            return 0.0

        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            file_path
        ]

        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                timeout=30
            )
            data = json.loads(result.stdout.decode('utf-8'))
            duration = float(data.get('format', {}).get('duration', 0))
            return duration
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError) as e:
            print(f"FFprobe Failed: Could not get duration: {e}")
            return 0.0
        except FileNotFoundError:
            print("FFprobe Failed: ffprobe not found in PATH")
            return 0.0

    def _validate_path(self, path: str, must_exist: bool = True) -> bool:
        """
        Validate file path for security.
        - Must be absolute or relative without traversal
        - Must not contain shell metacharacters
        - Optionally check existence
        """
        if not path:
            return False

        # Check for null bytes
        if "\x00" in path:
            return False

        # Check for path traversal attempts
        normalized = os.path.normpath(path)
        if ".." in normalized.split(os.sep):
            return False

        # Check for shell metacharacters that could be dangerous
        # Even though we use list format, ffmpeg itself interprets some patterns
        dangerous_patterns = [
            r'[|;&$`]',  # Shell operators
            r'^\s*-',     # Options injection at start (after normpath)
        ]
        basename = os.path.basename(path)
        for pattern in dangerous_patterns:
            if re.search(pattern, basename):
                return False

        # Check existence if required
        if must_exist and not os.path.isfile(path):
            return False

        return True

    def _ensure_output_dir(self, output_path: str) -> bool:
        """Ensure the output directory exists."""
        try:
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            return True
        except OSError as e:
            print(f"Failed to create output directory: {e}")
            return False

    def extract_audio(self, video_path: str, output_audio_path: str) -> bool:
        """Extract 16kHz mono audio for Whisper."""
        # Validate input path
        if not self._validate_path(video_path, must_exist=True):
            print(f"FFmpeg Extract Failed: Invalid or missing input path: {video_path}")
            return False

        # Validate output path (should not exist yet)
        if not self._validate_path(output_audio_path, must_exist=False):
            print(f"FFmpeg Extract Failed: Invalid output path: {output_audio_path}")
            return False

        # Ensure output directory exists
        if not self._ensure_output_dir(output_audio_path):
            return False

        cmd = [
            "ffmpeg", "-i", video_path,
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            output_audio_path, "-y"
        ]

        try:
            result = subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=self.TIMEOUT_SECONDS
            )
            return True
        except subprocess.TimeoutExpired:
            print(f"FFmpeg Extract Failed: Operation timed out after {self.TIMEOUT_SECONDS}s")
            return False
        except subprocess.CalledProcessError as e:
            stderr_msg = e.stderr.decode('utf-8', errors='replace') if e.stderr else 'Unknown error'
            print(f"FFmpeg Extract Failed: {stderr_msg[:500]}")  # Limit error message length
            return False
        except FileNotFoundError:
            print("FFmpeg Extract Failed: ffmpeg not found in PATH")
            return False

    def merge_video(self, video_path: str, audio_path: str, output_path: str) -> bool:
        """Merge original video with new audio."""
        # Validate all paths
        if not self._validate_path(video_path, must_exist=True):
            print(f"FFmpeg Merge Failed: Invalid or missing video path: {video_path}")
            return False

        if not self._validate_path(audio_path, must_exist=True):
            print(f"FFmpeg Merge Failed: Invalid or missing audio path: {audio_path}")
            return False

        if not self._validate_path(output_path, must_exist=False):
            print(f"FFmpeg Merge Failed: Invalid output path: {output_path}")
            return False

        # Ensure output directory exists
        if not self._ensure_output_dir(output_path):
            return False

        cmd = [
            "ffmpeg", "-i", video_path, "-i", audio_path,
            "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0",
            "-shortest",
            output_path, "-y"
        ]

        try:
            result = subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=self.TIMEOUT_SECONDS
            )
            return True
        except subprocess.TimeoutExpired:
            print(f"FFmpeg Merge Failed: Operation timed out after {self.TIMEOUT_SECONDS}s")
            return False
        except subprocess.CalledProcessError as e:
            stderr_msg = e.stderr.decode('utf-8', errors='replace') if e.stderr else 'Unknown error'
            print(f"FFmpeg Merge Failed: {stderr_msg[:500]}")  # Limit error message length
            return False
        except FileNotFoundError:
            print("FFmpeg Merge Failed: ffmpeg not found in PATH")
            return False

    def extend_video_to_audio(self, video_path: str, audio_path: str, output_path: str) -> bool:
        """
        Merge video with audio, stretching video if audio is longer.
        Uses setpts filter to slow down video to match audio duration.
        """
        # Validate all paths
        if not self._validate_path(video_path, must_exist=True):
            print(f"FFmpeg Extend Failed: Invalid or missing video path: {video_path}")
            return False

        if not self._validate_path(audio_path, must_exist=True):
            print(f"FFmpeg Extend Failed: Invalid or missing audio path: {audio_path}")
            return False

        if not self._validate_path(output_path, must_exist=False):
            print(f"FFmpeg Extend Failed: Invalid output path: {output_path}")
            return False

        # Ensure output directory exists
        if not self._ensure_output_dir(output_path):
            return False

        # Get durations
        video_duration = self.get_media_duration(video_path)
        audio_duration = self.get_media_duration(audio_path)

        if video_duration <= 0 or audio_duration <= 0:
            print(f"FFmpeg Extend Failed: Could not determine durations (video={video_duration}s, audio={audio_duration}s)")
            return False

        print(f"Video duration: {video_duration:.2f}s, Audio duration: {audio_duration:.2f}s")

        # If audio is longer, slow down video; otherwise do normal merge
        if audio_duration > video_duration:
            # Calculate slowdown factor (PTS multiplier)
            # setpts=PTS*factor slows video by that factor
            slowdown_factor = audio_duration / video_duration

            # Limit slowdown to prevent extremely slow video (max 2x slower)
            max_slowdown = 2.0
            if slowdown_factor > max_slowdown:
                print(f"Warning: Audio is {slowdown_factor:.2f}x longer than video. Limiting slowdown to {max_slowdown}x")
                slowdown_factor = max_slowdown

            print(f"Applying video slowdown factor: {slowdown_factor:.3f}x")

            # Use setpts filter to slow down video
            # PTS = Presentation TimeStamp
            video_filter = f"setpts={slowdown_factor}*PTS"

            cmd = [
                "ffmpeg", "-i", video_path, "-i", audio_path,
                "-filter:v", video_filter,
                "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                "-c:a", "aac", "-b:a", "192k",
                "-map", "0:v:0", "-map", "1:a:0",
                "-shortest",
                output_path, "-y"
            ]
        else:
            # Audio is shorter or equal - do normal merge
            print("Audio fits within video duration - performing normal merge")
            cmd = [
                "ffmpeg", "-i", video_path, "-i", audio_path,
                "-c:v", "copy", "-c:a", "aac",
                "-map", "0:v:0", "-map", "1:a:0",
                "-shortest",
                output_path, "-y"
            ]

        try:
            result = subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=self.TIMEOUT_SECONDS
            )
            return True
        except subprocess.TimeoutExpired:
            print(f"FFmpeg Extend Failed: Operation timed out after {self.TIMEOUT_SECONDS}s")
            return False
        except subprocess.CalledProcessError as e:
            stderr_msg = e.stderr.decode('utf-8', errors='replace') if e.stderr else 'Unknown error'
            print(f"FFmpeg Extend Failed: {stderr_msg[:500]}")
            return False
        except FileNotFoundError:
            print("FFmpeg Extend Failed: ffmpeg not found in PATH")
            return False
