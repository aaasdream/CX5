#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""從 8891 抓取 CX-5 在售清單。

用法：
    python scrape.py              # 抓今天
    python scrape.py 2026-08-17   # 指定日期（覆寫該日檔案）

產出兩份：
    raw/8891_YYYY-MM-DD.txt        年式|車型|里程|價格（含每頁 TOTAL=N）→ 給 parse.py
    data/listings_YYYY-MM-DD.json  以車輛 ID 為鍵的完整快照 → 給 diff 比對用

只用標準庫。頁面是伺服器端渲染，不需要 Playwright。
"""

import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date as _date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(BASE_DIR, "raw")
DATA_DIR = os.path.join(BASE_DIR, "data")

LIST_URL = "https://auto.8891.com.tw/mazda/cx-5"
ITEM_URL = "https://auto.8891.com.tw/item/%s"
PER_PAGE = 40
MAX_PAGES = 30
DELAY_SEC = 2.0          # 客氣一點，一天總共也才幾次請求
TIMEOUT = 30
RETRIES = 3

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


# ---------- 抓取 ----------

def fetch(url):
    last = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept-Language": "zh-TW,zh;q=0.9",
                "Accept": "text/html,application/xhtml+xml",
            })
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError) as exc:
            last = exc
            if attempt < RETRIES - 1:
                time.sleep(DELAY_SEC * (attempt + 2))
    raise RuntimeError("抓取失敗 %s：%s" % (url, last))


# ---------- 解析 ----------

def tokenize(fragment):
    """把卡片 HTML 拆成純文字 token 序列。

    不依賴 class 名稱：8891 是 Next.js CSS Modules，class 長得像
    listItem_ib-price__W_88B，尾巴的 hash 每次改版都會變。卡片內的
    「文字順序」反而穩定：… | 58.8 | 萬 | 賣點 | ： | … | 2021年 | 4萬公里
    """
    text = re.sub(r"<[^>]+>", "\x01", fragment)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    parts = [p.strip() for p in text.split("\x01") if p.strip()]
    return [p for p in parts if not p.startswith("data-testid")]


def parse_card(card):
    m = re.search(r'data-testid="auto-list-item-(\d+)"', card)
    if not m:
        return None
    car_id = m.group(1)
    tokens = tokenize(card)

    title = next((t for t in tokens if re.match(r"^Mazda\s+CX-?5", t, re.I)), "")

    # 價格：找「數字 + 萬」這組相鄰 token。描述文字裡的「僅跑4萬」不會拆成
    # 兩個 token，所以不會誤判。
    price_text = ""
    for i, t in enumerate(tokens):
        if t == u"萬" and i and re.match(r"^[0-9][0-9.]*$", tokens[i - 1]):
            price_text = tokens[i - 1] + u"萬"
            break
    if not price_text:
        price_text = u"電洽"

    years = [t for t in tokens if re.match(r"^\d{4}年$", t)]
    miles = [t for t in tokens if re.match(r"^[0-9][0-9.]*\s*萬?公里$", t)]
    year_text = years[-1] if years else ""
    if not year_text:
        ym = re.search(r"(\d{4})\s*款", title)
        year_text = (ym.group(1) + u"年") if ym else ""
    mileage_text = miles[-1].replace(" ", "") if miles else u"電洽"

    # 車型：把標題的 'Mazda CX-5 2021款 ' 前綴去掉
    model = re.sub(r"^\s*Mazda\s+CX-?5\s*", "", title, flags=re.I)
    model = re.sub(r"^\s*\d{4}\s*款\s*", "", model).strip() or title.strip() or "CX-5"

    region = next((t for t in tokens if re.match(r"^..[市縣]$", t)), "")

    return {
        "id": car_id,
        "year": year_text,
        "model": model,
        "mileage_text": mileage_text,
        "price_text": price_text,
        "region": region,
        "title": title,
        "url": ITEM_URL % car_id,
    }


def parse_page(html):
    cards = re.split(r'(?=data-testid="auto-list-item-\d+")', html)
    out = []
    for card in cards[1:]:
        rec = parse_card(card[:6000])
        if rec:
            out.append(rec)
    return out


def parse_total(html):
    text = " ".join(tokenize(html))
    for pat in [r"共\s*(\d{1,5})\s*[台輛筆部]", r"(\d{2,5})\s*[台輛]"]:
        m = re.search(pat, text)
        if m:
            return int(m.group(1))
    return 0


# ---------- 主流程 ----------

def scrape():
    all_rows = []
    seen = set()
    total = 0
    pages = 0

    for page in range(1, MAX_PAGES + 1):
        url = LIST_URL if page == 1 else "%s?page=%d" % (LIST_URL, page)
        html = fetch(url)
        pages += 1
        rows = parse_page(html)
        if page == 1:
            total = parse_total(html)
            print("  宣告總數 TOTAL=%d" % total)
        fresh = [r for r in rows if r["id"] not in seen]
        for r in fresh:
            seen.add(r["id"])
        all_rows.append(rows)          # 保留原頁順序，raw 檔照頁寫出
        print("  第 %d 頁：%d 筆（新 %d 筆，累計唯一 %d）"
              % (page, len(rows), len(fresh), len(seen)))

        if not rows or not fresh:
            break
        if total and len(seen) >= total:
            break
        if len(rows) < PER_PAGE:
            break
        time.sleep(DELAY_SEC)

    return all_rows, total, pages


def write_raw(pages_rows, total, path):
    with io.open(path, "w", encoding="utf-8") as fh:
        for rows in pages_rows:
            for r in rows:
                fh.write(u"%s|%s|%s|%s\n" % (
                    r["year"], r["model"], r["mileage_text"], r["price_text"]))
            fh.write(u"TOTAL=%d\n" % total)


def write_snapshot(pages_rows, total, day, path):
    uniq = {}
    for rows in pages_rows:
        for r in rows:
            uniq.setdefault(r["id"], r)
    snapshot = {"date": day, "total_declared": total,
                "n_unique": len(uniq), "listings": uniq}
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))
        fh.write(u"\n")
    return len(uniq)


def main(argv):
    day = argv[1] if len(argv) > 1 else _date.today().strftime("%Y-%m-%d")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        print("用法: python scrape.py [YYYY-MM-DD]")
        return 2

    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print("抓取 %s ..." % LIST_URL)
    pages_rows, total, pages = scrape()
    n_rows = sum(len(p) for p in pages_rows)
    if not n_rows:
        print("沒有抓到任何車輛 —— 版面可能改了，先不覆寫既有檔案。")
        return 1

    raw_path = os.path.join(RAW_DIR, "8891_%s.txt" % day)
    snap_path = os.path.join(DATA_DIR, "listings_%s.json" % day)
    write_raw(pages_rows, total, raw_path)
    n_uniq = write_snapshot(pages_rows, total, day, snap_path)

    print("完成：%d 頁 / %d 列 / %d 台唯一（宣告 %d）" % (pages, n_rows, n_uniq, total))
    print("  %s" % raw_path)
    print("  %s" % snap_path)
    if total and n_uniq != total:
        print("  註：唯一台數與宣告總數差 %d，8891 分頁本身會有重複車源。"
              % (n_uniq - total))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
