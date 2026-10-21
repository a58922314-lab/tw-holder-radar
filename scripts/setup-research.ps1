# 以 PowerShell 在本專案根目錄執行：powershell -ExecutionPolicy Bypass -File .\scripts\setup-research.ps1
# 僅建立本機虛擬環境與離線模擬；不啟用 API 或實盤下單。
param([switch]$SkipJev)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ToolHome = Join-Path $Root ".research-tools"
$AntiSha = "8609cef73718a056fddb74201fc304f174fa1553"
$JevSha = "b6f5b2a5b9b5d8cc06523c6563125cdf2177acc8"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "找不到 Git。請先安裝 Git for Windows。"
}
$PyName = "python"
$PyArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $PyName = "py"
    $PyArgs = @("-3")
} elseif (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "找不到 Python。請先安裝 Python 3.11 或更新版。"
}
& $PyName @PyArgs -c "import sys; print(sys.version); sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "本整合需要 Python 3.11+。" }

New-Item -ItemType Directory -Force -Path $ToolHome | Out-Null
function Checkout-Reviewed([string]$Name, [string]$Url, [string]$Sha) {
    $dest = Join-Path $ToolHome $Name
    if (Test-Path $dest) {
        if (-not (Test-Path (Join-Path $dest ".git"))) {
            throw "$dest 已存在，但不是 Git 專案。請先自行檢查，程式不會覆蓋。"
        }
        Write-Host "沿用既有本機資料夾（不覆蓋、不重設）: $dest"
        return $dest
    }
    Write-Host "下載 $Name..."
    & git clone --depth 1 --branch main $Url $dest | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "下載失敗: $Name" }
    & git -C $dest fetch --depth 1 origin $Sha | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "無法取得審查過的版本: $Name" }
    & git -C $dest checkout --detach $Sha | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "無法切換版本: $Name" }
    return $dest
}
$Anti = Checkout-Reviewed "anti-gambling-trader-tw" "https://github.com/mars-tw/anti-gambling-trader-tw.git" $AntiSha
$AntiPython = Join-Path $Anti ".venv\Scripts\python.exe"
if (-not (Test-Path $AntiPython)) {
    & $PyName @PyArgs -m venv (Join-Path $Anti ".venv")
    if ($LASTEXITCODE -ne 0) { throw "無法建立 Anti-Gambling Python 虛擬環境" }
}
Push-Location $Anti
try {
    & $AntiPython -m pip install -e ".[excel]"
    if ($LASTEXITCODE -ne 0) { throw "Anti-Gambling 安裝失敗" }
    Write-Host "檢查反詐投資王內建範例..."
    & $AntiPython -m core.cli demo
    # 此專案遇到「勸退」判定時可能故意回傳 exit code 2。
    if ($LASTEXITCODE -notin @(0, 2)) { throw "Anti-Gambling DEMO 執行失敗" }
} finally { Pop-Location }
if (-not $SkipJev) {
    $Jev = Checkout-Reviewed "jev-trading-command-center" "https://github.com/mars-tw/jev-trading-command-center.git" $JevSha
    $JevPython = Join-Path $Jev ".venv\Scripts\python.exe"
    if (-not (Test-Path $JevPython)) {
        & $PyName @PyArgs -m venv (Join-Path $Jev ".venv")
        if ($LASTEXITCODE -ne 0) { throw "無法建立 JEV Python 虛擬環境" }
    }
    Push-Location $Jev
    try {
        & $JevPython -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw "JEV 相依套件安裝失敗" }
        & $JevPython -B run_app.py --demo --check
        if ($LASTEXITCODE -ne 0) { throw "JEV 離線 DEMO 自我檢查失敗" }
    } finally { Pop-Location }
}
Write-Host ""
Write-Host "本機工具已安裝並完成上述檢查；並未啟動真實市場或券商帳戶。"
Write-Host "Anti 工作台：& '$AntiPython' -m core.ui --mode browser"
if (-not $SkipJev) {
    Write-Host "JEV 離線展示：& '$JevPython' -B '$Jev\run_app.py' --demo --port 8765"
    Write-Host "啟動後開啟：http://127.0.0.1:8765/stage.html"
}
Write-Host "績效報告產生：.\scripts\validate-trades.ps1 -CsvPath '你的交易.csv'"
