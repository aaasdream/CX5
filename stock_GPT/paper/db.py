"""SQLite 結構定義與連線。

一個檔案裝完整個實驗：帳本、論點、決策、新聞、總經、行情快取。
好處是 repo 裡就帶著完整歷史，任何人 clone 下來都能重算。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from . import config

SCHEMA_VERSION = 3

SCHEMA = """
-- 帳戶層級的 key/value（初始資金、起始日、schema 版本…）
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 每一筆成交。這張表是唯一的真相來源，positions/snapshots 都能由它重建。
--
-- fill_mode 只允許 LIVE：盤中（9:00–13:30）以當下即時成交價成交。
CREATE TABLE IF NOT EXISTS trades (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date         TEXT    NOT NULL,              -- 成交日 YYYY-MM-DD
    filled_at    TEXT,                          -- 成交當下的時間戳（本機時間）
    code         TEXT    NOT NULL,
    name         TEXT    NOT NULL,
    side         TEXT    NOT NULL CHECK (side IN ('BUY','SELL')),
    shares       INTEGER NOT NULL CHECK (shares > 0),
    price        REAL    NOT NULL CHECK (price > 0),
    fill_mode    TEXT    NOT NULL DEFAULT 'LIVE'
                 CHECK (fill_mode = 'LIVE'),
    price_source TEXT    NOT NULL,              -- 價格來自哪裡，驗證時比對用
    gross        REAL    NOT NULL,              -- 成交價金
    fee          REAL    NOT NULL,              -- 手續費
    tax          REAL    NOT NULL,              -- 證交稅（買進為 0）
    net          REAL    NOT NULL,              -- 買:實付 / 賣:實收
    cash_after   REAL    NOT NULL,              -- 成交後現金餘額
    realized_pnl REAL,                          -- 只有賣出才有：本筆已實現損益（已扣成本與稅費）
    reason       TEXT    NOT NULL,              -- 為什麼做這筆
    thesis_id    INTEGER REFERENCES theses(id),
    created_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date);
CREATE INDEX IF NOT EXISTS idx_trades_code ON trades(code);

-- 現時持倉（加權平均成本制，與台灣券商對帳單一致）
CREATE TABLE IF NOT EXISTS positions (
    code            TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    shares          INTEGER NOT NULL,
    avg_cost        REAL NOT NULL,        -- 每股平均成本（已含買進手續費）
    total_cost      REAL NOT NULL,        -- = avg_cost × shares
    first_buy_date  TEXT NOT NULL,
    last_action_date TEXT NOT NULL,
    thesis_id       INTEGER REFERENCES theses(id)
);

-- 投資論點：為什麼買、看多久、看到哪、什麼情況認錯
CREATE TABLE IF NOT EXISTS theses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    code         TEXT NOT NULL,
    name         TEXT NOT NULL,
    created_date TEXT NOT NULL,
    updated_date TEXT NOT NULL,
    title        TEXT NOT NULL,          -- 一句話講完的買進理由
    rationale    TEXT NOT NULL,          -- 完整論證
    catalysts    TEXT,                   -- 預期的催化劑（換行分隔）
    risks        TEXT,                   -- 什麼會讓這個論點失效
    target_price REAL,
    stop_loss    REAL,
    horizon      TEXT,                   -- 例: "至Q4法說" / "2-4週"
    conviction   INTEGER CHECK (conviction BETWEEN 1 AND 5),
    status       TEXT NOT NULL DEFAULT 'OPEN'
                 CHECK (status IN ('OPEN','CLOSED','INVALIDATED')),
    outcome      TEXT                    -- 結案時回填：對了還是錯了、錯在哪
);
CREATE INDEX IF NOT EXISTS idx_theses_code ON theses(code);

-- 論點調整採追加紀錄，保留修改前後值，避免事後改寫理由。
CREATE TABLE IF NOT EXISTS thesis_revisions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    thesis_id  INTEGER NOT NULL REFERENCES theses(id),
    date       TEXT NOT NULL,
    field      TEXT NOT NULL,
    old_value  TEXT,
    new_value  TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_thesis_revisions_thesis ON thesis_revisions(thesis_id, id);

-- 每日決策紀錄。**包含「決定不動」**——沒交易的日子也要留下理由，
-- 否則事後無法分辨「判斷正確」與「根本沒判斷」。
CREATE TABLE IF NOT EXISTS decisions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    date      TEXT NOT NULL,
    code      TEXT,                      -- NULL = 針對整體部位/大盤的決策
    name      TEXT,
    action    TEXT NOT NULL CHECK (action IN ('BUY','SELL','ADD','TRIM','HOLD','WATCH','PASS')),
    rationale TEXT NOT NULL,
    executed  INTEGER NOT NULL DEFAULT 0,
    trade_id  INTEGER REFERENCES trades(id)
);
CREATE INDEX IF NOT EXISTS idx_decisions_date ON decisions(date);

-- 每日收盤後的淨值快照（績效曲線的資料來源）
CREATE TABLE IF NOT EXISTS snapshots (
    date             TEXT PRIMARY KEY,
    cash             REAL NOT NULL,
    positions_value  REAL NOT NULL,      -- 依當日收盤價計算的市值
    total_equity     REAL NOT NULL,
    unrealized_pnl   REAL NOT NULL,
    realized_pnl_cum REAL NOT NULL,      -- 累計已實現損益
    fees_cum         REAL NOT NULL,      -- 累計交易成本（手續費+稅）
    day_return_pct   REAL,
    cum_return_pct   REAL NOT NULL,
    twii_close       REAL,               -- 加權指數，做為基準
    twii_cum_pct     REAL,               -- 同期大盤報酬（買進持有）
    note             TEXT
);

