"""全域設定：資金、手續費、路徑、觀察標的。

所有「可調參數」集中在這裡，不要散到各模組去。
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # .../CX5/stock
DB_PATH = Path(os.environ.get("CX5_STOCK_DB", ROOT / "db" / "portfolio.db"))
SITE_DIR = ROOT                                         # index.html 直接放 stock/ 底下
                                                        # → https://aaasdream.github.io/CX5/stock/

# ── 帳戶 ────────────────────────────────────────────────────────────
INITIAL_CASH = 500_000.0      # 新台幣
BASE_CURRENCY = "TWD"
START_DATE = "2026-08-20"     # 實驗起始日

# ── 台股交易成本（現股）──────────────────────────────────────────────
# 券商手續費 0.1425%，電子下單折扣後常見 6 折；單筆最低 20 元。
# 賣出另課證券交易稅 0.3%（現股；當沖減半為 0.15%，本帳本不做當沖）。
FEE_RATE = 0.001425
FEE_DISCOUNT = 0.6            # 六折
FEE_MIN = 20.0                # 單筆最低手續費（元）
TAX_RATE_SELL = 0.003         # 證交稅，只在賣出課徵
LOT_SIZE = 1000               # 一張 = 1000 股（允許零股，但預設以張為單位思考）

# ── 風控（自主交易時的自我約束）────────────────────────────────────
MAX_POSITION_PCT = 0.25       # 單一個股上限：總資產的 25%
MAX_NEW_BUY_PCT = 0.15        # 單日單筆新進場上限：總資產的 15%
MIN_CASH_PCT = 0.10           # 現金水位下限：總資產的 10%

# ── 每日要抓的總經/情緒指標（yfinance ticker → 顯示名）──────────────
MACRO_SERIES = {
    "^TWII":   "台灣加權指數",
    "^SOX":    "費城半導體",
    "^IXIC":   "那斯達克",
    "^GSPC":   "標普500",
    "^VIX":    "VIX 恐慌指數",
    "TWD=X":   "美元兌台幣",
    "DX-Y.NYB": "美元指數",
    "^TNX":    "美債10年殖利率",
    "BZ=F":    "布蘭特原油",
    "GC=F":    "黃金",
    "BTC-USD": "比特幣",
    "NVDA":    "NVIDIA",
}

# ── 常態觀察清單（台股）─────────────────────────────────────────────
# 只是「每天會撈價量進資料庫」的名單，不代表要買。
WATCHLIST = {
    "2330": "台積電",
    "2317": "鴻海",
    "2454": "聯發科",
    "2382": "廣達",
    "3231": "緯創",
    "2376": "技嘉",
    "6669": "緯穎",
    "3661": "世芯-KY",
    "3037": "欣興",
    "2308": "台達電",
    "2891": "中信金",
    "0050": "元大台灣50",
    "00878": "國泰永續高股息",
}

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"


def finmind_tokens() -> list[str]:
    """回傳可用的 FinMind token（支援多把輪替）。"""
    multi = os.environ.get("FINMIND_TOKENS", "").strip()
    if multi:
        return [t.strip() for t in multi.split(",") if t.strip()]
    single = os.environ.get("FINMIND_TOKEN", "").strip()
    return [single] if single else []
