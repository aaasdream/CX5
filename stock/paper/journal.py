"""日誌層：新聞、每日簡報、決策、事件行事曆、投資論點。

這一層是整個實驗的重點。帳本只記「做了什麼」，
日誌記的是「當下為什麼這樣想」—— 沒有後者，事後就無從檢驗判斷品質，
只會剩下「我早就說了」這種無法否證的說法。
"""
from __future__ import annotations

import sqlite3

from . import market


# ── 投資論點 ────────────────────────────────────────────────────────
def add_thesis(conn: sqlite3.Connection, code: str, date: str, title: str,
               rationale: str, *, catalysts: str | None = None,
               risks: str | None = None, target_price: float | None = None,
               stop_loss: float | None = None, horizon: str | None = None,
               conviction: int | None = None, name: str | None = None) -> int:
    """建立一個投資論點，回傳 id。買進時掛上去。"""
    name = name or market.stock_name(code)
    cur = conn.execute(
        "INSERT INTO theses(code,name,created_date,updated_date,title,rationale,"
        "catalysts,risks,target_price,stop_loss,horizon,conviction,status) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'OPEN')",
        (code, name, date, date, title, rationale, catalysts, risks,
         target_price, stop_loss, horizon, conviction))
    conn.commit()
    return cur.lastrowid


def update_thesis(conn: sqlite3.Connection, thesis_id: int, date: str, **fields) -> None:
    """更新論點，並追加每個欄位的修改前後值。"""
    allowed = {"title", "rationale", "catalysts", "risks", "target_price",
               "stop_loss", "horizon", "conviction", "status", "outcome"}
    current = conn.execute("SELECT * FROM theses WHERE id=?", (thesis_id,)).fetchone()
    if not current:
        raise ValueError(f"找不到論點 #{thesis_id}")
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed and v is not None:
            conn.execute(
                "INSERT INTO thesis_revisions(thesis_id,date,field,old_value,new_value) "
                "VALUES (?,?,?,?,?)", (thesis_id, date, k, current[k], v))
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return
    sets.append("updated_date=?")
    vals.extend([date, thesis_id])
    conn.execute(f"UPDATE theses SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()


def theses(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM theses"
    args: tuple = ()
    if status:
        sql += " WHERE status=?"
        args = (status,)
    sql += " ORDER BY created_date DESC, id DESC"
    return [dict(r) for r in conn.execute(sql, args)]


# ── 新聞 ────────────────────────────────────────────────────────────
def add_news(conn: sqlite3.Connection, date: str, title: str, *, source: str | None = None,
             url: str | None = None, summary: str | None = None,
             category: str | None = None, sentiment: str | None = None,
             importance: int | None = None, codes: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO news(date,title,source,url,summary,category,sentiment,importance,codes) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (date, title, source, url, summary, category, sentiment, importance, codes))
    conn.commit()
    return cur.lastrowid


def news(conn: sqlite3.Connection, date: str | None = None, limit: int = 50) -> list[dict]:
    if date:
        rows = conn.execute(
            "SELECT * FROM news WHERE date=? ORDER BY importance DESC, id DESC", (date,))
    else:
        rows = conn.execute(
            "SELECT * FROM news ORDER BY date DESC, importance DESC, id DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


# ── 每日簡報 ────────────────────────────────────────────────────────
def set_brief(conn: sqlite3.Connection, date: str, **fields) -> None:
    """寫入當日簡報；同日期內容不得覆寫。"""
    cols = ["macro", "tw_market", "ai_sector", "crypto", "key_events",
            "stance", "actions", "outlook"]
    vals = [fields.get(c) for c in cols]
    try:
        conn.execute(
            f"INSERT INTO briefs(date,{','.join(cols)}) VALUES (?,?,?,?,?,?,?,?,?)",
            (date, *vals))
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"{date} 簡報已存在；禁止覆寫，修正請新增 correction 紀錄") from exc
    conn.commit()


def brief(conn: sqlite3.Connection, date: str | None = None) -> dict | None:
    if date:
        r = conn.execute("SELECT * FROM briefs WHERE date=?", (date,)).fetchone()
    else:
        r = conn.execute("SELECT * FROM briefs ORDER BY date DESC LIMIT 1").fetchone()
    return dict(r) if r else None


# ── 決策 ────────────────────────────────────────────────────────────
def add_decision(conn: sqlite3.Connection, date: str, action: str, rationale: str,
                 *, code: str | None = None, executed: bool = False,
                 trade_id: int | None = None, name: str | None = None) -> int:
    if code and not name:
        name = market.stock_name(code)
    cur = conn.execute(
        "INSERT INTO decisions(date,code,name,action,rationale,executed,trade_id) "
        "VALUES (?,?,?,?,?,?,?)",
        (date, code, name, action.upper(), rationale, int(executed), trade_id))
    conn.commit()
    return cur.lastrowid


def decisions(conn: sqlite3.Connection, date: str | None = None, limit: int = 100) -> list[dict]:
    if date:
        rows = conn.execute("SELECT * FROM decisions WHERE date=? ORDER BY id", (date,))
    else:
        rows = conn.execute("SELECT * FROM decisions ORDER BY date DESC, id DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


# ── 事件行事曆 ──────────────────────────────────────────────────────
def add_event(conn: sqlite3.Connection, date: str, title: str, *,
              category: str | None = None, importance: int | None = None,
              note: str | None = None) -> None:
    conn.execute(
        "INSERT INTO events(date,title,category,importance,note) VALUES (?,?,?,?,?) "
        "ON CONFLICT(date,title) DO UPDATE SET category=excluded.category, "
        "importance=excluded.importance, note=COALESCE(excluded.note, events.note)",
        (date, title, category, importance, note))
    conn.commit()


def upcoming_events(conn: sqlite3.Connection, from_date: str, days: int = 30) -> list[dict]:
    import datetime as dt
    end = (dt.date.fromisoformat(from_date) + dt.timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT * FROM events WHERE date>=? AND date<=? ORDER BY date, importance DESC",
        (from_date, end))
    return [dict(r) for r in rows]
