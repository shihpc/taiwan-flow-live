# taiwan-flow-live — 即時市場資金流向

手機網頁看台股**盤中即時資金流向**，按「🔄 更新」拉最新快照。分 **產業別** 與 **產業鏈** 兩頁，點類股看成分股；產業鏈可再下鑽到**次產業**。架構參考姊妹專案 taiwan-flows，但用即時快照而非盤後三大法人。

## 資料與口徑

- **來源**：FinMind `taiwan_stock_tick_snapshot`（Sponsor 級，一次 request 取全市場），**盤中即時更新、盤後為當日最終值**。
- **指標（綜合，皆由快照即時欄位計算，非盤後三大法人）**：
  - 成交值＝`total_amount`（盤中累計成交金額）
  - 淨流入＝漲家成交額 − 跌家成交額（紅綠資金）
  - 均漲跌＝成交額加權漲跌幅；漲/跌家數
- **大盤指數（TSE 加權＝snapshot `001`、OTC 櫃買＝`101`）**：即時指數值、漲跌點、漲跌%、成交量/額。
- **指數貢獻點數**：個股對大盤漲跌點的影響 `pts_i = ΔIndex × (Δ價_i×發行股數_i) / Σ同市場(Δ價×股數)`
  （構成股＝該市場普通股，排除 ETF），**類股加總＝指數漲跌點**（自洽）；前端可切「加權/櫃買」。
  例：6/26 台積電 −408 點、半導體業 −850 點（全市場 −1,683 點）。
- **分類**：產業別（`TaiwanStockInfo`，互斥）+ 產業鏈（`TaiwanStockIndustryChain`，多對多、含次產業）。
- 已排除指數 pseudo-row（如 `001`=加權指數）——只計真實個股/ETF。
- 權重資料：`TaiwanStockInfo.type`（twse/tpex）+ `TaiwanStockShareholding.NumberOfSharesIssued`（發行股數，存入 classify.json，meta.py 重建時更新）。

## 架構（純 GitHub，無自有伺服器）

```
FinMind tick_snapshot ──(GitHub Actions: src/snapshot.py)──► data/live.json ──► GitHub Pages
                                       ▲                                         │ 讀 live.json + classify.json
                          網頁「🔄更新」workflow_dispatch ◄───────────────────────┘ 前端聚合呈現
```

- 「更新」按鈕用 `workflow_dispatch` 觸發 Action（PAT 存瀏覽器 localStorage，同 taiwan-flows 作法），Action 重算 `live.json` 並 commit，前端輪詢 raw `live.json` 直到時間戳更新。
- **延遲**：按鈕後約 **1–2 分鐘**才更新（Action 啟動+跑+commit+傳播）。要秒級需另接即時代理（非本專案範圍）。

## 檔案

```
src/fin.py        FinMind client（token + snapshot/api）
src/meta.py       建 data/classify.json（代號→名稱/產業別/產業鏈/次產業配對；偶爾跑）
src/snapshot.py   取快照+聚合 → data/live.json（Action 與本機共用）
src/server.py     本機開發伺服器（靜態 + /api/refresh 即時重算；正式版不需要）
index.html        前端（手機，vanilla JS）
data/classify.json  分類表（commit）
data/live.json      即時快照聚合（Action 產生、commit）
.github/workflows/snapshot.yml  workflow_dispatch（可選盤中 cron）
```

## 部署

1. 建 GitHub repo，推上去；Settings → Pages → 由 `main` 分支根目錄發佈。
2. Settings → Secrets → Actions 新增 `FINMIND_TOKEN`（你的 FinMind Sponsor token）。
3. 改 `index.html` 最上方 `REPO`（owner/repo/branch）。
4. 先在本機跑一次 `python src/meta.py` 與 `python src/snapshot.py` 產出 `data/classify.json`、`data/live.json` 並 commit（首屏要有資料）。
5. 手機開 Pages 網址 → 「🔄 更新」首次會要求貼上 GitHub fine-grained PAT（需該 repo 的 **Actions: read/write**），存於瀏覽器本機。Shift+點更新可清除 Token。

## 本機開發

```bash
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
set FINMIND_TOKEN=<你的 token>          # 或放 .env（不進 git）
python src/meta.py                      # 建分類表（偶爾）
python src/server.py                    # http://127.0.0.1:8899，按「更新」走 /api/refresh 即時重算
```

> `classify.json` 變動慢（產業歸屬），偶爾重跑 `meta.py` 即可。
