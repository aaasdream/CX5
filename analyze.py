#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""依「360環景 + 前座通風座椅」硬需求篩選當日快照。

合格範圍（見 尋找車子/CX5_合格車款與車源.md）：
    2025 年式 — 任何等級
    2024 年式 — 僅 Select Plus 以上（20S Select 無通風，不合格）
    2023 以前 — 除非確認頂規，否則不合格

用法：python analyze.py [YYYY-MM-DD]
"""

import io
import json
import os
import re
import sys
from datetime import date as _date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# 2024 年式有通風座椅的等級（Select Plus 以上）
TRIM_2024_OK = re.compile(r"Select\s*Plus|Premium|Signature|GT\b|25T|淬鍊", re.I)
# 2024 入門 20S Select（無 Plus）沒有通風座椅
HAS_SELECT = re.compile(r"Select", re.I)
HAS_SELECT_PLUS = re.compile(r"Select\s*Plus", re.I)


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
    """回傳 (是否合格, 說明)。"""
    y = year_int(v["year"])
    model = v["model"]
    if y is None:
        return False, "年份不明"
    if y >= 2025:
        return True, "2025+ 全車系標配 360+通風"
    if y == 2024:
        if HAS_SELECT.search(model) and not HAS_SELECT_PLUS.search(model):
            return False, "2024 入門 Select — 無通風"
        if TRIM_2024_OK.search(model):
            return True, "2024 Select Plus 以上"
        return False, "2024 等級待確認"
    return False, "%d 年式 — 360 非全車系標配" % y


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
    print("合格 %d 台 / 不合格 %d 台 / 價格可疑 %d 台\n" % (len(ok), len(ng), len(flagged)))

    ok.sort(key=lambda x: (price_wan(x[0]["price_text"]) or 9e9))
    print("--- 合格車源（依價格排序）---")
    print("%-6s %-26s %-10s %-8s %-6s %s" % ("年式", "等級", "里程", "價格", "地區", "連結"))
    for v, why in ok:
        print("%-6s %-26s %-10s %-8s %-6s %s" % (
            v["year"], v["model"][:26], v["mileage_text"],
            v["price_text"], v["region"], v["url"]))

    kh = [x for x in ok if "高雄" in x[0]["region"]]
    print("\n--- 高雄在地合格：%d 台 ---" % len(kh))
    for v, why in kh:
        print("  %s %s | %s | %s | %s" % (
            v["year"], v["model"], v["mileage_text"], v["price_text"], v["url"]))

    print("\n--- 價格可疑（不要當成行情）---")
    for v, why in flagged:
        print("  %s %-30s %-9s %-7s %-6s ← %s" % (
            v["year"], v["model"][:30], v["mileage_text"],
            v["price_text"], v["region"], why))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
