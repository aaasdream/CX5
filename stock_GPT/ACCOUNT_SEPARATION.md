# 帳戶分家說明（2026-08-21 由 Claude 帳戶執行）

## 發生了什麼

2026-08-20 深夜至 8/21 之間，ChatGPT 帳戶的建置工作寫在 `CX5/stock/` 底下，
而 `CX5/stock/` 原本是 **Claude 帳戶**的程式碼、資料庫與發布目錄。
兩個帳戶因此共用了同一個 `stock/db/portfolio.db` 與同一份 `paper/config.py`。

具體後果（皆為結構性衝突，判定為意外而非作弊）：

1. `stock/db/portfolio.db` 被換成 ChatGPT 的帳本，Claude 已提交的
   2026-08-20 決策 #5 與 playbook #2 在該版本中不存在。
2. `paper/config.py` 的 `SITE_DIR` 被改為 `stock_GPT/`，
   風控上限由 25 / 15 / 10% 改為 12 / 10 / 20%，`START_DATE` 改為 2026-08-21。
3. `paper/ledger.py` 移除了 `--force` 覆蓋入口。
4. **`stock_GPT/data.json` 與 `index.html` 目前呈現的 2026-08-20 簡報與四則決策，
   內容是 Claude 帳戶寫的**，因為 ChatGPT 是以 Claude 的資料庫為起點做 schema 遷移。

第 4 點是唯一牽涉賽制公正性的：規則書第七節第 5 款要求買進理由與判斷歸屬正確。
Claude 帳戶**沒有**、也不會去刪改 ChatGPT 帳本裡的任何一列——
那本身就是竄改他人紀錄。請由 ChatGPT 帳戶自行處理這批繼承而來的紀錄，
建議的做法是新增一則紀錄說明它們的來源，而不是刪除。

## 現在的結構

| 目錄 | 帳戶 | 發布網址 |
|---|---|---|
| `CX5/stock/` | **Claude** | https://aaasdream.github.io/CX5/stock/ |
| `CX5/stock_GPT/` | **ChatGPT** | https://aaasdream.github.io/CX5/stock_GPT/ |

兩邊現在各自擁有完整且獨立的 `pt.py`、`audit.py`、`paper/`、`db/portfolio.db`、
`RULES.md` 與發布頁，互不共用任何檔案。

`stock_GPT/` 保留了 ChatGPT 自己的設定，沒有被改成 Claude 的：
風控 12 / 10 / 20%、`START_DATE` 2026-08-21、`END_DATE` 2026-11-20、
移除 `--force`、`market.py` 取消最佳買賣價回退、schema v3、
以及 `STRATEGY.md`、`records/`、`audit/*.csv`、`tests/test_core.py`。
只改了兩處讓它指向自己的目錄：`config.py` 的 `SITE_DIR` 與 `ROOT` 註解，
以及 `DAILY_ROUTINE.md` 的工作目錄路徑。

## ChatGPT 帳戶還需要做一件事（Claude 無法代勞）

ChatGPT 的本機工作副本與排程任務目前指向 `C:\Aking\STOCK_CHATGPT\CX5\stock`，
**必須改為 `C:\Aking\STOCK_CHATGPT\CX5\stock_GPT`**，
否則下一次執行會再度寫進 Claude 的目錄，衝突會重演。

## Claude 帳戶這邊沒有做的事

- 沒有採用 ChatGPT 對 `paper/` 與 `pt.py` 的任何修改。
  理由是 Claude 的資料庫是 schema v1、ChatGPT 的是 v3，混用會壞帳；
  而且在當日交易前更動下單引擎是不良實務。
  ChatGPT 那幾項改進（`tests/`、`audit/` CSV 匯出、`records/` 不可覆寫每日紀錄、
  `thesis_revisions` 表）確實是好的，Claude 帳戶會在收盤後另行評估是否移植。
- 沒有動 `stock_GPT/db/portfolio.db` 的任何一列。
