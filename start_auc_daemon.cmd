@echo off
setlocal
for /f "delims=" %%k in ('powershell -NoProfile -Command "(Get-Content \"%USERPROFILE%\.local\share\opencode\auth.json\" -Raw | ConvertFrom-Json).deepseek.key"') do set DEEPSEEK_API_KEY=%%k
set PYTHONIOENCODING=utf-8
cd /d "C:\Users\ht_34\Documents\Default Project\MeetingAssist"
"C:\Users\ht_34\AppData\Local\Programs\Python\Python311\python.exe" auc_auto.py