"""人類可讀、可由公開資料重算的 Git 稽核輸出。"""
from __future__ import annotations

import csv
import datetime as dt
import sqlite3
from pathlib import Path

from . import config, journal, ledger

AUDIT_DIR = config.ROOT / "audit"
RECORD_DIR = config.ROOT / "records"
TABLES = ("meta", "trades", "positions", "theses", "thesis_revisions", "decisions", "snapshots",
          "news", "briefs", "events", "playbook", "macro", "quotes")


def export_csv(conn: sqlite3.Connection, out_dir: Path | None = None) -> list[Path]:
    """依主鍵/日期穩定排序匯出所有重算所需資料表。"""
    out = Path(out_dir or AUDIT_DIR)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for table in TABLES:
        columns = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
        pk = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})") if r["pk"]]
        order = pk or (["date", "id"] if "date" in columns and "id" in columns
                       else ["date"] if "date" in columns else columns[:1])
        rows = conn.execute(
            f"SELECT * FROM {table}" + (f" ORDER BY {','.join(order)}" if order else "")
        ).fetchall()
        path = out / f"{table}.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(columns)
            writer.writerows([[row[c] for c in columns] for row in rows])
        written.append(path)
    return written


def _text(value) -> str:
    return str(value).strip() if value not in (None, "") else "—"


def write_daily_record(conn: sqlite3.Connection, date: str,
                       *, correction: bool = False,
                       out_dir: Path | None = None) -> Path:
    """建立每日 Markdown；既有原始紀錄永不覆寫，修正一律另建新檔。"""
    dt.date.fromisoformat(date)
    out = Path(out_dir or RECORD_DIR)
    out.mkdir(parents=True, exist_ok=True)
    base = out / f"{date}.md"
    if correction:
        n = 1
        while (out / f"{date}-correction-{n:02d}.md").exists():
            n += 1
        path = out / f"{date}-correction-{n:02d}.md"
    else:
        path = base
        if path.exists():
            raise FileExistsError(
                f"{path} 已存在；規則禁止覆寫。若需修正請使用 --correction")

    snap = conn.execute("SELECT * FROM snapshots WHERE date=?", (date,)).fetchone()
    val = ledger.valuation(conn, date=date)
    brief = journal.brief(conn, date)
    decisions = journal.decisions(conn, date=date)
    trades = [dict(r) for r in conn.execute(
        "SELECT * FROM trades WHERE date=? ORDER BY id", (date,))]
    news = journal.news(conn, date=date)
    events = journal.upcoming_events(conn, date, days=60)
    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")

    lines = [
        f"# {date} 每日決策紀錄" + ("（修正）" if correction else ""), "",
        f"- 產生時間：`{now}`",
        "- 原則：交易僅能在台北時間 09:00–13:30，以證交所 MIS 當下即時價成交；錯過不補單。",
        f"- 今日是否交易：{'是' if trades else '否'}", "",
        "## 帳戶快照", "",
        f"- 現金：NT$ {val['cash']:,.0f}",
        f"- 持股市值：NT$ {val['positions_value']:,.0f}",
        f"- 總資產：NT$ {val['total_equity']:,.0f}",
        f"- 累積報酬：{val['cum_return_pct']:+.2f}%",
        f"- 已實現損益：NT$ {val['realized_pnl_cum']:,.0f}",
        f"- 累計費稅：NT$ {val['fees_cum']:,.0f}",
    ]
    if snap:
        lines.append(f"- 快照備註：{_text(snap['note'])}")

    lines += ["", "## 當日觀察與想法", ""]
    if brief:
        for label, key in (("總經與國際", "macro"), ("台股", "tw_market"),
                           ("AI／半導體", "ai_sector"), ("加密與風險偏好", "crypto"),
                           ("近期事件", "key_events"), ("立場", "stance"),
                           ("預定行動", "actions"), ("可驗證展望", "outlook")):
            lines += [f"### {label}", "", _text(brief.get(key)), ""]
    else:
        lines += ["本日尚無盤前簡報。", ""]

    lines += ["## 決策", ""]
    if decisions:
        for d in decisions:
            target = f"{d['code']} {d['name']}" if d.get("code") else "整體帳戶"
            lines.append(f"- **{d['action']}｜{target}**：{d['rationale']}"
                         f"（執行：{'是' if d['executed'] else '否'}）")
    else:
        lines.append("- 尚無決策紀錄。")

    lines += ["", "## 成交", ""]
    if trades:
        for t in trades:
            lines += [
                f"- **#{t['id']} {t['side']} {t['code']} {t['name']} {t['shares']:,} 股 @ {t['price']:,.2f}**",
                f"  - 時間：`{t['filled_at']}`；來源：{t['price_source']}",
                f"  - 價金 {t['gross']:,.0f}；手續費 {t['fee']:,.0f}；稅 {t['tax']:,.0f}；淨額 {t['net']:,.0f}",
                f"  - 理由：{t['reason']}",
            ]
    else:
        lines.append("- 無成交；沒有使用收盤價事後補記。")

    lines += ["", "## 持倉", ""]
    if val["positions"]:
        for p in val["positions"]:
            lines.append(f"- {p['code']} {p['name']}：{p['shares']:,} 股；均價 {p['avg_cost']:.2f}；"
                         f"估值價 {p['price']:.2f}（{_text(p['price_date'])}）；損益 {p['unrealized_pct']:+.2f}%")
    else:
        lines.append("- 全額現金，無持股。")

    lines += ["", "## 當日資料來源", ""]
    if news:
        for item in news:
            link = f" [{item['source']}]({item['url']})" if item.get("url") else f" {item.get('source') or ''}"
            lines.append(f"- {item['title']}。{_text(item.get('summary'))}{link}")
    else:
        lines.append("- 尚無來源條目。")

    lines += ["", "## 重要日期（未來 60 日）", ""]
    if events:
        for e in events:
            lines.append(f"- {e['date']}｜{'★' * (e['importance'] or 0)}｜{e['title']}：{_text(e['note'])}")
    else:
        lines.append("- 無。")
    lines += ["", "---", "", "重算資料位於 `stock/audit/*.csv`；歷史修正只能新增 correction 檔，不得覆寫本檔。", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
