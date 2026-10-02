import csv
import inspect
import io
import tempfile
import unittest
from unittest import mock
from argparse import Namespace
from contextlib import redirect_stdout
from decimal import Decimal
from pathlib import Path

import growthledger as gl


HEADERS = [
    "datetime", "date", "account_type", "category", "type", "asset_class", "name",
    "symbol", "shares", "price", "amount", "fee", "tax", "currency", "original_amount",
    "original_currency", "fx_rate", "description", "transaction_id", "counterparty_name",
    "counterparty_iban", "payment_reference", "mcc_code",
]


def tr_row(**overrides):
    row = {key: "" for key in HEADERS}
    row.update({
        "datetime": "2026-01-02T10:00:00+00:00", "date": "2026-01-02",
        "category": "TRADING", "type": "BUY", "asset_class": "FUND",
        "name": "Test World ETF", "symbol": "IE00B4L5Y983", "shares": "0.1917700000",
        "price": "130.3639000000", "fee": "0", "tax": "0", "currency": "EUR",
        "description": "BUY IE00B4L5Y983", "transaction_id": "buy-001",
    })
    row.update(overrides)
    return row


def write_csv(path, rows, headers=HEADERS, bom=False):
    encoding = "utf-8-sig" if bom else "utf-8"
    with path.open("w", encoding=encoding, newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def tx(identifier, kind, *, shares=None, amount=None, buy=None, sell=None, market=None,
       fee=Decimal("0"), tax=Decimal("0"), date="2026-01-01", symbol="ETF"):
    return gl.Transaction(
        identifier, date=date, transaction_type=kind, shares=shares, amount=amount,
        buy_price=buy, sell_price=sell, market_price=market, fee=fee, tax=tax,
        symbol=symbol, source="manual", price_source="manual",
    )


class DecimalAndModelTests(unittest.TestCase):
    def test_manual_shares_calculated_with_decimal(self):
        args = Namespace(
            date="2026-01-01", transaction_type="etf_buy", amount="25", buy_price="130.3639",
            sell_price=None, market_price="132", shares=None, fee="0", tax="0", name="ETF",
            identifier="IE00B4L5Y983", currency="EUR", description=None, transaction_id="manual-1",
        )
        item = gl.make_manual_transaction(args, interactive=False)
        self.assertEqual(item.shares, Decimal("25") / Decimal("130.3639"))
        self.assertEqual(item.price_source, "manual")
        self.assertEqual(item.amount_source, "manual")

    def test_imported_actual_shares_have_priority(self):
        item = gl.transaction_from_trade_republic(tr_row(amount="25"))
        self.assertEqual(item.shares, Decimal("0.1917700000"))
        self.assertNotEqual(item.shares, item.amount / item.buy_price)

    def test_empty_fields_are_safe(self):
        item = gl.transaction_from_trade_republic(tr_row(amount="", fee="", tax=""))
        self.assertEqual(item.amount, Decimal("0.1917700000") * Decimal("130.3639000000"))
        self.assertEqual(item.fee, Decimal("0"))
        self.assertEqual(item.tax, Decimal("0"))

    def test_amount_is_calculated_and_marked(self):
        item = gl.transaction_from_trade_republic(tr_row(amount=""))
        self.assertEqual(item.amount_source, "calculated")
        self.assertEqual(item.amount, Decimal("0.1917700000") * Decimal("130.3639000000"))

    def test_manual_amount_is_calculated_from_actual_shares(self):
        args = Namespace(
            date="2026-01-01", transaction_type="etf_buy", amount=None, buy_price="100",
            sell_price=None, market_price=None, shares="0.25", fee="0", tax="0", name="ETF",
            identifier="TEST", currency="EUR", description=None, transaction_id="manual-2",
        )
        item = gl.make_manual_transaction(args, interactive=False)
        self.assertEqual(item.amount, Decimal("25.00"))
        self.assertEqual(item.amount_source, "calculated")

    def test_manual_fee_amount_is_reported_as_fee(self):
        args = Namespace(
            date="2026-01-01", transaction_type="fee", amount="2.50", buy_price=None,
            sell_price=None, market_price=None, shares=None, fee=None, tax=None, name=None,
            identifier=None, currency="EUR", description=None, transaction_id="manual-fee",
        )
        item = gl.make_manual_transaction(args, interactive=False)
        self.assertEqual(item.fee, Decimal("2.50"))
        self.assertEqual(gl.summarize([item]).fees, Decimal("2.50"))

    def test_isin_detection(self):
        self.assertTrue(gl.is_isin("IE00B4L5Y983"))
        self.assertFalse(gl.is_isin("VWCE.DE"))
        self.assertEqual(gl.transaction_from_trade_republic(tr_row()).isin, "IE00B4L5Y983")

    def test_input_validation(self):
        with self.assertRaises(gl.GrowthLedgerError):
            gl.parse_decimal("NaN", "amount")
        with self.assertRaises(gl.GrowthLedgerError):
            gl.validate_date("01.02.2026")
        with self.assertRaises(gl.GrowthLedgerError):
            tx("bad", "etf_buy", shares=Decimal("-1"))
        with self.assertRaises(gl.GrowthLedgerError):
            gl.Transaction("missing-amount", date="2026-01-01", transaction_type="cash_deposit", shares=Decimal("0"))

    def test_price_provider_is_abstract_and_offline(self):
        self.assertTrue(inspect.isabstract(gl.PriceProvider))
        self.assertEqual(set(gl.PriceProvider.__abstractmethods__), {"current_price", "historical_prices"})


class CalculationTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            tx("b1", "etf_buy", shares=Decimal("2"), amount=Decimal("200"), buy=Decimal("100")),
            tx("b2", "etf_buy", shares=Decimal("1"), amount=Decimal("120"), buy=Decimal("120"), market=Decimal("130"), date="2026-02-01"),
            tx("s1", "etf_sell", shares=Decimal("0.5"), amount=Decimal("65"), sell=Decimal("130"), date="2026-03-01"),
            tx("d1", "dividend", amount=Decimal("5"), date="2026-04-01"),
            tx("f1", "fee", amount=Decimal("2"), fee=Decimal("2"), date="2026-04-02"),
            tx("t1", "tax", amount=Decimal("1"), tax=Decimal("1"), date="2026-04-03"),
            tx("dep", "cash_deposit", amount=Decimal("320"), shares=Decimal("0")),
        ]

    def test_holdings_buy_amount_and_weighted_price(self):
        result = gl.summarize(self.items)
        self.assertEqual(result.bought_shares, Decimal("3"))
        self.assertEqual(result.sold_shares, Decimal("0.5"))
        self.assertEqual(result.holdings, Decimal("2.5"))
        self.assertEqual(result.buy_amounts, Decimal("320"))
        self.assertEqual(result.weighted_buy_price, Decimal("320") / Decimal("3"))
        self.assertEqual(result.deposits, Decimal("320"))

    def test_value_profit_loss_and_return(self):
        result = gl.summarize(self.items)
        self.assertEqual(result.portfolio_value, Decimal("325.0"))
        self.assertEqual(result.profit_loss, Decimal("72.0"))
        self.assertEqual(result.return_percent, Decimal("72.0") / Decimal("323") * Decimal("100"))
        self.assertEqual(result.fees, Decimal("2"))
        self.assertEqual(result.taxes, Decimal("1"))
        self.assertEqual(result.dividends, Decimal("5"))

    def test_missing_market_price_never_uses_buy_price(self):
        result = gl.summarize([tx("b", "etf_buy", shares=Decimal("1"), amount=Decimal("100"), buy=Decimal("100"))])
        self.assertIsNone(result.portfolio_value)
        self.assertIsNone(result.profit_loss)


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.storage = gl.CSVStorage(self.root / "data")
        self.file = self.root / "input.csv"

    def tearDown(self):
        self.temp.cleanup()

    def test_cash_buy_sell_dividend_fee_tax_and_unknown(self):
        rows = [
            tr_row(transaction_id="dep", category="CASH", type="CUSTOMER_INPAYMENT", asset_class="", shares="99", price="", amount="25", symbol="", name=""),
            tr_row(transaction_id="buy"),
            tr_row(transaction_id="sell", type="SELL", amount="26"),
            tr_row(transaction_id="div", category="INCOME", type="DIVIDEND", asset_class="", shares="", price="", amount="3"),
            tr_row(transaction_id="fee", category="FEE", type="FEE", asset_class="", shares="", price="", amount="-1.5"),
            tr_row(transaction_id="tax", category="TAX", type="TAX", asset_class="", shares="", price="", amount="-0.5"),
            tr_row(transaction_id="unknown", category="MYSTERY", type="OTHER", asset_class="", shares="", price="", amount=""),
        ]
        write_csv(self.file, rows, bom=True)
        result = gl.import_trade_republic(self.file, self.storage)
        self.assertFalse(result.errors)
        self.assertEqual((result.cash_deposits, result.etf_buys, result.etf_sells), (1, 1, 1))
        self.assertEqual((result.dividends, result.fees, result.taxes, result.unknown), (1, 1, 1, 1))
        loaded = self.storage.load()
        self.assertEqual(loaded[0].shares, Decimal("0"))
        self.assertEqual(loaded[1].price_source, "broker_statement")
        self.assertEqual(loaded[2].sell_price, Decimal("130.3639000000"))
        self.assertEqual(loaded[4].fee, Decimal("1.5"))
        self.assertEqual(loaded[5].tax, Decimal("0.5"))
        self.assertEqual(loaded[6].transaction_type, "unknown")
        stored_header = self.storage.path.read_text(encoding="utf-8").splitlines()[0]
        self.assertNotIn("counterparty_name", stored_header)
        self.assertNotIn("counterparty_iban", stored_header)

    def test_duplicate_detection_and_skip(self):
        write_csv(self.file, [tr_row()])
        self.assertEqual(gl.import_trade_republic(self.file, self.storage).imported, 1)
        rejected = gl.import_trade_republic(self.file, self.storage)
        self.assertTrue(rejected.errors)
        self.assertEqual(len(self.storage.load()), 1)
        skipped = gl.import_trade_republic(self.file, self.storage, skip_duplicates=True)
        self.assertFalse(skipped.errors)
        self.assertEqual(skipped.duplicates, 1)
        self.assertEqual(len(self.storage.load()), 1)

    def test_preview_and_dry_run_do_not_write(self):
        write_csv(self.file, [tr_row()])
        preview = gl.import_trade_republic(self.file, self.storage, preview=True)
        self.assertEqual(preview.imported, 1)
        self.assertEqual(self.storage.load(), [])
        dry = gl.import_trade_republic(self.file, self.storage, dry_run=True)
        self.assertEqual(dry.imported, 1)
        self.assertEqual(self.storage.load(), [])

    def test_invalid_row_preserves_existing_data(self):
        self.storage.save([tx("existing", "cash_deposit", amount=Decimal("10"), shares=Decimal("0"))])
        write_csv(self.file, [tr_row(transaction_id="valid"), tr_row(transaction_id="broken", date="not-a-date")])
        result = gl.import_trade_republic(self.file, self.storage)
        self.assertTrue(result.errors)
        self.assertEqual([item.transaction_id for item in self.storage.load()], ["existing"])

    def test_missing_required_columns(self):
        write_csv(self.file, [{"date": "2026-01-01"}], headers=["date"])
        with self.assertRaises(gl.GrowthLedgerError):
            gl.import_trade_republic(self.file, self.storage)


