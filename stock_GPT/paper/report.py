"""把資料庫匯出成 data.json，並產生自包含的 index.html。

網頁本身不打任何外部服務：資料在建置時就內嵌進 HTML，
所以 GitHub Pages 上是純靜態檔案，離線打開也一樣能看。
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

from . import config, db, journal, ledger, market

TEMPLATE = Path(__file__).parent / "template.html"


def export_data(conn: sqlite3.Connection, as_of: str | None = None) -> dict:
    """把整個實驗狀態組成一份 JSON-ready 的 dict。"""
    as_of = as_of or market.today()
    val = ledger.valuation(conn)

    snaps = [dict(r) for r in conn.execute(
        "SELECT * FROM snapshots ORDER BY date")]
    trades = [dict(r) for r in conn.execute(
        "SELECT * FROM trades ORDER BY date DESC, id DESC")]

    # 持倉附上論點摘要與距離目標/停損的位置
    th_by_id = {t["id"]: t for t in journal.theses(conn)}
    holdings = []
    for p in val["positions"]:
        t = th_by_id.get(p.get("thesis_id"))
        holdings.append({
            **p,
            "weight_pct": (p["market_value"] / val["total_equity"] * 100)
            if val["total_equity"] else 0.0,
            "thesis": {
                "id": t["id"], "title": t["title"], "rationale": t["rationale"],
                "catalysts": t["catalysts"], "risks": t["risks"],
                "target_price": t["target_price"], "stop_loss": t["stop_loss"],
                "horizon": t["horizon"], "conviction": t["conviction"],
                "created_date": t["created_date"],
            } if t else None,
        })

    # 持股與觀察清單的近期走勢（給網頁畫迷你走勢圖）
    codes = sorted({h["code"] for h in holdings} | set(config.WATCHLIST))
    series = {}
    for code in codes:
        rows = conn.execute(
            "SELECT date, close FROM quotes WHERE code=? ORDER BY date DESC LIMIT 60",
            (code,)).fetchall()
        if rows:
            series[code] = [{"date": r["date"], "close": r["close"]}
                            for r in reversed(rows)]

    watchlist = []
    for code, name in config.WATCHLIST.items():
        s = series.get(code)
        if not s:
            continue
        last = s[-1]["close"]
        prev = s[-2]["close"] if len(s) > 1 else last
        base20 = s[-21]["close"] if len(s) > 20 else s[0]["close"]
        watchlist.append({
            "code": code, "name": name, "close": last, "date": s[-1]["date"],
            "chg_pct": (last / prev - 1) * 100 if prev else 0.0,
            "chg20_pct": (last / base20 - 1) * 100 if base20 else 0.0,
            "held": any(h["code"] == code for h in holdings),
        })

    wins = [t for t in trades if t["side"] == "SELL" and (t["realized_pnl"] or 0) > 0]
    closed = [t for t in trades if t["side"] == "SELL"]
    equity_path = [float(s["total_equity"]) for s in snaps]
    peak = max(equity_path, default=val["initial_cash"])
    running_peak = val["initial_cash"]
    drawdowns = []
    for equity in equity_path:
        running_peak = max(running_peak, equity)
        drawdowns.append((equity / running_peak - 1) * 100 if running_peak else 0.0)
    current_drawdown = ((val["total_equity"] / peak - 1) * 100 if peak else 0.0)
    record_dates = {r["date"] for r in snaps}
    for table in ("briefs", "decisions", "news", "trades"):
        record_dates.update(r["date"] for r in conn.execute(f"SELECT DISTINCT date FROM {table}"))

    return {
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "as_of": as_of,
        "account": {
            "initial_cash": val["initial_cash"],
            "cash": val["cash"],
            "positions_value": val["positions_value"],
            "total_equity": val["total_equity"],
            "unrealized_pnl": val["unrealized_pnl"],
            "realized_pnl_cum": val["realized_pnl_cum"],
            "fees_cum": val["fees_cum"],
            "cum_return_pct": val["cum_return_pct"],
            "cash_pct": val["cash_pct"],
            "start_date": db.get_meta(conn, "start_date", config.START_DATE),
            "end_date": config.END_DATE,
            "knockout_equity": 250_000,
            "peak_equity": peak,
            "current_drawdown_pct": current_drawdown,
            "max_drawdown_pct": min(drawdowns, default=0.0),
            "record_days": len(record_dates),
            "trade_count": len(trades),
            "closed_count": len(closed),
            "win_count": len(wins),
            "win_rate_pct": (len(wins) / len(closed) * 100) if closed else None,
            "twii_cum_pct": snaps[-1]["twii_cum_pct"] if snaps else None,
        },
        "holdings": holdings,
        "snapshots": snaps,
        "trades": trades,
        "decisions": journal.decisions(conn, limit=5000),
        # 簡報、決策、新聞全部帶出來 —— 這個頁面要能回看整整三個月的判斷軌跡，
        # 而不是只顯示最新狀態。歷史本身就是實驗的產物。
        "briefs": [dict(r) for r in conn.execute("SELECT * FROM briefs ORDER BY date DESC")],
        "news": journal.news(conn, limit=1000),
        "events": journal.upcoming_events(conn, as_of, days=60),
        "macro": market.macro_snapshot(conn),
        "theses": journal.theses(conn),
        "playbook": [dict(r) for r in conn.execute(
            "SELECT * FROM playbook ORDER BY status='UNTESTED' DESC, id")],
        "watchlist": watchlist,
        "series": series,
        "limits": {
            "max_position_pct": config.MAX_POSITION_PCT * 100,
            "max_new_buy_pct": config.MAX_NEW_BUY_PCT * 100,
            "min_cash_pct": config.MIN_CASH_PCT * 100,
            "fee_rate": config.FEE_RATE,
            "fee_discount": config.FEE_DISCOUNT,
            "fee_min": config.FEE_MIN,
            "tax_rate_sell": config.TAX_RATE_SELL,
        },
    }


def render(conn: sqlite3.Connection, as_of: str | None = None,
           out_dir: Path | None = None) -> tuple[Path, Path]:
    """產生 index.html 與 data.json，回傳兩者路徑。"""
    out_dir = Path(out_dir or config.SITE_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = export_data(conn, as_of)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    json_path = out_dir / "data.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    html = TEMPLATE.read_text(encoding="utf-8")
    # 用 </script> 安全的注入方式，避免資料裡的字串提前關閉標籤
    html = html.replace("/*__DATA__*/null", payload.replace("</", "<\\/"))
    html_path = out_dir / "index.html"
    html_path.write_text(html, encoding="utf-8")
    return html_path, json_path
