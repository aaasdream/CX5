#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""篩選當日快照，找出目標車源。

硬需求：360 度環景 + 前座通風座椅（見 尋找車子/CX5_合格車款與車源.md）。
2025 年式起兩者全車系標配，因此鎖定：

    ✅ 2025 年式 20S Select Plus

2024 年式雖然 Select Plus 以上也有通風，但使用者 2026-08-17 決定不看 2024。
要放寬範圍改下面兩個常數即可。

用法：python analyze.py [YYYY-MM-DD]
產出：data/targets_<date>.json（給 build_dashboard.py 用）
"""

import io
import json
import os
import re
import sys
from datetime import date as _date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

MIN_YEAR = 2025                                    # 只看 2025 年式（含以後）
TARGET_TRIM = re.compile(r"Select\s*Plus", re.I)   # 只看 20S Select Plus
HOME_REGION = "高雄"


def load(day):
    path = os.path.join(DATA_DIR, "listings_%s.json" % day)
    if not os.path.exists(path):
        raise SystemExit("找不到快照：%s（先跑 python scrape.py %s）" % (path, day))
    return json.load(io.open(path, encoding="utf-8"))


def price_wan(text):
    m = re.match(r"^([0-9.]+)萬$", text or "")
    return float(m.group(1)) if m else None


def mileage_wan(text):
    t = (text or "").replace(" ", "")
    m = re.match(r"^([0-9.]+)萬公里$", t)
    if m:
        return float(m.group(1))
    m = re.match(r"^([0-9.]+)公里$", t)
    if m:
        return float(m.group(1)) / 10000.0
    return None


def year_int(text):
    m = re.match(r"^(\d{4})年$", text or "")
    return int(m.group(1)) if m else None


def classify(v):
    """回傳 (是否為目標車, 說明)。"""
    y = year_int(v["year"])
    if y is None:
        return False, "年份不明"
    if y < MIN_YEAR:
        return False, "%d 年式 — 不在範圍" % y
    if not TARGET_TRIM.search(v["model"]):
        return False, "%d 年式但非 Select Plus" % y
    return True, "%d Select Plus" % y


def suspicious(v):
    """一年內新車卻打骨折價 → 多半是頭期款/釣魚/事故車。"""
    y, p, km = year_int(v["year"]), price_wan(v["price_text"]), mileage_wan(v["mileage_text"])
    if y is None or p is None:
        return None
    if y >= 2024 and p < 60:
        return "%d年式僅 %.1f萬" % (y, p)
    if y >= 2023 and km is not None and km < 3 and p < 45:
        return "%d年式 %.1f萬公里僅 %.1f萬" % (y, km, p)
    return None


def main(argv):
    day = argv[1] if len(argv) > 1 else _date.today().strftime("%Y-%m-%d")
    snap = load(day)
    listings = list(snap["listings"].values())

    ok, ng, flagged = [], [], []
    for v in listings:
        sus = suspicious(v)
        if sus:
            flagged.append((v, sus))
        good, why = classify(v)
        (ok if good else ng).append((v, why))

    print("=== %s 快照：%d 台 ===" % (day, len(listings)))
    print("目標（%d+ Select Plus）%d 台 / 其他 %d 台 / 價格可疑 %d 台\n"
          % (MIN_YEAR, len(ok), len(ng), len(flagged)))

    ok.sort(key=lambda x: (price_wan(x[0]["price_text"]) or 9e9))
    print("--- 目標車源（依價格排序）---")
    print("%-6s %-24s %-10s %-8s %-6s %s" % ("年式", "等級", "里程", "價格", "地區", "連結"))
    for v, why in ok:
        print("%-6s %-24s %-10s %-8s %-6s %s" % (
            v["year"], v["model"][:24], v["mileage_text"],
            v["price_text"], v["region"], v["url"]))

    kh = [x for x in ok if HOME_REGION in x[0]["region"]]
    print("\n--- %s在地：%d 台 ---" % (HOME_REGION, len(kh)))
    for v, why in kh:
        print("  %s %s | %s | %s | %s" % (
            v["year"], v["model"], v["mileage_text"], v["price_text"], v["url"]))

    prices = sorted(p for p in (price_wan(v["price_text"]) for v, _ in ok) if p)
    if prices:
        mid = prices[len(prices) // 2] if len(prices) % 2 else \
            (prices[len(prices) // 2 - 1] + prices[len(prices) // 2]) / 2.0
        print("\n目標行情帶：%.1f ~ %.1f 萬（中位 %.1f 萬，%d 台有價）"
              % (prices[0], prices[-1], mid, len(prices)))

    if flagged:
        print("\n--- 價格可疑（不列入行情）---")
        for v, why in flagged:
            print("  %s %-28s %-9s %-7s %-6s ← %s" % (
                v["year"], v["model"][:28], v["mileage_text"],
                v["price_text"], v["region"], why))

    # 寫出給網頁用的目標清單
    out = {
        "date": day,
        "criteria": "%d+ 年式 20S Select Plus（360環景 + 前座通風標配）" % MIN_YEAR,
        "home_region": HOME_REGION,
        "n_scanned": len(listings),
        "targets": [dict(v, why=why) for v, why in ok],
        "suspicious": [dict(v, why=why) for v, why in flagged],
    }
    path = os.path.join(DATA_DIR, "targets_%s.json" % day)
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
        fh.write(u"\n")
    print("\n已寫入 %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
