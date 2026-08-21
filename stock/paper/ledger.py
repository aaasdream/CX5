"""帳本核心：買、賣、持倉、每日淨值快照。

會計採**加權平均成本制**（與台灣券商對帳單一致）：
  買進 -> avg_cost = (原總成本 + 本次實付) / 新總股數     # 買進手續費滾入成本
  賣出 -> 已實現損益 = 實收淨額 - avg_cost x 賣出股數     # 賣出費稅已從實收扣除

因此帳面上的 avg_cost 就是「真正的成本」，不需要另外記手續費。
"""
from __future__ import annotations

import datetime as dt
import sqlite3

from . import config, db, fees, market


class RiskViolation(Exception):
    """觸犯自訂風控上限。可用 force=True 明確覆蓋（覆蓋這件事會記進理由裡）。"""


# ── 讀取 ────────────────────────────────────────────────────────────
def cash(conn: sqlite3.Connection) -> float:
    return float(db.get_meta(conn, "cash", "0"))


def positions(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM positions WHERE shares > 0 ORDER BY code")]


def position(conn: sqlite3.Connection, code: str) -> dict | None:
    r = conn.execute("SELECT * FROM positions WHERE code = ?", (code,)).fetchone()
    return dict(r) if r else None


def realized_pnl_cum(conn: sqlite3.Connection) -> float:
    r = conn.execute("SELECT COALESCE(SUM(realized_pnl),0) v FROM trades").fetchone()
    return float(r["v"])


def fees_cum(conn: sqlite3.Connection) -> float:
    r = conn.execute("SELECT COALESCE(SUM(fee+tax),0) v FROM trades").fetchone()
    return float(r["v"])


def valuation(conn: sqlite3.Connection, date: str | None = None) -> dict:
    """依收盤價估算目前總資產。date 為 None 表示用各檔最新收盤價。"""
    c = cash(conn)
    rows = []
    mkt_value = 0.0
    cost_total = 0.0
    for p in positions(conn):
        q = market.last_close(conn, p["code"], on_or_before=date)
        price = q[1] if q else p["avg_cost"]       # 拿不到報價就以成本計，不虛增
        price_date = q[0] if q else None
        value = price * p["shares"]
        pnl = value - p["total_cost"]
        rows.append({**p, "price": price, "price_date": price_date,
                     "market_value": value, "unrealized_pnl": pnl,
                     "unrealized_pct": (pnl / p["total_cost"] * 100) if p["total_cost"] else 0.0})
        mkt_value += value
        cost_total += p["total_cost"]
    equity = c + mkt_value
    initial = float(db.get_meta(conn, "initial_cash", str(config.INITIAL_CASH)))
    return {
        "date": date,
        "cash": c,
        "positions": rows,
        "positions_value": mkt_value,
        "positions_cost": cost_total,
        "total_equity": equity,
        "unrealized_pnl": mkt_value - cost_total,
        "realized_pnl_cum": realized_pnl_cum(conn),
        "fees_cum": fees_cum(conn),
        "initial_cash": initial,
        "cum_return_pct": (equity / initial - 1) * 100 if initial else 0.0,
        "cash_pct": (c / equity * 100) if equity else 0.0,
    }


# ── 風控 ────────────────────────────────────────────────────────────
def check_buy_limits(conn: sqlite3.Connection, code: str, net_cost: float) -> list[str]:
    """回傳違規訊息清單（空清單 = 通過）。"""
    v = valuation(conn)
    equity = v["total_equity"]
    problems = []
    if net_cost > v["cash"]:
        problems.append(f"現金不足：需要 {net_cost:,.0f}，只有 {v['cash']:,.0f}")
    if equity:
        if net_cost / equity > config.MAX_NEW_BUY_PCT:
            problems.append(f"單筆金額佔總資產 {net_cost / equity * 100:.1f}%，"
                            f"超過單筆上限 {config.MAX_NEW_BUY_PCT * 100:.0f}%")
        held = next((p["market_value"] for p in v["positions"] if p["code"] == code), 0.0)
        after = (held + net_cost) / equity
        if after > config.MAX_POSITION_PCT:
            problems.append(f"買進後單一個股佔比 {after * 100:.1f}%，"
                            f"超過上限 {config.MAX_POSITION_PCT * 100:.0f}%")
        if (v["cash"] - net_cost) / equity < config.MIN_CASH_PCT:
            problems.append(f"買進後現金水位 {(v['cash'] - net_cost) / equity * 100:.1f}%，"
                            f"低於下限 {config.MIN_CASH_PCT * 100:.0f}%")
    return problems


# ── 寫入 ────────────────────────────────────────────────────────────
def buy(conn: sqlite3.Connection, code: str, shares: int, reason: str, *,
        thesis_id: int | None = None, force: bool = False,
        now: dt.datetime | None = None) -> dict:
    """買進並更新現金與持倉，回傳成交明細。

    **成交價不由呼叫端指定**，一律由 market.execution_quote 依當下時段
    取公開報價。沒有這條限制，帳本就沒有可稽核性可言。
    """
    q = market.execution_quote(conn, code, now)
    price, date = q["price"], q["date"]
    name = market.stock_name(code)
    c = fees.compute("BUY", price, shares)

    problems = check_buy_limits(conn, code, c.net)
    if problems and not force:
        raise RiskViolation("；".join(problems))
    if problems:
        reason = f"[已覆蓋風控: {'；'.join(problems)}] {reason}"

    new_cash = cash(conn) - c.net
    cur = conn.execute(
        "INSERT INTO trades(date,filled_at,code,name,side,shares,price,fill_mode,"
        "price_source,gross,fee,tax,net,cash_after,realized_pnl,reason,thesis_id) "
        "VALUES (?,?,?,?,'BUY',?,?,?,?,?,?,?,?,?,NULL,?,?)",
        (date, q["filled_at"], code, name, shares, price, q["mode"], q["source"],
         c.gross, c.fee, c.tax, c.net, new_cash, reason, thesis_id))
    trade_id = cur.lastrowid

    p = position(conn, code)
    if p:
        total_shares = p["shares"] + shares
        total_cost = p["total_cost"] + c.net
        conn.execute(
            "UPDATE positions SET shares=?, total_cost=?, avg_cost=?, last_action_date=?, "
            "thesis_id=COALESCE(?,thesis_id) WHERE code=?",
            (total_shares, total_cost, total_cost / total_shares, date, thesis_id, code))
    else:
        conn.execute(
            "INSERT INTO positions(code,name,shares,avg_cost,total_cost,"
            "first_buy_date,last_action_date,thesis_id) VALUES (?,?,?,?,?,?,?,?)",
            (code, name, shares, c.net / shares, c.net, date, date, thesis_id))

    db.set_meta(conn, "cash", new_cash)
    conn.commit()
    return {"trade_id": trade_id, "code": code, "name": name, "side": "BUY",
            "shares": shares, "price": price, "gross": c.gross, "fee": c.fee,
            "tax": c.tax, "net": c.net, "cash_after": new_cash,
            "date": date, "filled_at": q["filled_at"], "price_source": q["source"]}


def sell(conn: sqlite3.Connection, code: str, shares: int, reason: str, *,
         close_thesis: str | None = None, now: dt.datetime | None = None) -> dict:
    """賣出並結算已實現損益。成交價同樣只能來自 execution_quote。"""
    p = position(conn, code)
    if not p:
        raise ValueError(f"沒有持有 {code}")
    if shares > p["shares"]:
        raise ValueError(f"{code} 只持有 {p['shares']} 股，不能賣 {shares} 股")

    q = market.execution_quote(conn, code, now)
    price, date = q["price"], q["date"]
    c = fees.compute("SELL", price, shares)
    cost_out = p["avg_cost"] * shares
    realized = c.net - cost_out
    new_cash = cash(conn) + c.net

    cur = conn.execute(
        "INSERT INTO trades(date,filled_at,code,name,side,shares,price,fill_mode,"
        "price_source,gross,fee,tax,net,cash_after,realized_pnl,reason,thesis_id) "
        "VALUES (?,?,?,?,'SELL',?,?,?,?,?,?,?,?,?,?,?,?)",
        (date, q["filled_at"], code, p["name"], shares, price, q["mode"], q["source"],
         c.gross, c.fee, c.tax, c.net, new_cash, realized, reason, p["thesis_id"]))
    trade_id = cur.lastrowid

    left = p["shares"] - shares
    if left == 0:
        conn.execute("DELETE FROM positions WHERE code=?", (code,))
        if p["thesis_id"]:
            conn.execute(
                "UPDATE theses SET status='CLOSED', updated_date=?, "
                "outcome=COALESCE(?,outcome) WHERE id=?",
                (date, close_thesis, p["thesis_id"]))
    else:
        conn.execute(
            "UPDATE positions SET shares=?, total_cost=?, last_action_date=? WHERE code=?",
            (left, p["avg_cost"] * left, date, code))

    db.set_meta(conn, "cash", new_cash)
    conn.commit()
    return {"trade_id": trade_id, "code": code, "name": p["name"], "side": "SELL",
            "shares": shares, "price": price, "gross": c.gross, "fee": c.fee,
            "tax": c.tax, "net": c.net, "realized_pnl": realized, "cash_after": new_cash,
            "date": date, "filled_at": q["filled_at"], "price_source": q["source"]}


def state_as_of(conn: sqlite3.Connection, date: str) -> dict:
    """從 trades 重建「截至 date 當日收盤時」的現金與持倉。

    存在的理由是一個真實踩過的坑：早期版本的 snapshot() 直接用
    `positions` 表（也就是**今天**的持倉）去套歷史價格重算舊快照，
    結果 8/20（當時還空手）被算成持有 8/21 才買進的部位。

    歷史淨值曲線是這場實驗的核心證據，被今天的部位污染就毀了。
    重算任何一天，都必須先把那一天當時的帳戶狀態還原出來。
    """
    initial = float(db.get_meta(conn, "initial_cash", str(config.INITIAL_CASH)))
    cash_ = initial
    book: dict[str, dict] = {}
    realized = 0.0
    fees_paid = 0.0

    for t in conn.execute(
            "SELECT * FROM trades WHERE date <= ? ORDER BY date, id", (date,)):
        b = book.setdefault(t["code"], {"name": t["name"], "shares": 0, "cost": 0.0})
        fees_paid += t["fee"] + t["tax"]
        if t["side"] == "BUY":
            cash_ -= t["net"]
            b["shares"] += t["shares"]
            b["cost"] += t["net"]
        else:
            cash_ += t["net"]
            avg = b["cost"] / b["shares"] if b["shares"] else 0.0
            realized += t["net"] - avg * t["shares"]
            b["cost"] -= avg * t["shares"]
            b["shares"] -= t["shares"]

    holdings = []
    for code, b in book.items():
        if b["shares"] <= 0:
            continue
        holdings.append({"code": code, "name": b["name"], "shares": b["shares"],
                         "total_cost": b["cost"],
                         "avg_cost": b["cost"] / b["shares"]})
    return {"cash": cash_, "positions": holdings, "realized_pnl_cum": realized,
            "fees_cum": fees_paid, "initial_cash": initial}


def valuation_as_of(conn: sqlite3.Connection, date: str) -> dict:
    """把 state_as_of 的持倉用該日（或之前最近）收盤價估值。"""
    st = state_as_of(conn, date)
    rows, mkt_value, cost_total = [], 0.0, 0.0
    for p in st["positions"]:
        q = market.last_close(conn, p["code"], on_or_before=date)
        price = q[1] if q else p["avg_cost"]
        value = price * p["shares"]
        pnl = value - p["total_cost"]
        rows.append({**p, "price": price, "price_date": q[0] if q else None,
                     "market_value": value, "unrealized_pnl": pnl,
                     "unrealized_pct": (pnl / p["total_cost"] * 100) if p["total_cost"] else 0.0})
        mkt_value += value
        cost_total += p["total_cost"]
    equity = st["cash"] + mkt_value
    initial = st["initial_cash"]
    return {**st, "date": date, "positions": rows, "positions_value": mkt_value,
            "positions_cost": cost_total, "total_equity": equity,
            "unrealized_pnl": mkt_value - cost_total,
            "cum_return_pct": (equity / initial - 1) * 100 if initial else 0.0,
            "cash_pct": (st["cash"] / equity * 100) if equity else 0.0}


def snapshot(conn: sqlite3.Connection, date: str, note: str | None = None) -> dict:
    """寫入當日淨值快照（含與大盤的對照）。可重複執行，同一天會被覆蓋。

    用 point-in-time 狀態而非目前持倉，因此重算歷史任一天都會得到
    當時真正的淨值，不會被之後才建立的部位污染。
    """
    v = valuation_as_of(conn, date)
    initial = v["initial_cash"]

    twii = conn.execute(
        "SELECT close FROM macro WHERE series='^TWII' AND date<=? ORDER BY date DESC LIMIT 1",
        (date,)).fetchone()
    twii_close = float(twii["close"]) if twii else None

    start_date = db.get_meta(conn, "start_date", config.START_DATE)
    twii_base = conn.execute(
        "SELECT close FROM macro WHERE series='^TWII' AND date>=? ORDER BY date ASC LIMIT 1",
        (start_date,)).fetchone()
    twii_cum = ((twii_close / float(twii_base["close"]) - 1) * 100
                if twii_close and twii_base and twii_base["close"] else None)

    prev = conn.execute(
        "SELECT total_equity FROM snapshots WHERE date < ? ORDER BY date DESC LIMIT 1",
        (date,)).fetchone()
    day_ret = ((v["total_equity"] / float(prev["total_equity"]) - 1) * 100
               if prev and prev["total_equity"] else None)

    conn.execute(
        "INSERT INTO snapshots(date,cash,positions_value,total_equity,unrealized_pnl,"
        "realized_pnl_cum,fees_cum,day_return_pct,cum_return_pct,twii_close,twii_cum_pct,note) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(date) DO UPDATE SET cash=excluded.cash, "
        "positions_value=excluded.positions_value, total_equity=excluded.total_equity, "
        "unrealized_pnl=excluded.unrealized_pnl, realized_pnl_cum=excluded.realized_pnl_cum, "
        "fees_cum=excluded.fees_cum, day_return_pct=excluded.day_return_pct, "
        "cum_return_pct=excluded.cum_return_pct, twii_close=excluded.twii_close, "
        "twii_cum_pct=excluded.twii_cum_pct, note=COALESCE(excluded.note, snapshots.note)",
        (date, v["cash"], v["positions_value"], v["total_equity"], v["unrealized_pnl"],
         v["realized_pnl_cum"], v["fees_cum"], day_ret,
         (v["total_equity"] / initial - 1) * 100 if initial else 0.0,
         twii_close, twii_cum, note))
    conn.commit()
    return {**v, "twii_close": twii_close, "twii_cum_pct": twii_cum,
            "day_return_pct": day_ret}
