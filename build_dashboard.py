#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""產生 dashboard.html / index.html。

資料來源：
    data/history.json         每日全站統計（parse.py 產出）
    data/targets_<date>.json  每日目標車源清單（analyze.py 產出）

網頁以「目標車源」為主，全站行情只當背景參考。
用法：python build_dashboard.py
"""

import glob
import io
import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")
OUT_PATH = os.path.join(BASE_DIR, "dashboard.html")
# GitHub Pages 以 index.html 為進入點，內容相同
INDEX_PATH = os.path.join(BASE_DIR, "index.html")

HTML_TEMPLATE = u"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CX-5 目標車源監控</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0a0a0f; --panel: #14141c; --border: #24242f;
    --text: #e6e6ee; --muted: #8b8b9e;
    --orange: #ff9f40; --red: #ff4d5e; --green: #4ade80; --blue: #60a5fa;
  }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 20px; background: var(--bg); color: var(--text);
         font-family: "Segoe UI", "Microsoft JhengHei", system-ui, sans-serif; }
  h1 { font-size: 19px; margin: 0 0 4px; }
  h2 { font-size: 14px; margin: 0 0 12px; color: var(--muted);
       font-weight: 500; letter-spacing: .5px; }
  .sub { color: var(--muted); font-size: 12.5px; margin-bottom: 18px; }
  .sub code { color: var(--orange); background: #1c1c27;
              padding: 1px 6px; border-radius: 4px; }
  .cards { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 18px; }
  .card { background: var(--panel); border: 1px solid var(--border);
          border-radius: 10px; padding: 11px 15px; min-width: 118px; flex: 1 1 118px; }
  .card .label { color: var(--muted); font-size: 11px; }
  .card .value { font-size: 21px; font-weight: 600; margin-top: 3px; }
  .card .value.hi { color: var(--green); }
  .panel { background: var(--panel); border: 1px solid var(--border);
           border-radius: 12px; padding: 16px; margin-bottom: 18px; }
  .chart-wrap { position: relative; height: 300px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 8px 9px; text-align: right; border-bottom: 1px solid var(--border);
           white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; font-size: 11.5px; }
  th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
  tbody tr:hover { background: #1c1c27; }
  .tbl-wrap { overflow-x: auto; }
  a { color: var(--blue); text-decoration: none; }
  a:hover { text-decoration: underline; }
  .home { color: var(--green); font-weight: 600; }
  .badge { display: inline-block; font-size: 10.5px; padding: 1px 6px;
           border-radius: 4px; background: #14301f; color: var(--green);
           border: 1px solid #1e5236; margin-left: 6px; }
  .cheap { color: var(--green); font-weight: 600; }
  .warn { border-color: #4a2230; }
  .warn h2 { color: var(--red); }
  .warn td { color: #b9808c; }
  .empty { color: var(--muted); padding: 34px 0; text-align: center; }
  .foot { color: var(--muted); font-size: 11.5px; margin-top: 14px; line-height: 1.6; }
</style>
</head>
<body>
<h1>CX-5 目標車源監控</h1>
<div class="sub">條件：<code>__CRITERIA__</code> &middot; 最後更新 __DATE__ &middot;
  當日掃描 __NSCAN__ 台在售車</div>

<div class="cards" id="cards"></div>

<div class="panel">
  <h2>目標車源（依價格排序）</h2>
  <div class="tbl-wrap"><table>
    <thead><tr><th>年式</th><th>等級</th><th>里程</th><th>開價</th><th>地區</th><th>連結</th></tr></thead>
    <tbody id="targets"></tbody>
  </table></div>
  <div class="foot" id="tfoot"></div>
</div>

<div class="panel">
  <h2>目標車價走勢</h2>
  <div class="chart-wrap"><canvas id="chart"></canvas></div>
</div>

<div class="panel warn" id="susPanel" style="display:none">
  <h2>價格可疑 — 不列入行情</h2>
  <div class="tbl-wrap"><table>
    <thead><tr><th>年式</th><th>等級</th><th>里程</th><th>開價</th><th>地區</th><th>疑點</th></tr></thead>
    <tbody id="sus"></tbody>
  </table></div>
  <div class="foot">一年內新車卻打骨折價，常見原因：刊登的是頭期款／月付金、釣魚廣告、
    或事故泡水車。看到心動價先確認總價。</div>
</div>

<div class="panel">
  <h2>全站行情（背景參考，含 2013 年起所有車況）</h2>
  <div class="tbl-wrap"><table>
    <thead><tr><th>日期</th><th>在售</th><th>有價</th><th>P25</th><th>中位</th><th>P75</th><th>最低</th><th>最高</th></tr></thead>
    <tbody id="market"></tbody>
  </table></div>
</div>

<script>
const TARGETS = __TARGETS__;      // 最新一日目標清單
const TSERIES = __TSERIES__;      // 每日目標統計
const MARKET  = __MARKET__;       // 每日全站統計
const HOME    = __HOME__;

const wan = v => (v === null || v === undefined) ? '-' : (v / 10000).toFixed(1) + '萬';
const w2  = v => (v === null || v === undefined) ? '-' : v.toFixed(1) + '萬';

// ---- 摘要卡 ----
const homeCars = TARGETS.filter(t => (t.region || '').includes(HOME));
const prices = TARGETS.map(t => t.price_wan).filter(v => v !== null).sort((a, b) => a - b);
const mid = prices.length
  ? (prices.length % 2 ? prices[(prices.length - 1) / 2]
     : (prices[prices.length / 2 - 1] + prices[prices.length / 2]) / 2) : null;
document.getElementById('cards').innerHTML = [
  ['符合條件', TARGETS.length + ' 台', ''],
  [HOME + '在地', homeCars.length + ' 台', homeCars.length ? 'hi' : ''],
  ['最低開價', prices.length ? w2(prices[0]) : '-', 'hi'],
  ['行情中位', w2(mid), ''],
  ['行情帶', prices.length ? w2(prices[0]) + ' ~ ' + w2(prices[prices.length - 1]) : '-', ''],
].map(c => '<div class="card"><div class="label">' + c[0] +
  '</div><div class="value ' + c[2] + '">' + c[1] + '</div></div>').join('');

// ---- 目標車源表 ----
const lowest = prices.length ? prices[0] : null;
document.getElementById('targets').innerHTML = TARGETS.length ? TARGETS.map(t => {
  const isHome = (t.region || '').includes(HOME);
  const isLow = t.price_wan !== null && t.price_wan === lowest;
  return '<tr>' +
    '<td>' + t.year + '</td>' +
    '<td>' + t.model + (isHome ? '<span class="badge">' + HOME + '</span>' : '') + '</td>' +
    '<td>' + t.mileage_text + '</td>' +
    '<td class="' + (isLow ? 'cheap' : '') + '">' + (t.price_text || '-') + '</td>' +
    '<td class="' + (isHome ? 'home' : '') + '">' + (t.region || '-') + '</td>' +
    '<td><a href="' + t.url + '" target="_blank" rel="noopener">8891 &rarr;</a></td>' +
    '</tr>';
}).join('') : '<tr><td colspan="6" class="empty">今日沒有符合條件的車</td></tr>';

document.getElementById('tfoot').innerHTML = TARGETS.length
  ? '綠色為最低開價。' + HOME + '在地 ' + homeCars.length + ' 台。'
  : '';

// ---- 可疑清單 ----
const SUS = __SUS__;
if (SUS.length) {
  document.getElementById('susPanel').style.display = '';
  document.getElementById('sus').innerHTML = SUS.map(t =>
    '<tr><td>' + t.year + '</td><td>' + t.model + '</td><td>' + t.mileage_text +
    '</td><td>' + t.price_text + '</td><td>' + (t.region || '-') +
    '</td><td>' + t.why + '</td></tr>').join('');
}

// ---- 走勢圖 ----
if (!TSERIES.length) {
  document.querySelector('.chart-wrap').innerHTML =
    '<div class="empty">尚無資料</div>';
} else {
  new Chart(document.getElementById('chart'), {
    type: 'line',
    data: {
      labels: TSERIES.map(r => r.date),
      datasets: [
        { label: '目標最高', data: TSERIES.map(r => r.max),
          borderColor: 'rgba(255,159,64,.3)', backgroundColor: 'rgba(255,159,64,.10)',
          borderWidth: 1, pointRadius: 0, tension: .25, fill: false },
        { label: '目標最低', data: TSERIES.map(r => r.min),
          borderColor: 'rgba(255,77,94,.6)', backgroundColor: 'rgba(255,159,64,.10)',
          borderWidth: 1.5, pointRadius: 4, pointBackgroundColor: '#ff4d5e',
          tension: .25, fill: '-1' },
        { label: '目標中位', data: TSERIES.map(r => r.median),
          borderColor: '#ff9f40', backgroundColor: '#ff9f40',
          borderWidth: 2.5, pointRadius: 4, tension: .25, fill: false },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: '#e6e6ee', usePointStyle: true, boxWidth: 8 } },
        tooltip: { backgroundColor: '#14141c', borderColor: '#24242f', borderWidth: 1,
          titleColor: '#e6e6ee', bodyColor: '#e6e6ee',
          callbacks: { label: c => c.dataset.label + '： ' + w2(c.parsed.y) } },
      },
      scales: {
        x: { ticks: { color: '#8b8b9e' }, grid: { color: '#1e1e28' } },
        y: { ticks: { color: '#8b8b9e', callback: v => v + '萬' },
             grid: { color: '#1e1e28' } },
      },
    },
  });
}

// ---- 全站行情表 ----
document.getElementById('market').innerHTML = MARKET.slice().reverse().map(r =>
  '<tr><td>' + r.date + '</td><td>' + r.n + '</td><td>' + r.n_priced + '</td><td>' +
  wan(r.p25) + '</td><td>' + wan(r.median) + '</td><td>' + wan(r.p75) + '</td><td>' +
  wan(r.min_priced) + '</td><td>' + wan(r.max_priced) + '</td></tr>').join('');
</script>
</body>
</html>
"""


