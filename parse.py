#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析 8891 每日抓取的原始清單，統計後寫入 data/history.json。

用法：python parse.py 2026-08-17
原始檔格式（raw/8891_YYYY-MM-DD.txt）每行：
    年式|車型|里程|價格
每頁最後一行為 TOTAL=N
"""

import json
import os
import re
import statistics
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(BASE_DIR, "raw")
DATA_DIR = os.path.join(BASE_DIR, "data")
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")

NO_VALUE = ("電洽", "未揭露", "面議", "洽詢", "-", "")

NUM = r"([0-9]+(?:\.[0-9]+)?)"


def parse_mileage(text):
    """'5000公里' -> 5000、'3.5萬公里' -> 35000、'電洽' -> None"""
    s = text.strip().replace(",", "").replace(" ", "")
    if not s or s in NO_VALUE:
        return None
    m = re.search(NUM + r"\s*萬", s)
    if m:
        return int(round(float(m.group(1)) * 10000))
    m = re.search(NUM, s)
    if m:
        return int(round(float(m.group(1))))
    return None


def parse_price(text):
    """'89.8萬' -> 898000、'電洽'/'未揭露' -> None"""
    s = text.strip().replace(",", "").replace(" ", "")
    if not s or s in NO_VALUE:
        return None
    m = re.search(NUM + r"\s*萬", s)
    if m:
        return int(round(float(m.group(1)) * 10000))
    m = re.search(NUM, s)
    if m:
        value = float(m.group(1))
        # 純數字：小於 1000 視為「萬」為單位，否則視為元
        return int(round(value * 10000)) if value < 1000 else int(round(value))
    return None


def percentile(sorted_values, q):
    """線性內插百分位數（與 statistics inclusive quantiles 一致）。"""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return int(sorted_values[0])
    pos = (len(sorted_values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return int(round(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac))


def parse_file(path):
    """回傳 (rows, total_declared, totals)。rows 為 dict 清單。

    TOTAL=N 是網站宣告的「總筆數」，每頁重複出現（偶爾因為上架/下架而
    有 1~2 筆落差），因此取出現次數最多的那個值當作宣告總數，平手取大。
    """
    rows = []
    totals = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            m = re.match(r"^TOTAL\s*=\s*([0-9]+)$", line, re.IGNORECASE)
            if m:
                totals.append(int(m.group(1)))
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 4:
                continue  # 格式不符，略過
            year, model, mileage_raw, price_raw = parts[0], parts[1], parts[2], parts[3]
            if not year or not model:
                continue
            rows.append({
                "year": year,
                "model": model,
                "mileage": parse_mileage(mileage_raw),
                "price": parse_price(price_raw),
            })
    total_declared = max(totals, key=lambda v: (totals.count(v), v)) if totals else 0
    return rows, total_declared, totals


def summarize(rows, total_declared, date, raw_rel):
    prices = sorted(p for p in (r["price"] for r in rows) if p is not None)
    return {
        "n": len(rows),
        "n_priced": len(prices),
        "median": int(round(statistics.median(prices))) if prices else None,
        "p25": percentile(prices, 0.25),
        "p75": percentile(prices, 0.75),
        "min_priced": prices[0] if prices else None,
        "max_priced": prices[-1] if prices else None,
        "complete": bool(total_declared) and len(rows) == total_declared,
        "raw_path": raw_rel,
    }


def load_history():
    if not os.path.exists(HISTORY_PATH):
        return {"records": {}}
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (ValueError, OSError):
        return {"records": {}}
    if not isinstance(data, dict) or not isinstance(data.get("records"), dict):
        return {"records": {}}
    return data


def save_history(history):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = HISTORY_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(history, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, HISTORY_PATH)


def main(argv):
    if len(argv) != 2 or not re.match(r"^\d{4}-\d{2}-\d{2}$", argv[1]):
        print("用法: python parse.py YYYY-MM-DD")
        return 2
    date = argv[1]
    raw_path = os.path.join(RAW_DIR, "8891_%s.txt" % date)
    if not os.path.exists(raw_path):
        print("找不到原始檔: %s" % raw_path)
        return 1

    rows, total_declared, totals = parse_file(raw_path)
    record = summarize(rows, total_declared, date, "raw/8891_%s.txt" % date)

    history = load_history()
    history["records"][date] = record  # 追加/覆寫該日，其餘保留
    save_history(history)

    print("%s 解析完成：n=%d n_priced=%d TOTAL=%d（%d 頁）complete=%s"
          % (date, record["n"], record["n_priced"], total_declared,
             len(totals), record["complete"]))
    if len(set(totals)) > 1:
        print("  註：各頁 TOTAL 不一致 %s，採用 %d" % (totals, total_declared))
    print("  中位=%s p25=%s p75=%s 最低=%s 最高=%s"
          % (record["median"], record["p25"], record["p75"],
             record["min_priced"], record["max_priced"]))
    print("  已寫入 %s" % HISTORY_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
