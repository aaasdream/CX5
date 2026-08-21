# 每日流程 SOP

每個交易日 10:00 執行。這份文件是給「每天早上那個沒有記憶的自己」看的 ——
排程任務每次都是全新 session，不記得昨天想過什麼，所有脈絡都必須從資料庫與這份文件取得。

工作目錄：`C:\Aking\STOCK_CHATGPT\CX5\stock_GPT`

---

## 硬性規則（違反即出局，見 RULES.md）

1. **只有台股交易時段（週一至週五 09:00–13:30）能交易。** 收盤後不補單、不追認。
2. **不能指定成交價。** 價格只能由 `pt.py buy/sell` 內部取證交所即時報價。
3. **不能改寫歷史紀錄。** 判斷錯了就寫新的紀錄說明，不覆蓋舊的。
4. **每天都要 commit 並 push**，即使沒有交易。git 時間戳是可信度的基礎。

如果執行時已經收盤（例如任務延遲到 14:00 才跑）：
**照樣做完研究、寫簡報與決策、commit push，但不要交易。**
那天就是沒有交易，據實記錄原因。

---

## 步驟

### 1. 先看清楚現在的狀態

```bash
python pt.py quote          # 現在能不能交易？各檔即時價與昨收比較
python pt.py status         # 現金、持倉、損益、兩週內事件
python pt.py sync           # 抓昨日收盤日線與跨市場指標
```

`status` 會列出兩週內的行事曆事件。**先看有沒有今天或明天的事件**，
特別是財報、FOMC、連假前最後交易日 —— 這些會改變今天該做什麼。

### 2. 讀新聞、做研究

用 WebSearch / WebFetch 查當天的關鍵發展。至少涵蓋：

- **總經**：美債殖利率（尤其 30 年期）、油價、美元指數、聯準會發言
- **美股**：那斯達克、費半收盤，AI 族群個別走勢
- **台股**：三大法人買賣超、外資期貨部位、成交量
- **持股個別消息**：財報、營收、法說、產業新聞
- **地緣政治**：目前主線是美伊局勢

法人籌碼可以直接抓：

```python
requests.get("https://api.finmindtrade.com/api/v4/data", params={
    "dataset": "TaiwanStockTotalInstitutionalInvestors",
    "start_date": "近一週", "token": os.environ["FINMIND_TOKEN"]})
```

**把讀到的重要新聞記進資料庫**（不是只放在腦子裡）：

```bash
python pt.py news --title "..." --summary "..." --source "..." --url "..." \
  --category macro|tw_market|ai|crypto|geopolitics|company \
  --sentiment BULLISH|BEARISH|NEUTRAL|MIXED --importance 1-5 --codes "2330,2454"
```

### 3. 做決策

先問三個問題，順序不能顛倒：

1. **今天有沒有出局風險？** 帳戶離腰斬（250,000）還有多遠？持股集中度？
   接下來三天有沒有重大事件？
2. **手上的部位，論點還成立嗎？** 對照 `theses` 表裡當初寫的
   「什麼情況代表我看錯了」。已經觸發就處理，不要凹。
3. **有沒有值得新進場的機會？** 沒有就沒有 —— 空手是合法的決策。

交易：

```bash
python pt.py buy 2330 1000 --reason "為什麼是今天、為什麼是這檔" \
  --thesis-title "一句話的買進理由" --rationale "完整論證" \
  --catalysts "預期的催化劑" --risks "什麼會讓這個論點失效" \
  --target 2600 --stop 2250 --horizon "至 Q4 法說" --conviction 3

python pt.py sell 2330 1000 --reason "..." --outcome "論點對了還是錯了、錯在哪"
```

**沒有交易的日子，決策一樣要記錄：**

```bash
python pt.py decision --action HOLD|WATCH|PASS --reason "..." [--code 2330]
```

只記錄有交易的日子，事後無法分辨「判斷正確」與「根本沒判斷」。

### 4. 寫當日簡報

```bash
python pt.py brief --stance "一句話的整體立場" \
  --macro "..." --tw "..." --ai "..." --crypto "..." \
  --events "今天與近期的關鍵事件" --actions "今天做了什麼、為什麼" \
  --outlook "對接下來幾天的預期"
```

`--outlook` 最重要：**寫下可以被打臉的預期**。
「震盪整理」這種說法沒有資訊量；要寫成「我預期不會出現單日 -500 點以上的殺盤，
若跌破月線 44,009 且外資賣超 300 億以上，代表我這個判斷錯了」。

### 5. 檢查市場經驗法則

`playbook` 表裡有待檢驗的法則，看今天是不是檢驗日：

```sql
SELECT * FROM playbook WHERE status='UNTESTED';
```

到期就回填結果（`status` 改為 SUPPORTED / REFUTED / MIXED，寫 `verdict`）。
不要因為結論不合自己胃口就放著不判。

### 6. 收盤後：結算、產頁、提交

```bash
python pt.py mark            # 寫入當日淨值快照
python pt.py record          # 產生不可覆寫每日紀錄與 CSV
python pt.py report          # 產生 index.html 與 data.json
python audit.py --no-network # 快速自我稽核；有交易的日子跑完整版
```

`audit.py` 任何一項 FAIL 都要先查清楚再提交，不要把壞掉的帳推上去。

```bash
cd C:\Aking\STOCK_CHATGPT\CX5
git add stock_GPT/
git commit -m "YYYY-MM-DD 盤後：<一句話摘要>"
git push origin main
```

---

## 注意事項

- **成交價抓不到就不交易**，不要想辦法繞過。那是設計，不是故障。
- **風控被擋下就不交易。** 正式競賽不提供覆蓋參數。
- 單一個股 ≤ 12%、單筆進場 ≤ 10%、常態現金 ≥ 20%。
- 帳戶跌破 250,000 就出局。**這條規則的意義是：破產風險不能用報酬率補償。**
  三個月約 60 個交易日，市場年化波動 36%，先確保活著，判斷才有機會累積。
- 誠實優先於好看。判斷錯了就寫錯了，補跑遲到了就寫遲到了。
  這本帳會被其他 AI 逐筆驗證，而且**修飾紀錄的代價遠大於承認判斷失誤**。
