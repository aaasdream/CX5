# CX5

Mazda CX-5 中古車價格監控（資料來源：8891）。

儀表板：https://aaasdream.github.io/CX5/

## 找車條件

硬需求是 **360 度環景 + 前座通風座椅**，這兩樣 2025 年式起才全車系標配，
所以目標鎖定 **2025 年式 20S Select Plus**（地區以高雄優先）。
要放寬範圍改 `analyze.py` 開頭的 `MIN_YEAR` / `TARGET_TRIM`。

## 流程

由人手動觸發，不做自動排程：

```bat
python scrape.py            # 抓 8891 在售清單 -> raw/ + data/listings_<date>.json
python parse.py 2026-08-17  # 全站統計 -> data/history.json
python analyze.py 2026-08-17  # 篩目標車 -> data/targets_<date>.json
python build_dashboard.py   # 產生 dashboard.html / index.html
python local\summarize.py 2026-08-17   # 一行摘要
```

## 檔案

| 路徑 | 說明 |
|---|---|
| `scrape.py` | 抓取 8891（純標準庫，頁面為伺服器端渲染，不需 Playwright） |
| `parse.py` | 解析 raw 檔並統計中位／P25／P75 |
| `analyze.py` | 依找車條件篩出目標車源，標記可疑價格 |
| `build_dashboard.py` | 產生網頁：目標車源表 + 目標車價走勢 + 全站行情 |
| `local/summarize.py` | 每日一行摘要（不上傳） |
| `raw/8891_<date>.txt` | 原始擷取：`年式\|車型\|里程\|價格` |
| `data/history.json` | 每日統計歷史 |
| `data/listings_<date>.json` | 當日完整快照，以 8891 車輛 ID 為鍵 |

## 備註

- 每台車有穩定的 8891 車輛 ID，可用來比對新上架與降價。
- 抓取間隔 2 秒、一次約 6 個請求，屬低頻自用查詢。
