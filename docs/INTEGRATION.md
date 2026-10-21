# 大戶換手雷達 × Anti-Gambling Trader × JEV：第一階段整合

## 已整合的功能
- 網站新增「交易績效驗證」入口（strategy-validation.html），只用瀏覽器本機讀取 JSON，**不會上傳私人交易紀錄**。
- 新增 Windows PowerShell 安裝與驗收腳本，將 Anti-Gambling Trader 與 JEV 分別下載至被 Git 忽略的 .research-tools/。
- 新增已平倉交易 JSON 報告生成腳本，結果留在被忽略的 .research-reports/。
- JEV 僅跑離線 DEMO；**不串接 D1 台股訊號、不呼叫 Jev API、不送真單**。

> 重要：目前 D1 官方集保資料只有一個週別，融資及 D1 條件尚未完成。本站不會把圖片範例當真實回測，也不會以集保持股清單假裝已平倉交易。

## Windows 一鍵安裝（建議）
1. 前往 https://github.com/a58922314-lab/tw-holder-radar ，按 Code → Download ZIP，將**整個 ZIP 完整解壓縮**。
2. 請先安裝 Git for Windows（https://git-scm.com/downloads/win）與 Python 3.11+（https://www.python.org/downloads/windows/）。本工具不會自行修改系統環境或要求管理員權限。
3. 在解壓縮的專案根目錄雙擊 **install-research.cmd**，它會檢查安裝前置條件，呼叫 scripts/setup-research.ps1，安裝兩套工具與驗收離線範例。
4. 安裝成功後雙擊 **open-research.cmd**，選擇 1 開啟反詐投資王、2 開啟 JEV 離線 3D 模擬展示、3 開啟 D1 網站或 4 開啟 JSON 匯入工作台。
5. 如果看到錯誤，保留黑色視窗並截圖；不要輸入真實券商或 AI API 金鑰。

## Windows 安裝（本機 Windows 10/11）：PowerShell 進階方式
安裝 Git for Windows 與 Python 3.11+，打開 PowerShell 進入本 repo 目錄，執行以下指令：

    powershell -ExecutionPolicy Bypass -File .\scripts\setup-research.ps1

不需要 JEV 時，可加 -SkipJev。腳本下載兩個專案，首次下載固定於 2026-10-21 已檢查的公開程式版本；已存在的資料夾會保留，**不會強迫重設**。Anti 的虛擬環境會安裝 Excel 支援；JEV 的虛擬環境安裝其 requirements.txt。完成後執行 Anti demo 與 JEV demo --check（未指定 SkipJev 時）。安裝或測試失敗時將顯示錯誤。

> 本文件中的安裝是讓使用者在 **自己的 Windows 電腦上執行**，GitHub Pages 不提供 Python 主機。為避免供應鏈風險，腳本固定到檢查過的提交，不自動追蹤最新版。安裝前仍應自行審查第三方程式；未經本人明確同意不輸入 API 金鑰。

## 啟動研究工具

從本專案根目錄的 PowerShell 執行：

    & ".\.research-tools\anti-gambling-trader-tw\.venv\Scripts\python.exe" -m core.ui --mode browser

JEV 離線展示（另開視窗）：

    & ".\.research-tools\jev-trading-command-center\.venv\Scripts\python.exe" -B ".\.research-tools\jev-trading-command-center\run_app.py" --demo --port 8765

打開 http://127.0.0.1:8765/stage.html。離線 DEMO 為合成行情與合成模型狀態。

## 產生交易績效 JSON

準備自己**已完成買入與賣出**的 CSV 交易紀錄。至少包括代號、已扣成本的淨損益、損益幣別與可靠平倉時間；欄位範例參考 [Anti-Gambling 的官方 README](https://github.com/mars-tw/anti-gambling-trader-tw#輸入格式)。

    powershell -ExecutionPolicy Bypass -File .\scripts\validate-trades.ps1 -CsvPath "C:\Users\你的帳號\Desktop\trades.csv"

執行後產出 .research-reports/analysis-*.json。即使系統判定勸退、回傳退出碼 2，只要 JSON 成功建立，也應完整閱讀風險警告，不能當成驗證通過。

開啟本網站的「交易績效驗證」，點選這個 JSON 即可查看：
- 樣本內裁決與理由
- 筆數、勝率、期望值、淨損益與可靠性條件
- 已完成交易按時間切分的歷史 holdout
- 各策略描述統計與資料完整性提醒

網站不會上傳或儲存檔案。請**不要把私人交易 JSON 或券商資料加入 Git 版本庫**，更不能放入公開 GitHub Pages data/。

## 尚未完成的第二階段
1. D1 規則與集保歷史週別充足後，再設計無未來資料洩漏的歷史回測：明確選股訊號日期、可成交進場價、停損停利、手續費與稅。
2. 將回測產生的已平倉交易序列輸給 Anti-Gambling 統計引擎；**不能把未成交候選清單直接當交易績效**。
3. 若確有需要，將 JEV「多週期、決策回執、風控」思想改寫為台股專用元件，不直接接 USDT 永續合約或 TypeSafe 金鑰。
4. 等台股籌碼資料與樣本外回測可信，再討論正式上線的 AI 證據檢查頁。

以上都不提供實盤自動下單，且統計結果不構成投資建議。
