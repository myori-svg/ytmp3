@echo off
:: 작업 스케줄러 진입점 - 절대경로 사용 (스케줄러 환경에서 PATH 불신뢰)
set SCRIPT_DIR=%~dp0
"%SCRIPT_DIR%venv\Scripts\python.exe" "%SCRIPT_DIR%downloader.py" >> "%SCRIPT_DIR%logs\scheduler.log" 2>&1
