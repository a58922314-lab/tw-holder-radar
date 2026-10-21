# 用法：powershell -ExecutionPolicy Bypass -File .\scripts\validate-trades.ps1 -CsvPath C:\path\trades.csv
# 只分析「已平倉」交易；結果僅儲存本機 .research-reports/，絕不自動上傳 GitHub。
param(
    [Parameter(Mandatory=$true)][string]$CsvPath
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Anti = Join-Path $Root ".research-tools\anti-gambling-trader-tw"
$Python = Join-Path $Anti ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "尚未安裝本機分析引擎。請先執行 .\scripts\setup-research.ps1"
}
$InputFile = (Resolve-Path -LiteralPath $CsvPath -ErrorAction Stop).Path
if (-not (Test-Path -LiteralPath $InputFile -PathType Leaf)) {
    throw "找不到交易紀錄檔"
}
$ReportDir = Join-Path $Root ".research-reports"
New-Item -ItemType Directory -Path $ReportDir -Force | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$ReportPath = Join-Path $ReportDir ("analysis-" + $Stamp + "-" + [guid]::NewGuid().ToString("N").Substring(0,8) + ".json")
Push-Location $Anti
try {
    & $Python -m core.cli analyze $InputFile --json $ReportPath
    $Code = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($Code -notin @(0, 2) -or -not (Test-Path -LiteralPath $ReportPath -PathType Leaf)) {
    throw "分析未完成（退出碼 $Code）；原始交易紀錄未修改。"
}
Write-Host ""
Write-Host "分析 JSON 已儲存於：$ReportPath"
Write-Host "請打開 strategy-validation.html，選擇此 JSON 查看。"
if ($Code -eq 2) {
    Write-Warning "統計引擎回傳勸退/風險訊號（退出碼 2），並非單純的安裝故障。請閱讀完整報告。"
}
