@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title D1 研究工具 - 開啟工作台
echo.
echo [1] Anti-Gambling Trader 本機績效分析
echo [2] JEV 3D 離線模擬展示
echo [3] D1 大戶換手雷達正式網站
echo [4] 交易績效 JSON 匯入頁
echo.
choice /c 1234 /n /m "請按數字選擇 1 / 2 / 3 / 4："
if errorlevel 4 goto :json
if errorlevel 3 goto :d1
if errorlevel 2 goto :jev
if errorlevel 1 goto :anti
:anti
set "PYTHON_EXE=%~dp0.research-tools\anti-gambling-trader-tw\.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" goto :noinstall
"%PYTHON_EXE%" -m core.ui --mode browser
goto :end
:jev
set "JEV_PYTHON=%~dp0.research-tools\jev-trading-command-center\.venv\Scripts\python.exe"
if not exist "%JEV_PYTHON%" goto :noinstall
echo [JEV] 本機合成 DEMO，不會呼叫 Jev API 或執行交易。
start "" powershell.exe -NoProfile -Command "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:8765/stage.html'"
"%JEV_PYTHON%" -B "%~dp0.research-tools\jev-trading-command-center\run_app.py" --demo --port 8765
goto :end
:d1
start "" "https://a58922314-lab.github.io/tw-holder-radar/"
exit /b 0
:json
start "" "https://a58922314-lab.github.io/tw-holder-radar/strategy-validation.html"
exit /b 0
:noinstall
echo [錯誤] 尚未完成工具安裝。請先雙擊 install-research.cmd。
:end
echo.
echo [提示] 如果畫面無法開啟，請保留錯誤訊息供除錯。
pause
exit /b 0