class StorageForecastExportAndCliTests(unittest.TestCase):
    def test_csv_round_trip_and_duplicate_save_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = gl.CSVStorage(Path(directory) / "nested" / "data")
            original = tx("x", "etf_buy", shares=Decimal("0.123456789"), amount=Decimal("12.3456789"), buy=Decimal("100.0000001"))
            storage.save([original])
            loaded = storage.load()[0]
            self.assertEqual(loaded.shares, original.shares)
            self.assertEqual(loaded.buy_price, original.buy_price)
            self.assertTrue(storage.config_path.exists())
            with self.assertRaises(gl.GrowthLedgerError):
                storage.save([original, original])

    def test_forecast_one_and_multiple_scenarios(self):
        one = gl.forecast(Decimal("25"), 1, Decimal("0"), Decimal("100"))
        self.assertEqual(one.final_value, Decimal("400"))
        self.assertEqual(one.total_contributions, Decimal("300"))
        self.assertEqual(one.years[0].contributions, Decimal("300"))
        self.assertEqual(one.growth, Decimal("0"))
        scenarios = [gl.forecast(Decimal("25"), 2, rate) for rate in (Decimal("3"), Decimal("5"), Decimal("7"))]
        self.assertEqual(len(scenarios), 3)
        self.assertLess(scenarios[0].final_value, scenarios[1].final_value)
        self.assertLess(scenarios[1].final_value, scenarios[2].final_value)

    def test_export_is_bom_semicolon_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "export" / "ledger.csv"
            gl.export_csv([tx("x", "cash_deposit", amount=Decimal("25"), shares=Decimal("0"))], output)
            content = output.read_bytes()
            self.assertTrue(content.startswith(b"\xef\xbb\xbf"))
            self.assertIn(b";", content)

    def test_cli_help_and_sample_data_are_repeat_safe(self):
        with self.assertRaises(SystemExit) as caught, redirect_stdout(io.StringIO()):
            gl.main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            self.assertEqual(gl.main(["--data-dir", directory, "sample-data"]), 0)
            self.assertEqual(len(gl.CSVStorage(directory).load()), 2)
            self.assertEqual(gl.main(["--data-dir", directory, "sample-data"]), 2)


