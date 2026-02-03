@echo off
REM VideoVoice 서버 종료 스크립트

echo [VideoVoice] 모든 관련 프로세스 종료 중...

taskkill /F /IM python.exe 2>nul
taskkill /F /IM node.exe 2>nul
taskkill /F /IM ffmpeg.exe 2>nul

echo [VideoVoice] 서버가 종료되었습니다.
pause
