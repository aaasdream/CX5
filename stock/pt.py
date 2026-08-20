#!/usr/bin/env python
"""pt — 紙上台股實驗室的命令列介面。

    python pt.py sync                     抓當日行情與跨市場指標
    python pt.py status                   看帳戶現況
    python pt.py quote [2330 ...]         即時報價／現在能不能交易
    python pt.py buy 2330 1000 --reason "..." --thesis-title "..."
    python pt.py sell 2330 1000 --reason "..."
    python pt.py decision --code 2454 --action HOLD --reason "..."

成交價一律取證交所當下的即時價，**不能指定價格**，且只有台股交易時段
（週一至週五 09:00–13:30）才成交。收盤後下單會被拒絕，不補單。
    python pt.py news --title "..." --summary "..." --source ... --url ...
    python pt.py brief --stance "..." --macro "..." --tw "..." --outlook "..."
    python pt.py event 2026-08-26 "NVIDIA FY27Q2 財報" --importance 5
    python pt.py mark                     寫入當日淨值快照
    python pt.py report                   產生 index.html / data.json
    python pt.py daily                    sync + mark + report 一次做完

每個指令的 --help 都有說明。
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
if hasattr(sys.stdout, "reconfigure"):          # Windows 主控台預設 cp950，會炸中文
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from paper import config, db, journal, ledger, market, report  # noqa: E402

# 導向檔案或被其他程式擷取時關掉色碼，免得日誌裡塞滿跳脫序列
if sys.stdout.isatty():
    RED, GREEN, DIM, BOLD, OFF = "\033[31m", "\033[32m", "\033[2m", "\033[1m", "\033[0m"
else:
    RED = GREEN = DIM = BOLD = OFF = ""


def _c(v: float | None) -> str:
    """台股慣例上色：紅漲綠跌。"""
    if v is None:
        return DIM
    return RED if v > 0 else GREEN if v < 0 else DIM


def _sign(v: float, fmt: str = ",.0f") -> str:
    return f"{_c(v)}{v:+{fmt}}{OFF}"


# ── 指令 ────────────────────────────────────────────────────────────
def cmd_init(args, conn):
    db.init(initial_cash=args.cash)
    print(f"已初始化：{config.DB_PATH}")
    print(f"初始資金 {args.cash:,.0f} 元，起始日 {config.START_DATE}")


def cmd_sync(args, conn):
    codes = sorted(set(config.WATCHLIST) | {p["code"] for p in ledger.positions(conn)})
    print(f"{BOLD}台股日線{OFF}（{len(codes)} 檔）")
    market.fetch_tw_daily(conn, codes, start=args.start)
    print(f"\n{BOLD}跨市場指標{OFF}")
    market.fetch_macro(conn, lookback_days=args.lookback)


def cmd_status(args, conn):
    v = ledger.valuation(conn)
    a_start = db.get_meta(conn, "start_date", config.START_DATE)
    print(f"\n{BOLD}帳戶狀態{OFF}  起始 {a_start}   基準 {v['initial_cash']:,.0f}")
    print("─" * 78)
    print(f"  總資產   {v['total_equity']:>14,.0f}   累積報酬 "
          f"{_c(v['cum_return_pct'])}{v['cum_return_pct']:+.2f}%{OFF}")
    print(f"  現金     {v['cash']:>14,.0f}   水位 {v['cash_pct']:.1f}%")
    print(f"  持股市值 {v['positions_value']:>14,.0f}   未實現 {_sign(v['unrealized_pnl'])}")
    print(f"  已實現   {_sign(v['realized_pnl_cum']):>14}   累計費稅 {v['fees_cum']:,.0f}")

    if v["positions"]:
        print(f"\n{BOLD}持倉{OFF}")
        print(f"  {'代號':<7}{'名稱':<11}{'股數':>7}{'成本':>10}{'現價':>10}"
              f"{'市值':>12}{'損益':>12}{'報酬':>9}{'佔比':>8}")
        print("  " + "─" * 84)
        for p in v["positions"]:
            name = p["name"][:5]
            pad = " " * (10 - sum(2 if ord(ch) > 127 else 1 for ch in name))
            w = p["market_value"] / v["total_equity"] * 100 if v["total_equity"] else 0
            print(f"  {p['code']:<7}{name}{pad}{p['shares']:>7,}"
                  f"{p['avg_cost']:>10,.2f}{p['price']:>10,.2f}"
                  f"{p['market_value']:>12,.0f}"
                  f"{_c(p['unrealized_pnl'])}{p['unrealized_pnl']:>+12,.0f}{OFF}"
                  f"{_c(p['unrealized_pct'])}{p['unrealized_pct']:>+8.2f}%{OFF}"
                  f"{w:>7.1f}%")
    else:
        print(f"\n  {DIM}目前空手{OFF}")

    upcoming = journal.upcoming_events(conn, market.today(), days=14)
    if upcoming:
        print(f"\n{BOLD}兩週內事件{OFF}")
        for e in upcoming:
            stars = "★" * (e["importance"] or 0)
            print(f"  {e['date']}  {stars:<5} {e['title']}")
    print()


def cmd_buy(args, conn):
    """買進。成交價一律是證交所當下的即時價，這裡不能指定價格。"""
    now = dt.datetime.now()
    thesis_id = args.thesis_id
    if args.thesis_title:
        thesis_id = journal.add_thesis(
            conn, args.code, now.date().isoformat(), args.thesis_title,
            args.rationale or args.reason, catalysts=args.catalysts, risks=args.risks,
            target_price=args.target, stop_loss=args.stop, horizon=args.horizon,
            conviction=args.conviction)
        print(f"{DIM}已建立論點 #{thesis_id}{OFF}")
    try:
        t = ledger.buy(conn, args.code, args.shares, args.reason,
                       thesis_id=thesis_id, force=args.force)
    except market.MarketClosed as e:
        print(f"{RED}休市中，不能交易{OFF}")
        print(f"  {e}")
        print(f"{DIM}台股交易時段 09:00-13:30；錯過就是錯過，不補單。{OFF}")
        return 1
    except market.NoQuote as e:
        print(f"{RED}無法成交：{e}{OFF}")
        return 1
    except ledger.RiskViolation as e:
        print(f"{RED}風控擋下：{e}{OFF}")
        print(f"{DIM}確定要做就加 --force（覆蓋原因會記進成交紀錄）{OFF}")
        return 1
    print(f"{RED}買進{OFF} {t['name']} {t['code']}  {t['shares']:,} 股 @ {t['price']:,.2f}")
    print(f"  價金 {t['gross']:,.0f} + 手續費 {t['fee']:,.0f} = 實付 {t['net']:,.0f}")
    print(f"  餘額 {t['cash_after']:,.0f}")
    print(f"  {DIM}{t['price_source']}{OFF}")
    journal.add_decision(conn, t["date"], "BUY", args.reason, code=args.code,
                         executed=True, trade_id=t["trade_id"])


def cmd_sell(args, conn):
    """賣出。同樣只能用當下即時價成交。"""
    try:
        t = ledger.sell(conn, args.code, args.shares, args.reason,
                        close_thesis=args.outcome)
    except market.MarketClosed as e:
        print(f"{RED}休市中，不能交易{OFF}")
        print(f"  {e}")
        return 1
    except (market.NoQuote, ValueError) as e:
        print(f"{RED}無法成交：{e}{OFF}")
        return 1
    print(f"{GREEN}賣出{OFF} {t['name']} {t['code']}  {t['shares']:,} 股 @ {t['price']:,.2f}")
    print(f"  價金 {t['gross']:,.0f} - 手續費 {t['fee']:,.0f} - 證交稅 {t['tax']:,.0f} "
          f"= 實收 {t['net']:,.0f}")
    print(f"  已實現損益 {_sign(t['realized_pnl'])}   餘額 {t['cash_after']:,.0f}")
    print(f"  {DIM}{t['price_source']}{OFF}")
    journal.add_decision(conn, t["date"], "SELL", args.reason, code=args.code,
                         executed=True, trade_id=t["trade_id"])


def cmd_quote(args, conn):
    """看即時報價與目前是否可交易。"""
    now = dt.datetime.now()
    session = market.market_session(now)
    label = f"{GREEN}盤中可交易{OFF}" if session == "OPEN" else f"{DIM}休市{OFF}"
    print(f"{now:%Y-%m-%d %H:%M:%S}  {label}  {DIM}(台股 09:00-13:30){OFF}")
    print()
    codes = args.codes or sorted(set(config.WATCHLIST) |
                                 {p["code"] for p in ledger.positions(conn)})
    for code in codes:
        rt = market.realtime(code)
        if not rt:
            print(f"  {code:<7}{market.stock_name(code):<12} {DIM}無報價{OFF}")
            continue
        q = market.last_close(conn, code)
        chg = (rt["price"] / q[1] - 1) * 100 if q else None
        name = rt["name"][:6]
        pad = " " * max(1, 13 - sum(2 if ord(ch) > 127 else 1 for ch in name))
        chg_s = f"{_c(chg)}{chg:+.2f}%{OFF}" if chg is not None else ""
        print(f"  {code:<7}{name}{pad}{rt['price']:>10,.2f}  {chg_s}"
              f"   {DIM}{rt.get('time') or ''}{OFF}")


def cmd_thesis(args, conn):
    date = args.date or market.today()
    if args.update:
        journal.update_thesis(conn, args.update, date, title=args.title,
                              rationale=args.rationale, catalysts=args.catalysts,
                              risks=args.risks, target_price=args.target,
                              stop_loss=args.stop, horizon=args.horizon,
                              conviction=args.conviction, status=args.status,
                              outcome=args.outcome)
        print(f"論點 #{args.update} 已更新")
        return
    if args.list:
        for t in journal.theses(conn, status=args.status):
            print(f"  #{t['id']:<3} [{t['status']:<11}] {t['code']} {t['name']}  {t['title']}")
        return
    tid = journal.add_thesis(conn, args.code, date, args.title, args.rationale,
                             catalysts=args.catalysts, risks=args.risks,
                             target_price=args.target, stop_loss=args.stop,
                             horizon=args.horizon, conviction=args.conviction)
    print(f"已建立論點 #{tid}")


def cmd_decision(args, conn):
    date = args.date or market.today()
    journal.add_decision(conn, date, args.action, args.reason, code=args.code)
    tag = f"{args.code} " if args.code else ""
    print(f"已記錄 {date} {tag}{args.action}")


def cmd_news(args, conn):
    date = args.date or market.today()
    nid = journal.add_news(conn, date, args.title, source=args.source, url=args.url,
                           summary=args.summary, category=args.category,
                           sentiment=args.sentiment, importance=args.importance,
                           codes=args.codes)
    print(f"已記錄新聞 #{nid}")


def cmd_brief(args, conn):
    date = args.date or market.today()
    journal.set_brief(conn, date, macro=args.macro, tw_market=args.tw,
                      ai_sector=args.ai, crypto=args.crypto, key_events=args.events,
                      stance=args.stance, actions=args.actions, outlook=args.outlook)
    print(f"已寫入 {date} 簡報")


def cmd_event(args, conn):
    journal.add_event(conn, args.date, args.title, category=args.category,
                      importance=args.importance, note=args.note)
    print(f"已登錄事件 {args.date} {args.title}")


def cmd_mark(args, conn):
    date = args.date or market.today()
    s = ledger.snapshot(conn, date, note=args.note)
    line = (f"{date} 快照：總資產 {s['total_equity']:,.0f}  "
            f"累積 {_c(s['cum_return_pct'])}{s['cum_return_pct']:+.2f}%{OFF}")
    if s["twii_cum_pct"] is not None:
        line += f"  大盤同期 {s['twii_cum_pct']:+.2f}%"
    print(line)


def cmd_report(args, conn):
    html, js = report.render(conn, as_of=args.date)
    print(f"已產生 {html}")
    print(f"       {js}")


def cmd_daily(args, conn):
    print(f"{BOLD}=== {market.today()} 每日更新 ==={OFF}\n")
    cmd_sync(argparse.Namespace(start=args.start, lookback=10), conn)
    print()
    cmd_mark(argparse.Namespace(date=args.date, note=None), conn)
    cmd_report(argparse.Namespace(date=args.date), conn)
    print()
    cmd_status(args, conn)


# ── argparse ────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pt", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="建立資料庫")
    s.add_argument("--cash", type=float, default=config.INITIAL_CASH)
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("sync", help="抓行情與總經指標")
    s.add_argument("--start", default="2026-06-01", help="台股日線起始日")
    s.add_argument("--lookback", type=int, default=10, help="總經指標回看天數")
    s.set_defaults(fn=cmd_sync)

    s = sub.add_parser("status", help="帳戶現況")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("buy", help="買進（僅限盤中，價格由即時報價決定）")
    s.add_argument("code")
    s.add_argument("shares", type=int)
    s.add_argument("--reason", required=True, help="為什麼是今天、為什麼是這檔")
    s.add_argument("--force", action="store_true", help="覆蓋風控上限")
    s.add_argument("--thesis-id", type=int, help="掛到既有論點")
    s.add_argument("--thesis-title", help="同時建立新論點：一句話的買進理由")
    s.add_argument("--rationale", help="論點完整論證")
    s.add_argument("--catalysts")
    s.add_argument("--risks")
    s.add_argument("--target", type=float, help="目標價")
    s.add_argument("--stop", type=float, help="停損價")
    s.add_argument("--horizon", help="預期持有期間")
    s.add_argument("--conviction", type=int, choices=range(1, 6))
    s.set_defaults(fn=cmd_buy)

    s = sub.add_parser("sell", help="賣出（僅限盤中）")
    s.add_argument("code")
    s.add_argument("shares", type=int)
    s.add_argument("--reason", required=True)
    s.add_argument("--outcome", help="結案評語：論點對了還是錯了")
    s.set_defaults(fn=cmd_sell)

    s = sub.add_parser("quote", help="即時報價與可交易狀態")
    s.add_argument("codes", nargs="*")
    s.set_defaults(fn=cmd_quote)

    s = sub.add_parser("thesis", help="投資論點")
    s.add_argument("--code")
    s.add_argument("--title")
    s.add_argument("--rationale")
    s.add_argument("--catalysts")
    s.add_argument("--risks")
    s.add_argument("--target", type=float)
    s.add_argument("--stop", type=float)
    s.add_argument("--horizon")
    s.add_argument("--conviction", type=int, choices=range(1, 6))
    s.add_argument("--status", choices=["OPEN", "CLOSED", "INVALIDATED"])
    s.add_argument("--outcome")
    s.add_argument("--update", type=int, metavar="ID", help="更新既有論點")
    s.add_argument("--list", action="store_true")
    s.add_argument("--date")
    s.set_defaults(fn=cmd_thesis)

    s = sub.add_parser("decision", help="記錄決策（含決定不動）")
    s.add_argument("--code")
    s.add_argument("--action", required=True,
                   choices=["BUY", "SELL", "ADD", "TRIM", "HOLD", "WATCH", "PASS"])
    s.add_argument("--reason", required=True)
    s.add_argument("--date")
    s.set_defaults(fn=cmd_decision)

    s = sub.add_parser("news", help="記錄新聞")
    s.add_argument("--title", required=True)
    s.add_argument("--summary")
    s.add_argument("--source")
    s.add_argument("--url")
    s.add_argument("--category",
                   choices=["macro", "tw_market", "ai", "crypto", "geopolitics", "company"])
    s.add_argument("--sentiment", choices=["BULLISH", "BEARISH", "NEUTRAL", "MIXED"])
    s.add_argument("--importance", type=int, choices=range(1, 6))
    s.add_argument("--codes", help="相關個股，逗號分隔")
    s.add_argument("--date")
    s.set_defaults(fn=cmd_news)

    s = sub.add_parser("brief", help="每日簡報")
    s.add_argument("--macro")
    s.add_argument("--tw")
    s.add_argument("--ai")
    s.add_argument("--crypto")
    s.add_argument("--events")
    s.add_argument("--stance")
    s.add_argument("--actions")
    s.add_argument("--outlook")
    s.add_argument("--date")
    s.set_defaults(fn=cmd_brief)

    s = sub.add_parser("event", help="事件行事曆")
    s.add_argument("date")
    s.add_argument("title")
    s.add_argument("--category")
    s.add_argument("--importance", type=int, choices=range(1, 6))
    s.add_argument("--note")
    s.set_defaults(fn=cmd_event)

    s = sub.add_parser("mark", help="寫入當日淨值快照")
    s.add_argument("--date")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_mark)

    s = sub.add_parser("report", help="產生網頁")
    s.add_argument("--date")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("daily", help="sync + mark + report")
    s.add_argument("--start", default="2026-06-01")
    s.add_argument("--date")
    s.set_defaults(fn=cmd_daily)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    conn = db.init()
    return args.fn(args, conn) or 0


if __name__ == "__main__":
    raise SystemExit(main())
