#!/usr/bin/env python
"""audit — 獨立稽核器：把整本帳從頭重算一次，並比對公開報價。

這支程式是寫給**驗證方**用的（包含其他 AI）。它不信任資料庫裡的任何
彙總欄位，只從 trades 表逐筆重算，再拿 FinMind 的公開日線比對成交價。

    python audit.py                 完整稽核
    python audit.py --no-network    只做內部一致性檢查（不打 FinMind）
    python audit.py --json          輸出機器可讀結果

檢查項目
  1. 現金流水：從初始資金逐筆套用，比對每筆 cash_after 與最終餘額
  2. 持倉重建：加權平均成本重算，比對 positions 表
  3. 費用重算：每筆手續費與證交稅是否符合公告費率
  4. 成交價：是否落在當日公開的最高／最低價區間內（抓不到就報告，不當作通過）
  5. 交易時段：是否都在 09:00–13:30 的交易日成交、fill_mode 是否為 LIVE
  6. 帳務恆等式：初始資金 + 已實現損益 - 累計費稅 是否 = 現金 + 持股成本

任何一項 FAIL 都代表這本帳不可信。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from paper import config, db, fees, market  # noqa: E402

TOL = 0.51          # 金額容差（元）：費用採整數捨去，容許不到 1 元的浮點誤差


class Report:
    def __init__(self):
        self.checks: list[dict] = []

    def add(self, name: str, ok: bool, detail: str = "", *, warn: bool = False):
        self.checks.append({"check": name, "status": "WARN" if warn and not ok
                            else ("PASS" if ok else "FAIL"), "detail": detail})

    @property
    def failed(self):
        return [c for c in self.checks if c["status"] == "FAIL"]

    @property
    def warned(self):
        return [c for c in self.checks if c["status"] == "WARN"]

    def print(self):
        icon = {"PASS": "  OK ", "FAIL": " FAIL", "WARN": " WARN"}
        for c in self.checks:
            print(f"{icon[c['status']]}  {c['check']}")
            if c["detail"]:
                for line in c["detail"].splitlines():
                    print(f"        {line}")
        print()
        if self.failed:
            print(f"稽核未通過：{len(self.failed)} 項失敗、{len(self.warned)} 項警告")
        elif self.warned:
            print(f"稽核通過，但有 {len(self.warned)} 項警告需人工確認")
        else:
            print("稽核全數通過。")


def audit(conn, use_network: bool = True) -> Report:
    r = Report()
    trades = [dict(t) for t in conn.execute(
        "SELECT * FROM trades ORDER BY date, id")]
    initial = float(db.get_meta(conn, "initial_cash", str(config.INITIAL_CASH)))

    if not trades:
        r.add("交易紀錄", True, "尚無成交紀錄，帳戶為初始狀態")
        cash_now = float(db.get_meta(conn, "cash", "0"))
        r.add("初始現金", abs(cash_now - initial) < TOL,
              f"帳上 {cash_now:,.2f} / 應為 {initial:,.2f}")
        return r

    # ── 1. 現金流水 ────────────────────────────────────────────────
    cash = initial
    problems = []
    for t in trades:
        cash += -t["net"] if t["side"] == "BUY" else t["net"]
        if abs(cash - t["cash_after"]) > TOL:
            problems.append(f"#{t['id']} {t['date']} {t['code']}：重算 {cash:,.2f}"
                            f" ≠ 帳上 {t['cash_after']:,.2f}")
        if cash < -TOL:
            problems.append(f"#{t['id']} {t['date']} 現金為負 {cash:,.2f}（透支）")
    cash_meta = float(db.get_meta(conn, "cash", "0"))
    if abs(cash - cash_meta) > TOL:
        problems.append(f"最終餘額：重算 {cash:,.2f} ≠ 帳上 {cash_meta:,.2f}")
    r.add(f"現金流水逐筆重算（{len(trades)} 筆）", not problems,
          "\n".join(problems) or f"最終現金 {cash:,.2f}")

    # ── 2. 持倉重建 ────────────────────────────────────────────────
    book: dict[str, dict] = {}
    realized = 0.0
    problems = []
    for t in trades:
        c = book.setdefault(t["code"], {"shares": 0, "cost": 0.0})
        if t["side"] == "BUY":
            c["shares"] += t["shares"]
            c["cost"] += t["net"]
        else:
            if t["shares"] > c["shares"]:
                problems.append(f"#{t['id']} {t['date']} 賣超：持有 {c['shares']}"
                                f" 卻賣 {t['shares']}")
                continue
            avg = c["cost"] / c["shares"] if c["shares"] else 0.0
            pnl = t["net"] - avg * t["shares"]
            if t["realized_pnl"] is not None and abs(pnl - t["realized_pnl"]) > TOL:
                problems.append(f"#{t['id']} {t['date']} {t['code']} 已實現損益："
                                f"重算 {pnl:,.2f} ≠ 帳上 {t['realized_pnl']:,.2f}")
            realized += pnl
            c["cost"] -= avg * t["shares"]
            c["shares"] -= t["shares"]

    stored = {p["code"]: dict(p) for p in conn.execute(
        "SELECT * FROM positions WHERE shares > 0")}
    rebuilt = {k: v for k, v in book.items() if v["shares"] > 0}
    for code in set(stored) | set(rebuilt):
        s, b = stored.get(code), rebuilt.get(code)
        if not s:
            problems.append(f"{code}：重算持有 {b['shares']} 股，但 positions 表沒有")
        elif not b:
            problems.append(f"{code}：positions 表有 {s['shares']} 股，但重算為 0")
        else:
            if s["shares"] != b["shares"]:
                problems.append(f"{code} 股數：重算 {b['shares']} ≠ 帳上 {s['shares']}")
            if abs(s["total_cost"] - b["cost"]) > TOL:
                problems.append(f"{code} 成本：重算 {b['cost']:,.2f}"
                                f" ≠ 帳上 {s['total_cost']:,.2f}")
    r.add(f"持倉與成本重建（{len(rebuilt)} 檔）", not problems,
          "\n".join(problems) or
          " / ".join(f"{k} {v['shares']:,}股 成本 {v['cost']:,.0f}"
                     for k, v in rebuilt.items()) or "空手")

    # ── 3. 費用重算 ────────────────────────────────────────────────
    problems = []
    for t in trades:
        c = fees.compute(t["side"], t["price"], t["shares"])
        if abs(c.fee - t["fee"]) > TOL:
            problems.append(f"#{t['id']} 手續費：應 {c.fee:,.0f} / 帳上 {t['fee']:,.0f}")
        if abs(c.tax - t["tax"]) > TOL:
            problems.append(f"#{t['id']} 證交稅：應 {c.tax:,.0f} / 帳上 {t['tax']:,.0f}")
        if abs(c.gross - t["gross"]) > TOL:
            problems.append(f"#{t['id']} 價金：應 {c.gross:,.2f} / 帳上 {t['gross']:,.2f}")
    r.add("手續費與證交稅重算", not problems,
          "\n".join(problems) or
          f"費率 {config.FEE_RATE * 100:.4f}% × {config.FEE_DISCOUNT} 折"
          f"（低消 {config.FEE_MIN:.0f}）、賣出稅 {config.TAX_RATE_SELL * 100:.1f}%")

    # ── 4. 交易時段與成交模式 ──────────────────────────────────────
    problems = []
    for t in trades:
        d = dt.date.fromisoformat(t["date"])
        if d.weekday() >= 5:
            problems.append(f"#{t['id']} {t['date']} 是{'六日'[d.weekday() - 5]}，非交易日")
        if t["fill_mode"] != "LIVE":
            problems.append(f"#{t['id']} {t['date']} 成交模式為 {t['fill_mode']}"
                            f"（非盤中即時價，可能含前視）")
        if t["filled_at"]:
            try:
                ts = dt.datetime.strptime(t["filled_at"], "%Y-%m-%d %H:%M:%S")
                if not (market.TRADING_OPEN <= ts.time() <= market.TRADING_CLOSE):
                    problems.append(f"#{t['id']} 成交時間 {t['filled_at']} 不在 09:00–13:30")
                if ts.date().isoformat() != t["date"]:
                    problems.append(f"#{t['id']} 成交時間戳日期 {ts.date()}"
                                    f" 與成交日 {t['date']} 不符")
            except ValueError:
                problems.append(f"#{t['id']} 成交時間戳格式無法解析：{t['filled_at']}")
        else:
            problems.append(f"#{t['id']} 沒有成交時間戳")
    r.add("交易時段與成交模式", not problems,
          "\n".join(problems) or "全部為交易日盤中（09:00–13:30）即時價成交")

    # ── 5. 成交價 vs 公開報價 ──────────────────────────────────────
    if use_network:
        problems, warnings, checked = [], [], 0
        for t in trades:
            try:
                rows = market._finmind_get("TaiwanStockPrice", t["code"],
                                           t["date"], t["date"])
            except Exception as e:
                warnings.append(f"#{t['id']} {t['code']} {t['date']} 無法查證：{e}")
                continue
            row = next((x for x in rows if x["date"] == t["date"]), None)
            if not row:
                warnings.append(f"#{t['id']} {t['code']} {t['date']} 公開日線查無此日")
                continue
            lo, hi = row.get("min"), row.get("max")
            checked += 1
            if lo is None or hi is None:
                warnings.append(f"#{t['id']} {t['code']} {t['date']} 日線缺高低價")
            elif not (lo - 0.001 <= t["price"] <= hi + 0.001):
                problems.append(f"#{t['id']} {t['code']} {t['date']} 成交價 {t['price']:.2f}"
                                f" 不在當日區間 [{lo:.2f}, {hi:.2f}]")
        r.add(f"成交價落在公開高低價區間（查證 {checked}/{len(trades)} 筆）",
              not problems, "\n".join(problems + warnings) or
              "每筆成交價都在當日公開的最高／最低價之間")
        if warnings and not problems:
            r.add("成交價查證覆蓋率", False, f"{len(warnings)} 筆無法查證", warn=True)
    else:
        r.add("成交價 vs 公開報價", False, "已略過（--no-network）", warn=True)

    # ── 6. 帳務恆等式 ──────────────────────────────────────────────
    total_fees = sum(t["fee"] + t["tax"] for t in trades)
    cost_held = sum(v["cost"] for v in rebuilt.values())
    lhs = cash + cost_held
    rhs = initial + realized
    r.add("帳務恆等式（現金 + 持股成本 = 初始資金 + 已實現損益）",
          abs(lhs - rhs) < TOL * len(trades) + TOL,
          f"{lhs:,.2f} vs {rhs:,.2f}   累計費稅 {total_fees:,.2f}"
          f"（已內含於上式）")
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", help="資料庫路徑（預設 db/portfolio.db）")
    ap.add_argument("--no-network", action="store_true", help="不打 FinMind 查證成交價")
    ap.add_argument("--json", action="store_true", help="輸出 JSON")
    a = ap.parse_args(argv)

    conn = db.connect(a.db)
    rep = audit(conn, use_network=not a.no_network)

    if a.json:
        print(json.dumps({
            "audited_at": dt.datetime.now().isoformat(timespec="seconds"),
            "passed": not rep.failed,
            "checks": rep.checks,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"\n稽核帳本：{a.db or config.DB_PATH}")
        print(f"時間：{dt.datetime.now():%Y-%m-%d %H:%M:%S}")
        print("─" * 72)
        rep.print()
    return 1 if rep.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