-- 新聞條目
CREATE TABLE IF NOT EXISTS news (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT NOT NULL,
    title      TEXT NOT NULL,
    source     TEXT,
    url        TEXT,
    summary    TEXT,
    category   TEXT,                     -- macro/tw_market/ai/crypto/geopolitics/company
    sentiment  TEXT CHECK (sentiment IN ('BULLISH','BEARISH','NEUTRAL','MIXED')),
    importance INTEGER CHECK (importance BETWEEN 1 AND 5),
    codes      TEXT,                     -- 相關個股代號，逗號分隔
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_news_date ON news(date);

-- 每日盤前簡報：把當天所有輸入濃縮成一段可回頭檢驗的判斷
CREATE TABLE IF NOT EXISTS briefs (
    date          TEXT PRIMARY KEY,
    macro         TEXT,                  -- 總經與國際市場
    tw_market     TEXT,                  -- 台股盤勢與籌碼
    ai_sector     TEXT,                  -- AI/半導體供應鏈
    crypto        TEXT,                  -- 比特幣與風險偏好
    key_events    TEXT,                  -- 今日/近期關鍵事件
    stance        TEXT,                  -- 整體立場：偏多/偏空/中性/防禦
    actions       TEXT,                  -- 今天打算做什麼
    outlook       TEXT,                  -- 對接下來幾天的預期（事後可驗證）
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 事件行事曆（財報、利率決議、經濟數據…）
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT NOT NULL,
    title      TEXT NOT NULL,
    category   TEXT,
    importance INTEGER CHECK (importance BETWEEN 1 AND 5),
    note       TEXT,
    UNIQUE(date, title)
);
CREATE INDEX IF NOT EXISTS idx_events_date ON events(date);

-- 市場經驗法則。來自委託人的實務經驗、外部分析師、或本帳戶自己的觀察。
--
-- 每一條都必須寫成**可證偽**的形式（什麼情況下、預期出現什麼、怎麼算不成立），
-- 並在事件發生後回填 verdict。三個月下來，這張表本身就是實驗產物之一：
-- 哪些老經驗在 2026 年還有效、哪些已經失效。
CREATE TABLE IF NOT EXISTS playbook (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    added_date   TEXT NOT NULL,
    title        TEXT NOT NULL,
    source       TEXT NOT NULL,        -- 誰說的：委託人／分析師／本帳戶觀察
    mechanism    TEXT NOT NULL,        -- 為什麼會這樣（機制，不是現象）
    testable     TEXT NOT NULL,        -- 可證偽的敘述：何時、預期什麼、怎樣算錯
    test_dates   TEXT,                 -- 預計檢驗的日期
    status       TEXT NOT NULL DEFAULT 'UNTESTED'
                 CHECK (status IN ('UNTESTED','SUPPORTED','REFUTED','MIXED')),
    verdict      TEXT,                 -- 事後回填：實際發生什麼
    verdict_date TEXT
);

-- 總經 / 跨市場指標的每日值
CREATE TABLE IF NOT EXISTS macro (
    date   TEXT NOT NULL,
    series TEXT NOT NULL,               -- yfinance ticker
    label  TEXT NOT NULL,
    close  REAL NOT NULL,
    chg_pct REAL,
    PRIMARY KEY (date, series)
);

-- 台股日線快取（觀察清單 + 持股）
CREATE TABLE IF NOT EXISTS quotes (
    code   TEXT NOT NULL,
    date   TEXT NOT NULL,
    open   REAL, high REAL, low REAL, close REAL,
    volume INTEGER,
    PRIMARY KEY (code, date)
);
CREATE INDEX IF NOT EXISTS idx_quotes_date ON quotes(date);
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """開啟資料庫連線（外鍵約束打開、回傳 Row 方便取欄位）。"""
    path = Path(path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init(path: Path | str | None = None, *, initial_cash: float | None = None) -> sqlite3.Connection:
    """建立結構並寫入初始 meta（可重複執行，不會覆蓋既有資料）。"""
    conn = connect(path)
    # v1 曾允許 CLOSE_LATE。正式比賽前若帳本尚無成交，重建空表；
    # 已有成交則停止，避免靜默改動歷史。
    old = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='trades'").fetchone()
    if old and "CLOSE_LATE" in (old["sql"] or ""):
        count = conn.execute("SELECT COUNT(*) n FROM trades").fetchone()["n"]
        if count:
            raise RuntimeError("舊帳本含成交且允許 CLOSE_LATE；需人工稽核後才能遷移")
        conn.commit()
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DROP TABLE trades")
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    cash = config.INITIAL_CASH if initial_cash is None else initial_cash
    defaults = {
        "schema_version": str(SCHEMA_VERSION),
        "initial_cash": str(cash),
        "cash": str(cash),
        "start_date": config.START_DATE,
        "currency": config.BASE_CURRENCY,
    }
    for k, v in defaults.items():
        conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)", (k, v))
    conn.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
    conn.execute("UPDATE meta SET value=? WHERE key='start_date'", (config.START_DATE,))
    conn.commit()
    return conn


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