def price_wan(text):
    m = re.match(r"^([0-9.]+)萬$", text or "")
    return float(m.group(1)) if m else None


def load_market():
    if not os.path.exists(HISTORY_PATH):
        return []
    data = json.load(io.open(HISTORY_PATH, encoding="utf-8"))
    records = data.get("records", {}) if isinstance(data, dict) else {}
    out = []
    for date in sorted(records):
        rec = dict(records[date])
        rec["date"] = date
        out.append(rec)
    return out


def load_targets():
    """回傳 (最新一日清單, 每日統計序列, 可疑清單, meta)。"""
    files = sorted(glob.glob(os.path.join(DATA_DIR, "targets_*.json")))
    series, latest, sus, meta = [], [], [], {}
    for path in files:
        try:
            d = json.load(io.open(path, encoding="utf-8"))
        except ValueError:
            continue
        rows = []
        for t in d.get("targets", []):
            t = dict(t)
            t["price_wan"] = price_wan(t.get("price_text"))
            rows.append(t)
        prices = sorted(p for p in (r["price_wan"] for r in rows) if p is not None)
        if prices:
            n = len(prices)
            median = prices[n // 2] if n % 2 else (prices[n // 2 - 1] + prices[n // 2]) / 2.0
            series.append({"date": d.get("date", ""), "n": len(rows),
                           "min": prices[0], "median": median, "max": prices[-1]})
        latest = rows
        sus = d.get("suspicious", [])
        meta = d
    return latest, series, sus, meta


def main():
    market = load_market()
    targets, series, sus, meta = load_targets()

    html = HTML_TEMPLATE
    for key, value in [
        ("__TARGETS__", json.dumps(targets, ensure_ascii=False)),
        ("__TSERIES__", json.dumps(series, ensure_ascii=False)),
        ("__MARKET__", json.dumps(market, ensure_ascii=False)),
        ("__SUS__", json.dumps(sus, ensure_ascii=False)),
        ("__HOME__", json.dumps(meta.get("home_region", "高雄"), ensure_ascii=False)),
        ("__CRITERIA__", meta.get("criteria", "尚未執行 analyze.py")),
        ("__DATE__", meta.get("date", market[-1]["date"] if market else "-")),
        ("__NSCAN__", str(meta.get("n_scanned", market[-1]["n"] if market else 0))),
    ]:
        html = html.replace(key, value)

    for path in (OUT_PATH, INDEX_PATH):
        io.open(path, "w", encoding="utf-8").write(html)
    print("已產生 dashboard.html 與 index.html（目標 %d 台 / 走勢 %d 天 / 全站 %d 天）"
          % (len(targets), len(series), len(market)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
