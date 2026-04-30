@echo off
setlocal EnableDelayedExpansion
set SCRIPT_DIR=%~dp0

echo ============================================
echo  YTMP3 Setup
echo ============================================

:: 1. Python 버전 확인 (3.10+)
python --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python을 찾을 수 없습니다. https://python.org 에서 설치하세요.
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo [OK] Python %PY_VER% 감지됨

:: 2. 가상환경 생성
if not exist "%SCRIPT_DIR%venv\" (
    echo [*] 가상환경 생성 중...
    python -m venv "%SCRIPT_DIR%venv"
    if errorlevel 1 (
        echo [ERROR] 가상환경 생성 실패
        exit /b 1
    )
    echo [OK] 가상환경 생성 완료
) else (
    echo [OK] 가상환경 이미 존재
)

:: 3. pip 패키지 설치
echo [*] 패키지 설치 중...
"%SCRIPT_DIR%venv\Scripts\pip.exe" install -r "%SCRIPT_DIR%requirements.txt" --quiet
if errorlevel 1 (
    echo [ERROR] 패키지 설치 실패
    exit /b 1
)
echo [OK] 패키지 설치 완료

:: 4. ffmpeg 확인
where ffmpeg > nul 2>&1
if errorlevel 1 (
    echo [WARNING] ffmpeg가 PATH에 없습니다.
    echo           winget으로 설치: winget install --id Gyan.FFmpeg -e
    echo           또는 https://ffmpeg.org/download.html 에서 다운로드 후
    echo           config.json의 ffmpeg_path를 ffmpeg.exe 경로로 설정하세요.
) else (
    echo [OK] ffmpeg 감지됨
)

:: 5. 필요 디렉토리 생성
if not exist "%SCRIPT_DIR%state\" mkdir "%SCRIPT_DIR%state"
if not exist "%SCRIPT_DIR%music\singles\" mkdir "%SCRIPT_DIR%music\singles"
if not exist "%SCRIPT_DIR%logs\" mkdir "%SCRIPT_DIR%logs"
echo [OK] 디렉토리 준비 완료

:: 6. .env 파일 생성 (없을 때만)
if not exist "%SCRIPT_DIR%.env" (
    copy "%SCRIPT_DIR%.env.example" "%SCRIPT_DIR%.env" > nul
    echo [OK] .env 파일 생성됨 - Discord 토큰을 입력하세요: %SCRIPT_DIR%.env
) else (
    echo [OK] .env 파일 이미 존재
)

:: 7. Windows 작업 스케줄러 등록 (매일 오전 9시)
echo [*] 작업 스케줄러 등록 중...
schtasks /Create ^
    /SC DAILY ^
    /TN "YTMP3-Batch" ^
    /TR "\"%SCRIPT_DIR%run.bat\"" ^
    /ST 09:00 ^
    /RU "%USERNAME%" ^
    /F > nul 2>&1

if errorlevel 1 (
    echo [WARNING] 작업 스케줄러 등록 실패.
    echo           관리자 권한으로 setup.bat을 다시 실행하거나,
    echo           작업 스케줄러를 수동으로 설정하세요.
    echo           실행 파일: %SCRIPT_DIR%run.bat
) else (
    echo [OK] 작업 스케줄러 등록 완료 ^(매일 오전 9:00^)
    echo       작업 이름: YTMP3-Batch
    echo       [참고] 작업 스케줄러 GUI에서 해당 작업을 열어 암호를 설정해야
    echo              할 수 있습니다 ^(로그아웃 상태에서도 실행하려면^)
)

echo.
echo ============================================
echo  설정 완료!
echo ============================================
echo  다음 단계:
echo  1. config.json 에 유튜브 플리 URL과 저장 폴더를 설정하세요
echo  2. .env 에 Discord 봇 토큰과 채널 ID를 입력하세요
echo  3. 테스트: python downloader.py --url "유튜브URL"
echo  4. 봇 실행: python bot.py
echo ============================================

endlocal
pause
