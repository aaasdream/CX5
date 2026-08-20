from __future__ import annotations

import datetime as dt
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stock.paper import db, fees, journal, ledger, market


class ContestRulesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.init(Path(self.tmp.name) / "test.db", initial_cash=500_000)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_fee_rounding_and_minimum(self):
        self.assertEqual(fees.compute("BUY", 10, 1).fee, 20)
        result = fees.compute("SELL", 100, 1000)
        self.assertEqual(result.fee, 85)
        self.assertEqual(result.tax, 300)

    def test_after_hours_trade_is_rejected_and_not_written(self):
        closed = dt.datetime(2026, 8, 21, 14, 0)
        with self.assertRaises(market.MarketClosed):
            ledger.buy(self.conn, "2330", 10, "測試", now=closed)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 0)

    def test_live_quote_is_the_only_fill_mode(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO trades(date,filled_at,code,name,side,shares,price,fill_mode,"
                "price_source,gross,fee,tax,net,cash_after,reason) "
                "VALUES ('2026-08-21','2026-08-21 10:00:00','2330','台積電','BUY',10,1000,"
                "'CLOSE_LATE','非法補單',10000,20,0,10020,489980,'測試')")

    def test_daily_brief_cannot_be_overwritten(self):
        journal.set_brief(self.conn, "2026-08-21", stance="中性")
        with self.assertRaises(ValueError):
            journal.set_brief(self.conn, "2026-08-21", stance="事後改寫")

    def test_thesis_change_has_append_only_revision(self):
        tid = journal.add_thesis(self.conn, "2330", "2026-08-21", "原始論點", "原始理由")
        journal.update_thesis(self.conn, tid, "2026-08-22", target_price=1100)
        row = self.conn.execute(
            "SELECT * FROM thesis_revisions WHERE thesis_id=?", (tid,)).fetchone()
        self.assertEqual(row["field"], "target_price")
        self.assertIsNone(row["old_value"])
        self.assertEqual(row["new_value"], "1100")

    @patch("stock.paper.market.realtime")
    def test_live_buy_records_timestamp_and_source(self, realtime):
        realtime.return_value = {"price": 1000.0, "name": "台積電",
                                 "time": "2026-08-21 10:01:02", "open": 990,
                                 "high": 1005, "low": 985, "volume": 1000}
        now = dt.datetime(2026, 8, 21, 10, 1, 2)
        fill = ledger.buy(self.conn, "2330", 10, "測試", now=now)
        row = self.conn.execute("SELECT * FROM trades WHERE id=?", (fill["trade_id"],)).fetchone()
        self.assertEqual(row["fill_mode"], "LIVE")
        self.assertEqual(row["price"], 1000.0)
        self.assertEqual(row["filled_at"], "2026-08-21 10:01:02")
        self.assertIn("證交所即時成交價", row["price_source"])


if __name__ == "__main__":
    unittest.main()