class PhaseTwoTests(unittest.TestCase):
    def test_alpha_vantage_parsing(self):
        provider = gl.AlphaVantageProvider("secret", "EUR")
        with mock.patch("growthledger.fetch_json", return_value={"Global Quote": {"05. price": "123.4567", "07. latest trading day": "2026-10-01"}}):
            quote = provider.current_price("ETF.DEX")
        self.assertEqual(quote.price, Decimal("123.4567"))
        self.assertEqual(quote.price_date, "2026-10-01")
        with mock.patch("growthledger.fetch_json", return_value={"Time Series (Daily)": {
            "2026-09-30": {"4. close": "120.1"}, "2026-10-01": {"4. close": "123.4567"}}}):
            history = provider.historical_prices("ETF.DEX", "2026-09-01", "2026-10-01")
        self.assertEqual([item.price for item in history], [Decimal("120.1"), Decimal("123.4567")])
        with mock.patch("growthledger.fetch_json", return_value={"Monthly Time Series": {
            "2021-10-29": {"4. close": "70"}, "2026-09-30": {"4. close": "120"}}}) as fetch:
            long_history = provider.historical_prices("ETF.DEX", "2021-10-01", "2026-10-01")
        self.assertEqual([item.price for item in long_history], [Decimal("70"), Decimal("120")])
        self.assertIn("TIME_SERIES_MONTHLY", fetch.call_args.args[0])

    def test_twelve_data_parsing_and_api_error(self):
        provider = gl.TwelveDataProvider("secret", "EUR")
        payload = {"meta": {"currency": "EUR"}, "values": [{"datetime": "2026-10-01", "close": "99.5"}]}
        with mock.patch("growthledger.fetch_json", return_value=payload):
            self.assertEqual(provider.current_price("ETF").price, Decimal("99.5"))
        with mock.patch("growthledger.fetch_json", return_value={"status": "error", "code": 401}):
            with self.assertRaises(gl.GrowthLedgerError):
                provider.current_price("ETF")

    def test_month_end_cache_sync_and_historical_return(self):
        quotes = [
            gl.PriceQuote("ETF", Decimal("100"), "EUR", "2025-01-02", "2025-01-02T12:00:00+00:00", "test"),
            gl.PriceQuote("ETF", Decimal("101"), "EUR", "2025-01-31", "2025-01-31T12:00:00+00:00", "test"),
            gl.PriceQuote("ETF", Decimal("110"), "EUR", "2026-01-31", "2026-01-31T12:00:00+00:00", "test"),
        ]
        self.assertEqual([item.price_date for item in gl.month_end_quotes(quotes)], ["2025-01-31", "2026-01-31"])
        with tempfile.TemporaryDirectory() as directory:
            storage = gl.CSVStorage(Path(directory) / "data")
            purchase = tx("buy", "etf_buy", shares=Decimal("1"), amount=Decimal("100"), buy=Decimal("100"), symbol="ETF")
            storage.save([purchase])
            self.assertEqual(gl.sync_market_prices(storage, quotes, "ETF.API", "ETF"), 3)
            loaded = storage.load()
            self.assertEqual(next(item for item in loaded if item.transaction_id == "buy").buy_price, Decimal("100"))
            self.assertEqual(gl.summarize(loaded).portfolio_value, Decimal("110"))
            annual = gl.historical_annual_return(loaded)
            self.assertIsNotNone(annual)
            self.assertGreater(annual, Decimal("9"))
            self.assertLess(annual, Decimal("11"))
            self.assertEqual(gl.sync_market_prices(storage, quotes, "ETF.API", "ETF"), 3)
            self.assertEqual(len(storage.load()), 4)

    def test_missing_api_keys_are_rejected(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(gl.GrowthLedgerError):
                gl.make_price_provider("alpha_vantage", "EUR", Path("unused"), False)

    def test_chart_comparison_and_automatic_forecast_return(self):
        quotes = [
            gl.PriceQuote("ETF", Decimal("100"), "EUR", "2025-01-31", "2025-01-31T12:00:00+00:00", "test"),
            gl.PriceQuote("ETF", Decimal("110"), "EUR", "2026-01-31", "2026-01-31T12:00:00+00:00", "test"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            storage = gl.CSVStorage(directory)
            storage.save([tx("buy", "etf_buy", shares=Decimal("1"), amount=Decimal("100"), buy=Decimal("100"), symbol="ETF", date="2025-01-01")])
            gl.sync_market_prices(storage, quotes, "ETF", "ETF")
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(gl.main(["--data-dir", directory, "chart", "--years", "1"]), 0)
                self.assertEqual(gl.main(["--data-dir", directory, "forecast", "--monthly", "25", "--years", "1"]), 0)
            rendered = output.getvalue()
            self.assertIn("Eingezahlter Betrag <-> Eingezahlter Betrag + Kursgewinn", rendered)
            self.assertIn("Historische annualisierte Kurssteigerung", rendered)
            self.assertIn("Szenarienvergleich", rendered)
            self.assertIn("künftig 25,00 EUR pro Monat", rendered)
            self.assertIn("Einzahlungen kum.", rendered)
            self.assertIn("3 %", rendered)
            self.assertIn("5 %", rendered)
            self.assertIn("7 %", rendered)


if __name__ == "__main__":
    unittest.main()
