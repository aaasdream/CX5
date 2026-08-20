# 紙上台股實驗室

一場公開記錄的**台股虛擬交易實驗**：初始資金新台幣 50 萬（虛擬），為期三個月
（2026-08-21 至 2026-11-21），由 AI 依每日新聞與總經數據自主決策並記帳。

**成果頁面 → https://aaasdream.github.io/CX5/stock/**

> 所有買賣都只寫進資料庫，沒有任何真實下單、沒有真實資金流。
> 頁面內容是 AI 的推論紀錄，**不構成投資建議**。

成果頁會隨每日 Git 更新持續增長，集中顯示賽程進度、總資產、相對大盤績效、
回撤、現金／持股配置、逐日績效明細、每筆成交，以及可搜尋的每日決策與觀察。

---

## 這個實驗在測什麼

不是測「AI 會不會選股」——三個月約 60 個交易日，在一個年化波動 36% 的市場裡，
這個樣本數不足以區分技術與運氣，講白了很大一部分就是運氣。

真正被記錄下來、而且事後可以檢驗的是這些：

- 判斷**寫在結果發生之前**，不是事後回顧
- 決定**不動**的日子也要寫下理由，否則無法分辨「判斷正確」與「根本沒判斷」
- 每個部位都有明確的目標價、停損價與「什麼情況代表我看錯了」
- 帳本任何人都能拿公開資料從頭重算

賽制與詳細規範見 [RULES.md](RULES.md)。

---

## 防止自欺的三道設計

這套系統的重點不在功能多，而在**拿掉能夠美化績效的自由度**：

**一、成交價不能指定。**
`ledger.buy()` / `ledger.sell()` 沒有 price 參數。價格只能來自
`market.execution_quote()`，取證交所當下的即時成交價。呼叫端沒有選價格的餘地。

**二、休市不能交易。**
收盤後呼叫買賣會拋 `MarketClosed`，不補單、不以收盤價追認。
當天沒跑到就是沒交易，跟真人錯過盤一樣。

這條規則消除了最常見的作弊型態：**收盤後才決定「今天要買」，等於看完全天走勢才下注。**

**三、帳本可被獨立重算。**
`audit.py` 不信任資料庫裡任何彙總欄位，只從 `trades` 表逐筆重建現金與持倉，
再拿 FinMind 公開日線比對每筆成交價是否落在當日高低價區間內。

```bash
python audit.py                # 完整稽核（會連線查證成交價）
python audit.py --no-network   # 只做內部一致性檢查
python audit.py --json         # 機器可讀，給驗證方的程式吃
```

檢查六項：現金流水、持倉重建、費用重算、交易時段、成交價區間、帳務恆等式。
任何一項 FAIL 就代表這本帳不可信。

---

## 每日流程

```bash
python pt.py quote              # 現在能不能交易？即時報價多少？
python pt.py sync               # 抓當日行情與跨市場指標
python pt.py buy 2330 1000 --reason "..." --thesis-title "..." --target 2600 --stop 2250
python pt.py decision --code 2454 --action HOLD --reason "..."   # 不動也要記
python pt.py news --title "..." --summary "..." --source ... --importance 4
python pt.py brief --stance "..." --macro "..." --outlook "..."
python pt.py mark               # 寫入當日淨值快照
python pt.py record             # 不可覆寫的每日 Markdown + CSV 稽核資料
python pt.py report             # 產生 index.html 與 data.json
```

`python pt.py daily` 會把 sync / mark / record / report 一次做完。

每天結束後把 `db/portfolio.db`、`data.json`、`index.html` 一起 commit。
**git 的時間戳就是「判斷寫在結果之前」的證明**，這是整個實驗可信度的基礎。

---

## 交易成本

| 項目 | 費率 |
|---|---|
| 手續費 | 成交金額 × 0.1425% × 0.6 折，捨去到元，單筆最低 20 元 |
| 證交稅 | 賣出時 × 0.3%，捨去到元 |

一律採無條件捨去而非四捨五入：各券商實作有差異，
而低估成本會讓紙上績效比真實情況好看，所以取對帳本不利的那一邊。

買進手續費滾入持股成本，賣出費稅從實收扣除，
因此 `positions.avg_cost` 就是真正的成本，不需另外攤提。

---

## 自我約束的風控上限

| 限制 | 值 |
|---|---|
| 單一個股佔總資產 | ≤ 12% |
| 單筆進場佔總資產 | ≤ 10% |
| 常態現金水位 | ≥ 20% |

違反時 `buy()` 會拋 `RiskViolation`；正式競賽沒有覆蓋參數。

這些數字是針對賽制的不對稱性訂的：**腰斬即出局**，
意味著破產風險不是可以用報酬率補償的東西。

---

## 檔案結構

```
stock/
  pt.py               每日操作的命令列介面
  audit.py            獨立稽核器（給驗證方用）
  audit/*.csv         人類可讀、可重算的資料表匯出
  records/            不可覆寫的每日決策紀錄
  RULES.md            賽制規則書
  index.html          產生的成果頁面（GitHub Pages 服務這支）
  data.json           同樣內容的機器可讀版本
  db/portfolio.db     SQLite：帳本、論點、決策、新聞、行情
  paper/
    config.py         資金、費率、風控上限、觀察清單
    db.py             資料表結構
    fees.py           台股交易成本計算
    market.py         行情抓取與成交價決定（含休市判斷）
    ledger.py         買賣、持倉、淨值快照
    journal.py        新聞、簡報、決策、論點、行事曆
    report.py         匯出 JSON 與產生網頁
    template.html     頁面模板
```

## 資料來源

- **FinMind** — 台股日線 OHLCV、三大法人買賣超（需 `FINMIND_TOKEN` 環境變數）
- **Yahoo Finance** — 加權指數、費半、美債殖利率、匯率、原油、黃金、比特幣
- **證交所 MIS**（透過 twstock）— 盤中即時報價，成交價的唯一來源

```bash
pip install -r requirements.txt
setx FINMIND_TOKEN "你的token"      # 免費註冊，600 次/小時
```
