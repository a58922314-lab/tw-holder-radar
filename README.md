# 大戶換手雷達 V2

臺股上市／上櫃 400 張以上集保持股變化雷達。黑金色網頁、週增與週減 TOP50、續買／回頭車／下車／續賣、個股查詢、CSV 匯入與收藏。

網站：https://a58922314-lab.github.io/tw-holder-radar/

## 啟用

1. 至 **Settings → Pages → Build and deployment → Source** 選擇 **GitHub Actions**。
2. 至 **Actions → Publish Holder Radar website → Run workflow** 初次發布網站。
3. 至 **Actions → Weekly TDCC holding updates → Run workflow** 執行第一次官方資料擷取，開啟執行紀錄確認官方 API 是否成功。
4. 以後工作日台灣時間 18:30 保存行情，週六 11:30 / 18:30 檢查最新集保分散表。GitHub 排程不保證準點。

## 真實資料與歷史累積

- 官方大戶是 **TDCC 400,001 股以上分級合計（12–15級）**；變化單位是 **百分點 pp**。
- 系統在 `data/auto_snapshots.json` 成功產生、並完成網站發布之前，只顯示**2026-10-16 圖片案例**，**不是當日行情**。
- 首次官方擷取只有 1 個集保週別，**兩週**才有大戶變化和排行榜，**三週**才有完整四類分類。
- 尚未介接融資與 D1；沒有資料的欄位是空白，不是假造為 0。
- 官方服務停擺可能導致更新失敗；請檢查 Actions 日誌。網址穩定不代表官方資料已更新。
- 收藏和 CSV 匯入存在瀏覽器本機；不會同步到 GitHub。

## 網頁部署 vs 官方資料更新

- `.github/workflows/deploy.yml` 負責網頁發布，與集保官方 API **無關**。
- `.github/workflows/refresh.yml` 依排程呼叫 `scripts/refresh.py`，儲存官方資料並重新發布網站。資料不足時不會建立偽造排名。
- 原圖內建範例與官方快照必須依畫面標記區分。

不構成任何投資建議。
