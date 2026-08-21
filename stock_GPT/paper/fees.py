"""台股現股交易成本計算。

規則（本帳本採用的版本，與多數券商電子下單一致）：
  手續費 = 成交金額 × 0.1425% × 折扣，**無條件捨去到整數元**，未滿 20 元以 20 元計
  證交稅 = 成交金額 × 0.3%，**無條件捨去到整數元**，只在賣出課徵

捨去而非四捨五入是刻意的：各券商實作略有差異，
低估成本會讓紙上績效比真實情況好看，所以一律取對帳本不利的那邊。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import config


@dataclass(frozen=True)
class Costs:
    """一筆成交的金額拆解。"""
    gross: float        # 成交價金 = 價格 × 股數
    fee: float          # 券商手續費
    tax: float          # 證交稅（買進為 0）
    net: float          # 買進：實際付出現金；賣出：實際收到現金

    @property
    def total_cost(self) -> float:
        """交易摩擦總額。"""
        return self.fee + self.tax


def brokerage_fee(gross: float,
                  rate: float = config.FEE_RATE,
                  discount: float = config.FEE_DISCOUNT,
                  minimum: float = config.FEE_MIN) -> float:
    """券商手續費：捨去到元，未滿低消以低消計。"""
    fee = math.floor(gross * rate * discount)
    return float(max(fee, minimum))


def sell_tax(gross: float, rate: float = config.TAX_RATE_SELL) -> float:
    """證交稅：捨去到元。"""
    return float(math.floor(gross * rate))


def compute(side: str, price: float, shares: int, **kw) -> Costs:
    """算出一筆買/賣的完整金額拆解。

    side: "BUY" | "SELL"
    """
    side = side.upper()
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side 必須是 BUY 或 SELL，收到 {side!r}")
    if shares <= 0:
        raise ValueError(f"股數必須為正整數，收到 {shares}")
    if price <= 0:
        raise ValueError(f"價格必須為正數，收到 {price}")

    gross = price * shares
    fee = brokerage_fee(gross, **kw)
    if side == "BUY":
        return Costs(gross=gross, fee=fee, tax=0.0, net=gross + fee)
    tax = sell_tax(gross)
    return Costs(gross=gross, fee=fee, tax=tax, net=gross - fee - tax)


def breakeven_price(avg_cost_per_share: float, shares: int) -> float:
    """持有成本對應的損益兩平賣出價（含賣出時的手續費與證交稅）。

    賣出淨收 = P×n − floor(P×n×r×d) − floor(P×n×tax)，要 ≥ 成本。
    直接解析解會被 floor 弄髒，用單調性做二分搜尋即可。
    """
    cost = avg_cost_per_share * shares
    lo, hi = avg_cost_per_share, avg_cost_per_share * 1.2
    for _ in range(60):
        mid = (lo + hi) / 2
        if compute("SELL", mid, shares).net >= cost:
            hi = mid
        else:
            lo = mid
    return hi
