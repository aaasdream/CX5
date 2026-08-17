#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""比對兩日快照，找出新上架／下架／改價。

以 8891 車輛 ID 為鍵，不靠文字比對，車商改標題也不會誤判。

用法：
    python diff.py 2026-08-18            # 與前一份快照比
    python diff.py 2026-08-18 2026-08-17 # 指定基準日
產出：data/diff_<new>.json
"""

import glob
import io
import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")


def snap_path(day):
    return os.path.join(DATA_DIR, "listings_%s.json" % day)


def available_days():
    days = []
    for p in glob.glob(os.path.join(DATA_DIR, "listings_*.json")):
        m = re.search(r"listings_(\d{4}-\d{2}-\d{2})\.json$", p)
        if m:
            days.append(m.group(1))
    return sorted(days)


def load(day):
    path = snap_path(day)
    if not os.path.exists(path):
        raise SystemExit("找不到快照：%s" % path)
    return json.load(io.open(path, encoding="utf-8"))["listings"]


def price_wan(text):
    m = re.match(r"^([0-9.]+)萬$", text or "")
    return float(m.group(1)) if m else None


def label(v):
    return "%s %s｜%s｜%s｜%s" % (
        v.get("year", ""), v.get("model", ""), v.get("mileage_text", ""),
        v.get("price_text", ""), v.get("region", ""))


def main(argv):
    days = available_days()
    if len(argv) > 1:
        new_day = argv[1]
    elif days:
        new_day = days[-1]
    else:
        raise SystemExit("沒有任何快照，先跑 scrape.py")

    if len(argv) > 2:
        old_day = argv[2]
    else:
        earlier = [d for d in days if d < new_day]
        if not earlier:
            raise SystemExit("只有 %s 一份快照，還沒得比。明天再跑一次就有了。" % new_day)
        old_day = earlier[-1]

    old, new = load(old_day), load(new_day)
    old_ids, new_ids = set(old), set(new)

    added = [new[i] for i in sorted(new_ids - old_ids)]
    removed = [old[i] for i in sorted(old_ids - new_ids)]

    changed = []
    for i in sorted(old_ids & new_ids):
        po, pn = price_wan(old[i]["price_text"]), price_wan(new[i]["price_text"])
        if po is None or pn is None:
            if old[i]["price_text"] != new[i]["price_text"]:
                changed.append({"car": new[i], "old": old[i]["price_text"],
                                "new": new[i]["price_text"], "delta": None})
            continue
        if abs(pn - po) >= 0.05:
            changed.append({"car": new[i], "old": po, "new": pn, "delta": pn - po})

    print("=== %s → %s ===" % (old_day, new_day))
    print("在售 %d → %d 台（新上架 %d／下架 %d／改價 %d）\n"
          % (len(old), len(new), len(added), len(removed), len(changed)))

    if changed:
        print("--- 改價 ---")
        for c in sorted(changed, key=lambda x: (x["delta"] is None, x["delta"] or 0)):
            if c["delta"] is None:
                print("  %s  %s → %s" % (label(c["car"]), c["old"], c["new"]))
            else:
                arrow = "↓" if c["delta"] < 0 else "↑"
                print("  %s %.1f萬 → %.1f萬（%s%.1f萬）"
                      % (label(c["car"]), c["old"], c["new"], arrow, abs(c["delta"])))
        print()

    if added:
        print("--- 新上架 %d 台 ---" % len(added))
        for v in added:
            print("  %s  %s" % (label(v), v["url"]))
        print()

    if removed:
        print("--- 下架／已售 %d 台 ---" % len(removed))
        for v in removed:
            print("  %s" % label(v))
        print()

    out = {"from": old_day, "to": new_day,
           "n_from": len(old), "n_to": len(new),
           "added": added, "removed": removed, "changed": changed}
    path = os.path.join(DATA_DIR, "diff_%s.json" % new_day)
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
        fh.write(u"\n")
    print("已寫入 %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
