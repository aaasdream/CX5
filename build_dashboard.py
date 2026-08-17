#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""讀取 data/history.json，產生 dashboard.html。

用法：python build_dashboard.py
"""

import json
import os
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
<title>CX-5 中古車價格監控</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0a0a0f;
    --panel: #14141c;
    --border: #24242f;
    --text: #e6e6ee;
    --muted: #8b8b9e;
    --orange: #ff9f40;
    --red: #ff4d5e;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 24px;
    background: var(--bg); color: var(--text);
    font-family: "Segoe UI", "Microsoft JhengHei", system-ui, sans-serif;
  }
  h1 { font-size: 20px; margin: 0 0 4px; letter-spacing: .5px; }
  .sub { color: var(--muted); font-size: 13px; margin-bottom: 20px; }
  .cards { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 20px; }
  .card {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 12px 16px; min-width: 130px;
  }
  .card .label { color: var(--muted); font-size: 11px; letter-spacing: .8px; }
  .card .value { font-size: 22px; font-weight: 600; margin-top: 4px; }
  .panel {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 12px; padding: 16px; margin-bottom: 20px;
  }
  .chart-wrap { position: relative; height: 420px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 8px 10px; text-align: right; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 500; font-size: 12px;
       position: sticky; top: 0; background: var(--panel); }
  th:first-child, td:first-child { text-align: left; }
  tbody tr:hover { background: #1c1c27; }
  .tbl-wrap { max-height: 480px; overflow: auto; }
  .ok { color: #4ade80; }
  .bad { color: var(--red); }
  .empty { color: var(--muted); padding: 40px 0; text-align: center; }
</style>
</head>
<body>
<h1>CX-5 中古車價格監控</h1>
<div class="sub">資料來源：8891 每日抓取 &middot; 共 __DAYS__ 天紀錄</div>

<div class="cards" id="cards"></div>

<div class="panel">
  <div class="chart-wrap"><canvas id="chart"></canvas></div>
</div>

<div class="panel">
  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th>日期</th><th>在售</th><th>有價</th><th>P25</th><th>中位</th>
          <th>P75</th><th>最低</th><th>最高</th><th>完整</th>
        </tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>
</div>

<script>
const RECORDS = __DATA__;

const wan = v => (v === null || v === undefined) ? '-' : (v / 10000).toFixed(1) + '萬';
const labels = RECORDS.map(r => r.date);

if (!RECORDS.length) {
  document.querySelector('.chart-wrap').innerHTML =
    '<div class="empty">尚無資料，請先執行 parse.py</div>';
} else {
  const last = RECORDS[RECORDS.length - 1];
  const cards = [
    ['最新日期', last.date],
    ['在售台數', last.n],
    ['中位價', wan(last.median)],
    ['最低有價', wan(last.min_priced)],
    ['P25 / P75', wan(last.p25) + ' / ' + wan(last.p75)],
  ];
  document.getElementById('cards').innerHTML = cards.map(
    c => '<div class="card"><div class="label">' + c[0] +
         '</div><div class="value">' + c[1] + '</div></div>').join('');

  new Chart(document.getElementById('chart'), {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'P25',
          data: RECORDS.map(r => r.p25),
          borderColor: 'rgba(255,159,64,.35)',
          backgroundColor: 'rgba(255,159,64,.12)',
          borderWidth: 1, pointRadius: 0, tension: .25, fill: false,
        },
        {
          label: 'P75',
          data: RECORDS.map(r => r.p75),
          borderColor: 'rgba(255,159,64,.35)',
          backgroundColor: 'rgba(255,159,64,.12)',
          borderWidth: 1, pointRadius: 0, tension: .25, fill: '-1',
        },
        {
          label: '中位價',
          data: RECORDS.map(r => r.median),
          borderColor: '#ff9f40',
          backgroundColor: '#ff9f40',
          borderWidth: 2.5, pointRadius: 3, tension: .25, fill: false,
        },
        {
          label: '最低有價',
          data: RECORDS.map(r => r.min_priced),
          borderColor: 'rgba(255,77,94,.5)',
          backgroundColor: '#ff4d5e',
          borderWidth: 0, showLine: false,
          pointRadius: 4, pointHoverRadius: 6,
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: '#e6e6ee', usePointStyle: true, boxWidth: 8 } },
        tooltip: {
          backgroundColor: '#14141c', borderColor: '#24242f', borderWidth: 1,
          titleColor: '#e6e6ee', bodyColor: '#e6e6ee',
          callbacks: { label: c => c.dataset.label + '： ' + wan(c.parsed.y) },
        },
      },
      scales: {
        x: { ticks: { color: '#8b8b9e' }, grid: { color: '#1e1e28' } },
        y: {
          ticks: { color: '#8b8b9e', callback: v => (v / 10000).toFixed(0) + '萬' },
          grid: { color: '#1e1e28' },
        },
      },
    },
  });
}

document.getElementById('tbody').innerHTML = RECORDS.slice().reverse().map(r =>
  '<tr>' +
  '<td>' + r.date + '</td>' +
  '<td>' + r.n + '</td>' +
  '<td>' + r.n_priced + '</td>' +
  '<td>' + wan(r.p25) + '</td>' +
  '<td>' + wan(r.median) + '</td>' +
  '<td>' + wan(r.p75) + '</td>' +
  '<td>' + wan(r.min_priced) + '</td>' +
  '<td>' + wan(r.max_priced) + '</td>' +
  '<td class="' + (r.complete ? 'ok' : 'bad') + '">' + (r.complete ? '✓' : '✗') + '</td>' +
  '</tr>').join('');
</script>
</body>
</html>
"""


def load_records():
    if not os.path.exists(HISTORY_PATH):
        return []
    with open(HISTORY_PATH, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    records = data.get("records", {}) if isinstance(data, dict) else {}
    out = []
    for date in sorted(records):
        rec = dict(records[date])
        rec["date"] = date
        out.append(rec)
    return out


def main():
    records = load_records()
    html = HTML_TEMPLATE.replace(
        "__DATA__", json.dumps(records, ensure_ascii=False)
    ).replace("__DAYS__", str(len(records)))
    for path in (OUT_PATH, INDEX_PATH):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
    print("已產生 %s 與 index.html（%d 天資料）" % (OUT_PATH, len(records)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
