"""行情抓取：台股日線（FinMind）與跨市場指標（yfinance）。

抓下來的東西一律落進 SQLite，網頁只讀資料庫。
這樣即使某天資料源掛掉，歷史紀錄仍然完整、頁面照樣出得來。
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import time

import requests

from . import config

_name_cache: dict[str, str] = {}


# ── 台股 ────────────────────────────────────────────────────────────
def stock_name(code: str) -> str:
    """查台股代號的中文名稱。先用設定檔的清單，再退到 twstock。"""
    if code in config.WATCHLIST:
        return config.WATCHLIST[code]
    if code in _name_cache:
        return _name_cache[code]
    try:
        import twstock
        info = twstock.codes.get(code)
        if info:
            _name_cache[code] = info.name
            return info.name
    except Exception:
        pass
    return code


def _finmind_get(dataset: str, data_id: str, start: str, end: str | None = None) -> list[dict]:
    """打 FinMind，多把 token 輪替；撞到速率上限就換下一把。"""
    tokens = config.finmind_tokens()
    if not tokens:
        raise RuntimeError("找不到 FINMIND_TOKEN / FINMIND_TOKENS 環境變數")
    params = {"dataset": dataset, "data_id": data_id, "start_date": start}
    if end:
        params["end_date"] = end
    last_err = None
    for tok in tokens:
        try:
            r = requests.get(config.FINMIND_URL, params={**params, "token": tok}, timeout=60)
            j = r.json()
            if j.get("msg") == "success":
                return j.get("data", [])
            last_err = f"{r.status_code} {j.get('msg')}"
        except Exception as e:      # 網路層失敗也換下一把試試
            last_err = str(e)
        time.sleep(0.3)
    raise RuntimeError(f"FinMind {dataset}/{data_id} 失敗: {last_err}")


def fetch_tw_daily(conn: sqlite3.Connection, codes: list[str],
                   start: str, end: str | None = None) -> int:
    """抓台股日線寫進 quotes 表，回傳寫入列數。"""
    written = 0
    for code in codes:
        try:
            rows = _finmind_get("TaiwanStockPrice", code, start, end)
        except Exception as e:
            print(f"  ! {code} 抓取失敗: {e}")
            continue
        name = stock_name(code)
        for d in rows:
            conn.execute(
                "INSERT INTO quotes(code,date,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(code,date) DO UPDATE SET "
                "open=excluded.open, high=excluded.high, low=excluded.low, "
                "close=excluded.close, volume=excluded.volume",
                (code, d["date"], d.get("open"), d.get("max"), d.get("min"),
                 d.get("close"), d.get("Trading_Volume")),
            )
            written += 1
        print(f"  {code} {name}: {len(rows)} 筆, 最後 {rows[-1]['date'] if rows else '無'}")
        time.sleep(0.2)
    conn.commit()
    return written


def last_close(conn: sqlite3.Connection, code: str, on_or_before: str | None = None) -> tuple[str, float] | None:
    """從快取取最近一筆收盤價，回傳 (日期, 收盤)。"""
    if on_or_before:
        row = conn.execute(
            "SELECT date, close FROM quotes WHERE code=? AND date<=? AND close IS NOT NULL "
            "ORDER BY date DESC LIMIT 1", (code, on_or_before)).fetchone()
    else:
        row = conn.execute(
            "SELECT date, close FROM quotes WHERE code=? AND close IS NOT NULL "
            "ORDER BY date DESC LIMIT 1", (code,)).fetchone()
    return (row["date"], row["close"]) if row else None


def realtime(code: str) -> dict | None:
    """台股即時報價（twstock 打證交所 MIS）。回傳 None 表示抓不到。"""
    try:
        import twstock
        r = twstock.realtime.get(code)
        if not r.get("success"):
            return None
        rt, info = r["realtime"], r.get("info", {})
        price = rt.get("latest_trade_price")
        if price in (None, "-", ""):          # 尚未成交（例如剛開盤）就退回最佳買賣價
            bid = (rt.get("best_bid_price") or [None])[0]
            ask = (rt.get("best_ask_price") or [None])[0]
            price = bid or ask
        if price in (None, "-", ""):
            return None
        return {
            "price": float(price),
            "name": info.get("name") or code,
            "time": info.get("time"),
            "open": _f(rt.get("open")), "high": _f(rt.get("high")),
            "low": _f(rt.get("low")), "volume": _f(rt.get("accumulate_trade_volume")),
        }
    except Exception:
        return None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


TRADING_OPEN = dt.time(9, 0)
TRADING_CLOSE = dt.time(13, 30)


def market_session(now: dt.datetime | None = None) -> str:
    """現在是不是台股盤中。回傳 'OPEN' / 'CLOSED'。

    只看星期與時間，不查國定假日 —— 假日時 twstock 本來就抓不到即時價，
    抓不到就不會成交，效果一樣，不必另外維護假日表。
    """
    now = now or dt.datetime.now()
    if now.weekday() >= 5:                       # 週六日
        return "CLOSED"
    return "OPEN" if TRADING_OPEN <= now.time() <= TRADING_CLOSE else "CLOSED"


class MarketClosed(Exception):
    """休市中。與真實市場一致：收盤後就是不能交易，不補單、不追認。"""


class NoQuote(Exception):
    """盤中但抓不到即時報價。依實驗規則：抓不到價就不交易。"""


def execution_quote(conn: sqlite3.Connection, code: str,
                    now: dt.datetime | None = None) -> dict:
    """取得這筆單的成交價。**只有盤中（9:00–13:30）才成立。**

    這個函式是成交價的唯一入口，呼叫端沒有指定價格的餘地：
    價格一律是證交所當下的即時成交價。兩個後果都是刻意的 ——
    一、成交價可被第三方比對公開資料驗證；
    二、下決策的當下不知道之後的走勢，帳本沒有前視。

    收盤後呼叫會直接拋 MarketClosed，不會用收盤價補成交。
    當天沒跑到就是沒交易，跟真的錯過盤一樣。
    """
    now = now or dt.datetime.now()
    if market_session(now) != "OPEN":
        raise MarketClosed(
            f"{now:%Y-%m-%d %H:%M} 非交易時段（台股 9:00–13:30，例假日休市），不得交易")

    rt = realtime(code)
    if not rt:
        raise NoQuote(f"{code} 即時報價抓不到（可能為休市日或個股暫停交易），依規則不交易")
    return {
        "price": rt["price"],
        "date": now.date().isoformat(),
        "mode": "LIVE",
        "source": f"證交所即時成交價 {rt.get('time') or now.strftime('%Y-%m-%d %H:%M:%S')}"
                  f" @ {rt['price']:.2f}",
        "filled_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "quote": rt,
    }


# ── 跨市場指標 ──────────────────────────────────────────────────────
def fetch_macro(conn: sqlite3.Connection, lookback_days: int = 10) -> int:
    """抓 config.MACRO_SERIES 的近期收盤與日變動，寫進 macro 表。"""
    import yfinance as yf
    written = 0
    for ticker, label in config.MACRO_SERIES.items():
        try:
            h = yf.Ticker(ticker).history(period=f"{lookback_days}d")
            if not len(h):
                print(f"  ! {ticker} 無資料")
                continue
            closes = h["Close"].dropna()
            for i, (idx, close) in enumerate(closes.items()):
                date = idx.date().isoformat()
                chg = None
                if i > 0:
                    prev = float(closes.iloc[i - 1])
                    if prev:
                        chg = (float(close) / prev - 1) * 100
                conn.execute(
                    "INSERT INTO macro(date,series,label,close,chg_pct) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(date,series) DO UPDATE SET "
                    "close=excluded.close, chg_pct=excluded.chg_pct, label=excluded.label",
                    (date, ticker, label, float(close), chg))
                written += 1
            last_date = closes.index[-1].date().isoformat()
            print(f"  {ticker:10s} {label:12s} {float(closes.iloc[-1]):>12,.2f}  ({last_date})")
        except Exception as e:
            print(f"  ! {ticker} 失敗: {e}")
    conn.commit()
    return written


def macro_snapshot(conn: sqlite3.Connection, date: str | None = None) -> list[dict]:
    """取某日（預設最新）的所有總經指標。"""
    if date is None:
        row = conn.execute("SELECT MAX(date) d FROM macro").fetchone()
        date = row["d"] if row and row["d"] else None
    if not date:
        return []
    rows = conn.execute(
        "SELECT series,label,close,chg_pct,date FROM macro WHERE date<=? "
        "AND date=(SELECT MAX(date) FROM macro m2 WHERE m2.series=macro.series AND m2.date<=?) "
        "ORDER BY series", (date, date)).fetchall()
    return [dict(r) for r in rows]


def today() -> str:
    return dt.date.today().isoformat()
