@echo off
chcp 65001 >nul
cd /d "%~dp0"
if "%~1"=="" (
  echo 用法: 把 m4a/wav/mp3 拖到本脚本上,或:
  echo   transcribe_file.cmd "录音文件.m4a"
  echo 摘要会写到音频所在文件夹。
  pause
  exit /b 1
)
python app.py --file "%~1"
if errorlevel 1 pause
exit /b %ERRORLEVEL%
