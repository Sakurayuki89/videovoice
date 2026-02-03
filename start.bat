@echo off
REM VideoVoice 서버 시작 스크립트
REM 기존 프로세스 정리 후 백엔드/프론트엔드 서버 시작

echo [VideoVoice] 기존 프로세스 정리 중...

REM Kill existing processes
taskkill /F /IM python.exe 2>nul
taskkill /F /IM node.exe 2>nul
taskkill /F /IM ffmpeg.exe 2>nul

timeout /t 2 /nobreak >nul

echo [VideoVoice] 서버 시작 중...

REM Start Backend (new window)
start "VideoVoice Backend" cmd /k "cd /d %~dp0 && venv\Scripts\python -m uvicorn src.web.main:app --reload --host 0.0.0.0 --port 8000"

REM Start Frontend (new window)
start "VideoVoice Frontend" cmd /k "cd /d %~dp0frontend && npm run dev -- --host"

echo.
echo [VideoVoice] 서버가 시작되었습니다!
echo   - 백엔드: http://localhost:8000
echo   - 프론트엔드: http://localhost:5173
echo.
echo 이 창은 닫아도 됩니다. 서버는 별도 창에서 실행 중입니다.
pause
