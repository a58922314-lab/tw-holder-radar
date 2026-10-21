# D1 Windows 10/11 - reviewed source installer (no Git requirement).
# Run from project root: powershell -ExecutionPolicy Bypass -File .\scripts\setup-research.ps1
# Installs local-only research tools; never enables live trading.
param([switch]$SkipJev)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
# Windows PowerShell 5.1 requires a UTF-8 BOM for Chinese text.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ToolHome = Join-Path $Root ".research-tools"
$AntiSha = "8609cef73718a056fddb74201fc304f174fa1553"
$JevSha = "b6f5b2a5b9b5d8cc06523c6563125cdf2177acc8"

$PyName = "python"
$PyArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $PyName = "py"
    $PyArgs = @("-3")
} elseif (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "找不到 Python。請先安裝 Python 3.11 或更新版：https://www.python.org/downloads/windows/"
}
& $PyName @PyArgs -c "import sys; print(sys.version); sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "本整合需要 Python 3.11+。" }

New-Item -ItemType Directory -Force -Path $ToolHome | Out-Null
function Install-Reviewed([string]$Name, [string]$Sha) {
    $dest = Join-Path $ToolHome $Name
    $marker = Join-Path $dest ".d1-source-commit"
    if (Test-Path -LiteralPath $dest) {
        # Archive installations carry a SHA marker. Legacy Git checkouts are checked if Git is available.
        $existingSha = $null
        if (Test-Path -LiteralPath $marker) {
            $existingSha = (Get-Content -LiteralPath $marker -Raw).Trim()
        } elseif ((Test-Path -LiteralPath (Join-Path $dest ".git")) -and (Get-Command git -ErrorAction SilentlyContinue)) {
            $existingSha = (& git -C $dest rev-parse HEAD | Select-Object -First 1).Trim()
            if ($LASTEXITCODE -ne 0) { throw "無法驗證既有專案版本：$dest" }
        }
        if ($existingSha -ne $Sha) {
            throw "資料夾已存在但版本無法確認（或不是預期版本）：$dest。請先備份或重新命名舊資料夾；程式不會覆蓋。"
        }
        Write-Host "已存在符合版本的本機資料夾：$dest"
        return $dest
    }
    $url = "https://github.com/mars-tw/$Name/archive/$Sha.zip"
    $staging = Join-Path $ToolHome ("download-" + [guid]::NewGuid().ToString("N"))
    $zip = Join-Path $staging "source.zip"
    $unpack = Join-Path $staging "unpacked"
    New-Item -ItemType Directory -Path $staging | Out-Null
    try {
        Write-Host "下載 $Name 的固定版本 $Sha..."
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing -TimeoutSec 90
        if ((Get-Item -LiteralPath $zip).Length -lt 1024) { throw "下載內容不完整：$Name" }
        Expand-Archive -LiteralPath $zip -DestinationPath $unpack
        $found = @(Get-ChildItem -LiteralPath $unpack -Directory)
        if ($found.Count -ne 1) { throw "壓縮檔內容異常：$Name" }
        Move-Item -LiteralPath $found[0].FullName -Destination $dest
        Set-Content -LiteralPath (Join-Path $dest ".d1-source-commit") -Encoding Ascii -Value $Sha
    } catch {
        # Never reuse a partial extraction on the next installation attempt.
        if (Test-Path -LiteralPath $dest) {
            if (-not (Test-Path -LiteralPath $marker)) {
                Remove-Item -LiteralPath $dest -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
        throw
    } finally {
        Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    }
    return $dest
}
$Anti = Install-Reviewed "anti-gambling-trader-tw" $AntiSha
$AntiPython = Join-Path $Anti ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $AntiPython)) {
    & $PyName @PyArgs -m venv (Join-Path $Anti ".venv")
    if ($LASTEXITCODE -ne 0) { throw "無法建立 Anti-Gambling Python 虛擬環境" }
}
Push-Location $Anti
try {
    & $AntiPython -m pip install -e ".[excel]"
    if ($LASTEXITCODE -ne 0) { throw "Anti-Gambling 安裝失敗" }
    Write-Host "檢查反詐投資王內建範例..."
    & $AntiPython -m core.cli demo
    # A gambling-risk verdict may intentionally return code 2.
    if ($LASTEXITCODE -notin @(0, 2)) { throw "Anti-Gambling DEMO 執行失敗" }
} finally { Pop-Location }
if (-not $SkipJev) {
    $Jev = Install-Reviewed "jev-trading-command-center" $JevSha
    $JevPython = Join-Path $Jev ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $JevPython)) {
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
Write-Host "本機工具已安裝並通過離線示範檢查；未啟動實盤交易。"
Write-Host "Anti：& '$AntiPython' -m core.ui --mode browser"
if (-not $SkipJev) {
    Write-Host "JEV：& '$JevPython' -B '$Jev\run_app.py' --demo --port 8765"
    Write-Host "啟動後開啟：http://127.0.0.1:8765/stage.html"
}
Write-Host "可雙擊 open-research.cmd 開啟選單。"
