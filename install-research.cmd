@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title D1 研究工具 - 安裝
echo.
echo [D1] 安裝 Anti-Gambling Trader 和 JEV 離線展示
echo.
if not exist "scripts\setup-research.ps1" (
  echo [錯誤] 缺少安裝腳本。請先解壓縮整個專案 ZIP，不能單獨下載本 CMD。
  goto :failed
)
echo [資訊] 此版本無須安裝 Git，會直接下載程式壓縮檔。
where py >nul 2>nul
if not errorlevel 1 goto :start
where python >nul 2>nul
if errorlevel 1 (
  echo [錯誤] 找不到 Python 3.11 以上。請先安裝：
  echo https://www.python.org/downloads/windows/
  goto :failed
)
:start
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup-research.ps1"
if errorlevel 1 (
  echo.
  echo [失敗] 安裝或檢查未完成。請截圖這個視窗中的錯誤訊息。
  goto :failed
)
echo.
echo [完成] 已完成本機安裝和內建 DEMO 檢查。
echo 請雙擊 open-research.cmd 選擇研究工作台。
echo 私人報告不會上傳 GitHub；未啟動任何實盤下單。
pause
exit /b 0
:failed
echo.
echo 取得詳細說明：
echo https://github.com/a58922314-lab/tw-holder-radar/blob/main/docs/INTEGRATION.md
pause
exit /b 1
