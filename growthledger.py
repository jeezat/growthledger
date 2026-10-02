#!/usr/bin/env python3
"""GrowthLedger – lokale Verwaltung und Analyse eines ETF-Sparplans (Phase 1)."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import tempfile
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, fields
from datetime import date as Date, datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Sequence


APP_NAME = "GrowthLedger"
DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"
TRANSACTION_TYPES = {
    "cash_deposit", "cash_withdrawal", "etf_buy", "etf_sell",
    "dividend", "fee", "tax", "unknown",
}
ZERO = Decimal("0")
ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")

TRANSACTION_FIELDS = [
    "transaction_id", "datetime", "date", "transaction_type", "category", "type",
    "asset_class", "name", "symbol", "isin", "ticker", "exchange", "shares",
    "buy_price", "sell_price", "market_price", "amount", "amount_source", "fee",
    "tax", "currency", "description", "source", "price_source", "price_date",
    "price_timestamp", "price_capture", "imported_at",
]
DECIMAL_FIELDS = {"shares", "buy_price", "sell_price", "market_price", "amount", "fee", "tax"}


class GrowthLedgerError(Exception):
    """Verständlicher, erwarteter Anwendungsfehler."""


def parse_decimal(value: object, field_name: str, *, allow_empty: bool = True) -> Decimal | None:
    """Parse beliebig genaue Dezimalwerte, optional mit deutschem Dezimalkomma."""
    if value is None or str(value).strip() == "":
        if allow_empty:
            return None
        raise GrowthLedgerError(f"{field_name} darf nicht leer sein.")
    raw = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if "," in raw and "." not in raw:
        raw = raw.replace(",", ".")
    try:
        number = Decimal(raw)
    except InvalidOperation as exc:
        raise GrowthLedgerError(f"Ungültiger Dezimalwert für {field_name}: {value!r}") from exc
    if not number.is_finite():
        raise GrowthLedgerError(f"{field_name} muss eine endliche Zahl sein.")
    return number


def validate_date(value: str) -> str:
    try:
        return Date.fromisoformat(value.strip()).isoformat()
    except (ValueError, AttributeError) as exc:
        raise GrowthLedgerError(f"Ungültiges Datum {value!r}; erwartet wird YYYY-MM-DD.") from exc


def validate_datetime(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GrowthLedgerError(f"Ungültiger ISO-8601-Zeitstempel: {value!r}") from exc
    return parsed.isoformat()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def decimal_text(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value, "f")


def money(value: Decimal | None, currency: str = "EUR") -> str:
    if value is None:
        return "nicht verfügbar"
    return f"{value:,.2f} {currency}".replace(",", "X").replace(".", ",").replace("X", ".")


def number(value: Decimal | None, places: int = 6) -> str:
    if value is None:
        return "–"
    rendered = f"{value:.{places}f}".rstrip("0").rstrip(".")
    return rendered or "0"


def is_isin(value: str) -> bool:
    """Plausibilitätsprüfung inklusive offizieller Luhn-Prüfziffer."""
    candidate = value.strip().upper()
    if not ISIN_RE.fullmatch(candidate):
        return False
    expanded = "".join(str(ord(ch) - 55) if ch.isalpha() else ch for ch in candidate)
    total = 0
    for index, digit in enumerate(reversed(expanded)):
        n = int(digit) * (2 if index % 2 == 1 else 1)
        total += n // 10 + n % 10
    return total % 10 == 0


@dataclass
class Transaction:
    transaction_id: str
    datetime: str = ""
    date: str = ""
    transaction_type: str = "unknown"
    category: str = ""
    type: str = ""
    asset_class: str = ""
    name: str = ""
    symbol: str = ""
    isin: str = ""
    ticker: str = ""
    exchange: str = ""
    shares: Decimal | None = None
    buy_price: Decimal | None = None
    sell_price: Decimal | None = None
    market_price: Decimal | None = None
    amount: Decimal | None = None
    amount_source: str = ""
    fee: Decimal | None = None
    tax: Decimal | None = None
    currency: str = "EUR"
    description: str = ""
    source: str = "manual"
    price_source: str = ""
    price_date: str = ""
    price_timestamp: str = ""
    price_capture: str = "manual"
    imported_at: str = ""

    def __post_init__(self) -> None:
        if not self.transaction_id.strip():
            raise GrowthLedgerError("transaction_id darf nicht leer sein.")
        if self.transaction_type not in TRANSACTION_TYPES:
            raise GrowthLedgerError(f"Unbekannter Transaktionstyp: {self.transaction_type}")
        if self.date:
            self.date = validate_date(self.date)
        if self.datetime:
            self.datetime = validate_datetime(self.datetime)
        if not self.date and self.datetime:
            self.date = self.datetime[:10]
        if not self.date:
            raise GrowthLedgerError("Ein Transaktionsdatum ist erforderlich.")
        self.currency = (self.currency or "EUR").upper()
        for field_name in DECIMAL_FIELDS:
            current = getattr(self, field_name)
            if current is not None and not isinstance(current, Decimal):
                setattr(self, field_name, parse_decimal(current, field_name))
        for field_name in ("shares", "buy_price", "sell_price", "market_price", "fee", "tax"):
            current = getattr(self, field_name)
            if current is not None and current < ZERO:
                raise GrowthLedgerError(f"{field_name} darf nicht negativ sein.")
        if self.transaction_type in {"etf_buy", "etf_sell"} and self.shares is None:
            raise GrowthLedgerError("Für Käufe und Verkäufe ist eine Stückzahl erforderlich.")
        if self.transaction_type in {"etf_buy", "etf_sell"} and self.shares <= ZERO:
            raise GrowthLedgerError("Die Stückzahl eines Kaufs oder Verkaufs muss größer als null sein.")
        if self.transaction_type == "etf_buy" and self.buy_price is None:
            raise GrowthLedgerError("Für einen ETF-Kauf ist der tatsächliche Kaufkurs erforderlich.")
        if self.transaction_type == "etf_sell" and self.sell_price is None:
            raise GrowthLedgerError("Für einen ETF-Verkauf ist der tatsächliche Verkaufskurs erforderlich.")
        if self.transaction_type in {"cash_deposit", "cash_withdrawal", "dividend", "fee", "tax"} and self.amount is None:
            raise GrowthLedgerError(f"Für {self.transaction_type} ist ein Betrag erforderlich.")

    @property
    def asset_key(self) -> str:
        return self.isin or self.symbol or self.ticker or self.name or "(ohne Kennung)"

    def to_row(self) -> dict[str, str]:
        row = asdict(self)
        for key in DECIMAL_FIELDS:
            row[key] = decimal_text(row[key])
        return {key: str(row.get(key, "")) for key in TRANSACTION_FIELDS}

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "Transaction":
        values: dict[str, object] = {}
        valid_names = {field.name for field in fields(cls)}
        for key in valid_names:
            value: object = row.get(key, "")
            if key in DECIMAL_FIELDS:
                value = parse_decimal(value, key)
            values[key] = value
        return cls(**values)


@dataclass(frozen=True)
class PriceQuote:
    symbol: str
    price: Decimal
    currency: str
    price_date: str
    timestamp: str
    source: str


class PriceProvider(ABC):
    """Kursquellen-Vertrag für Phase 2; Phase 1 enthält keine Netzimplementierung."""

    @abstractmethod
    def current_price(self, symbol: str) -> PriceQuote:
        """Liefert künftig einen aktuellen Kurs oder wirft einen verständlichen Fehler."""
        raise NotImplementedError

    @abstractmethod
    def historical_prices(self, symbol: str, start: str, end: str) -> list[PriceQuote]:
        """Liefert künftig historische Kurse für einen Datumsbereich."""
        raise NotImplementedError


# TODO Phase 2: Netzwerk-Provider und lokalen Kurs-Cache separat implementieren.


class CSVStorage:
    """CSV-Persistenz mit atomarem Ersetzen der Zieldatei."""

    def __init__(self, data_dir: Path | str = DEFAULT_DATA_DIR):
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "transactions.csv"
        self.config_path = self.data_dir / "config.json"

    def ensure(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._atomic_write([])
        if not self.config_path.exists():
            config = {"default_currency": "EUR", "ticker": "", "isin": "", "etf_name": "", "exchange": "", "price_provider": "manual"}
            self._atomic_text(self.config_path, json.dumps(config, ensure_ascii=False, indent=2) + "\n")

    def load(self) -> list[Transaction]:
        self.ensure()
        try:
            with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames is None:
                    return []
                return [Transaction.from_row(row) for row in reader]
        except (OSError, csv.Error, GrowthLedgerError) as exc:
            raise GrowthLedgerError(f"Transaktionsdatei konnte nicht gelesen werden: {exc}") from exc

    def save(self, transactions: Sequence[Transaction]) -> None:
        ids = [item.transaction_id for item in transactions]
        if len(ids) != len(set(ids)):
            raise GrowthLedgerError("Speichern abgebrochen: doppelte transaction_id in den Daten.")
        self.ensure()
        self._atomic_write(transactions)

    def append(self, transaction: Transaction) -> None:
        transactions = self.load()
        if transaction.transaction_id in {item.transaction_id for item in transactions}:
            raise GrowthLedgerError(f"Transaktion {transaction.transaction_id} ist bereits vorhanden.")
        transactions.append(transaction)
        self.save(transactions)

    def _atomic_write(self, transactions: Sequence[Transaction]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(prefix=".transactions-", suffix=".tmp", dir=self.data_dir)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=TRANSACTION_FIELDS, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(item.to_row() for item in transactions)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    @staticmethod
    def _atomic_text(path: Path, content: str) -> None:
        descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise


@dataclass
class ImportResult:
    read_rows: int = 0
    imported: int = 0
    duplicates: int = 0
    invalid: int = 0
    unknown: int = 0
    cash_deposits: int = 0
    etf_buys: int = 0
    etf_sells: int = 0
    dividends: int = 0
    fees: int = 0
    taxes: int = 0
    transactions: list[Transaction] | None = None
    errors: list[str] | None = None

    def __post_init__(self) -> None:
        self.transactions = [] if self.transactions is None else self.transactions
        self.errors = [] if self.errors is None else self.errors


def classify_trade_republic(row: dict[str, str]) -> str:
    category = row.get("category", "").strip().upper()
    kind = row.get("type", "").strip().upper()
    asset = row.get("asset_class", "").strip().upper()
    description = row.get("description", "").strip().upper()
    if category == "CASH" and kind in {"CUSTOMER_INPAYMENT", "DEPOSIT", "INPAYMENT", "BANK_TRANSFER_IN"}:
        return "cash_deposit"
    if category == "CASH" and kind in {"CUSTOMER_PAYOUT", "WITHDRAWAL", "OUTPAYMENT", "BANK_TRANSFER_OUT"}:
        return "cash_withdrawal"
    has_security = bool(row.get("symbol", "").strip() or row.get("name", "").strip())
    has_trade_values = bool(row.get("shares", "").strip() and row.get("price", "").strip())
    if category == "TRADING" and kind == "BUY" and asset in {"FUND", "ETF"} and has_security and has_trade_values:
        return "etf_buy"
    if category == "TRADING" and kind == "SELL" and has_security and has_trade_values:
        return "etf_sell"
    if kind in {"DIVIDEND", "DISTRIBUTION", "CASH_DIVIDEND"} or category in {"DIVIDEND", "DISTRIBUTION"}:
        return "dividend"
    if "DIVIDEND" in description or "AUSSCHÜTTUNG" in description or "DIVIDENDE" in description:
        return "dividend"
    if kind in {"FEE", "FEE_CHARGE"} or category == "FEE":
        return "fee"
    if kind in {"TAX", "TAX_CHARGE", "WITHHOLDING_TAX"} or category == "TAX":
        return "tax"
    return "unknown"


def transaction_from_trade_republic(row: dict[str, str], imported_at: str | None = None) -> Transaction:
    transaction_type = classify_trade_republic(row)
    raw_datetime = row.get("datetime", "").strip()
    raw_date = row.get("date", "").strip() or (raw_datetime[:10] if raw_datetime else "")
    tx_id = row.get("transaction_id", "").strip()
    if not tx_id:
        raise GrowthLedgerError("transaction_id fehlt.")
    if not raw_date:
        raise GrowthLedgerError("date und datetime fehlen.")
    shares = parse_decimal(row.get("shares"), "shares")
    price = parse_decimal(row.get("price"), "price")
    amount = parse_decimal(row.get("amount"), "amount")
    fee = parse_decimal(row.get("fee"), "fee") or ZERO
    tax = parse_decimal(row.get("tax"), "tax") or ZERO
    symbol = row.get("symbol", "").strip()
    isin = symbol.upper() if is_isin(symbol) else ""
    amount_source = "csv" if amount is not None else ""
    if transaction_type in {"etf_buy", "etf_sell"} and amount is None:
        if shares is None or price is None:
            raise GrowthLedgerError("Kauf/Verkauf benötigt shares und price.")
        amount = shares * price
        amount_source = "calculated"
    if transaction_type in {"cash_deposit", "cash_withdrawal", "dividend", "fee", "tax"} and amount is None:
        raise GrowthLedgerError(f"{transaction_type} benötigt amount.")
    # Separate Gebühren-/Steuerbuchungen tragen ihren Betrag zugleich in das fachliche Feld ein.
    if transaction_type == "fee" and fee == ZERO and amount is not None:
        fee = abs(amount)
    if transaction_type == "tax" and tax == ZERO and amount is not None:
        tax = abs(amount)
    return Transaction(
        transaction_id=tx_id,
        datetime=raw_datetime,
        date=raw_date,
        transaction_type=transaction_type,
        category=row.get("category", "").strip(),
        type=row.get("type", "").strip(),
        asset_class=row.get("asset_class", "").strip(),
        name=row.get("name", "").strip(),
        symbol=symbol,
        isin=isin,
        shares=ZERO if transaction_type in {"cash_deposit", "cash_withdrawal"} else shares,
        buy_price=price if transaction_type == "etf_buy" else None,
        sell_price=price if transaction_type == "etf_sell" else None,
        amount=amount,
        amount_source=amount_source,
        fee=fee,
        tax=tax,
        currency=row.get("currency", "").strip() or "EUR",
        description=row.get("description", "").strip(),
        source="trade_republic_csv",
        price_source="broker_statement" if transaction_type in {"etf_buy", "etf_sell"} else "",
        price_date=raw_date if transaction_type in {"etf_buy", "etf_sell"} else "",
        price_capture="broker_statement" if transaction_type in {"etf_buy", "etf_sell"} else "",
        imported_at=imported_at or utc_now(),
    )


def import_trade_republic(
    file_path: Path | str,
    storage: CSVStorage,
    *,
    preview: bool = False,
    dry_run: bool = False,
    skip_duplicates: bool = False,
) -> ImportResult:
    """Prüft die gesamte Datei, bevor bei fehlerfreiem Import atomar gespeichert wird."""
    result = ImportResult()
    existing = storage.load()
    known_ids = {item.transaction_id for item in existing}
    seen_ids: set[str] = set()
    required = {"date", "category", "type", "transaction_id"}
    try:
        with Path(file_path).open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = set(reader.fieldnames or [])
            missing = sorted(required - headers)
            if missing:
                raise GrowthLedgerError("Erforderliche CSV-Spalten fehlen: " + ", ".join(missing))
            for line_number, row in enumerate(reader, start=2):
                result.read_rows += 1
                try:
                    transaction = transaction_from_trade_republic(row)
                    duplicate = transaction.transaction_id in known_ids or transaction.transaction_id in seen_ids
                    if duplicate:
                        result.duplicates += 1
                        if not skip_duplicates:
                            result.errors.append(f"Zeile {line_number}: transaction_id ist bereits vorhanden.")
                        continue
                    seen_ids.add(transaction.transaction_id)
                    result.transactions.append(transaction)
                    attr = {
                        "unknown": "unknown", "cash_deposit": "cash_deposits", "etf_buy": "etf_buys",
                        "etf_sell": "etf_sells", "dividend": "dividends", "fee": "fees", "tax": "taxes",
                    }.get(transaction.transaction_type)
                    if attr:
                        setattr(result, attr, getattr(result, attr) + 1)
                except GrowthLedgerError as exc:
                    result.invalid += 1
                    result.errors.append(f"Zeile {line_number}: {exc}")
    except (OSError, csv.Error) as exc:
        raise GrowthLedgerError(f"Importdatei konnte nicht gelesen werden: {exc}") from exc
    if result.errors:
        # Keine Teilimporte: eine ungültige Zeile oder ein nicht erlaubtes Duplikat bricht alles ab.
        result.imported = 0
        return result
    result.imported = len(result.transactions)
    if not preview and not dry_run:
        storage.save([*existing, *result.transactions])
    return result


@dataclass
class PortfolioSummary:
    transaction_count: int
    bought_shares: Decimal
    sold_shares: Decimal
    holdings: Decimal
    buy_amounts: Decimal
    sell_proceeds: Decimal
    weighted_buy_price: Decimal | None
    deposits: Decimal
    withdrawals: Decimal
    fees: Decimal
    taxes: Decimal
    dividends: Decimal
    last_buy_price: Decimal | None
    last_market_price: Decimal | None
    portfolio_value: Decimal | None
    profit_loss: Decimal | None
    return_percent: Decimal | None
    missing_market_assets: tuple[str, ...]


def summarize(transactions: Sequence[Transaction]) -> PortfolioSummary:
    buys = [item for item in transactions if item.transaction_type == "etf_buy"]
    sells = [item for item in transactions if item.transaction_type == "etf_sell"]
    bought_shares = sum((item.shares or ZERO for item in buys), ZERO)
    sold_shares = sum((item.shares or ZERO for item in sells), ZERO)
    buy_amounts = sum((abs(item.amount or ZERO) for item in buys), ZERO)
    sell_proceeds = sum((abs(item.amount or ZERO) for item in sells), ZERO)
    weighted = (sum(((item.shares or ZERO) * (item.buy_price or ZERO) for item in buys), ZERO) / bought_shares) if bought_shares else None
    ordered = sorted(transactions, key=lambda item: (item.date, item.datetime, item.transaction_id))
    last_buy = next((item.buy_price for item in reversed(ordered) if item.transaction_type == "etf_buy" and item.buy_price is not None), None)
    last_market = next((item.market_price for item in reversed(ordered) if item.market_price is not None), None)

    asset_shares: dict[str, Decimal] = {}
    asset_prices: dict[str, Decimal] = {}
    for item in ordered:
        if item.transaction_type == "etf_buy":
            asset_shares[item.asset_key] = asset_shares.get(item.asset_key, ZERO) + (item.shares or ZERO)
        elif item.transaction_type == "etf_sell":
            asset_shares[item.asset_key] = asset_shares.get(item.asset_key, ZERO) - (item.shares or ZERO)
        if item.market_price is not None:
            asset_prices[item.asset_key] = item.market_price
    active_assets = {key: shares for key, shares in asset_shares.items() if shares != ZERO}
    missing = tuple(sorted(key for key in active_assets if key not in asset_prices))
    portfolio_value = None if missing else sum((shares * asset_prices[key] for key, shares in active_assets.items()), ZERO)
    fees = sum((abs(item.fee or ZERO) for item in transactions), ZERO)
    taxes = sum((abs(item.tax or ZERO) for item in transactions), ZERO)
    dividends = sum((abs(item.amount or ZERO) for item in transactions if item.transaction_type == "dividend"), ZERO)
    profit = None if portfolio_value is None else portfolio_value + sell_proceeds + dividends - buy_amounts - fees - taxes
    capital = buy_amounts + fees + taxes
    return_percent = (profit / capital * Decimal("100")) if profit is not None and capital else None
    return PortfolioSummary(
        transaction_count=len(transactions), bought_shares=bought_shares, sold_shares=sold_shares,
        holdings=bought_shares - sold_shares, buy_amounts=buy_amounts, sell_proceeds=sell_proceeds,
        weighted_buy_price=weighted,
        deposits=sum((abs(item.amount or ZERO) for item in transactions if item.transaction_type == "cash_deposit"), ZERO),
        withdrawals=sum((abs(item.amount or ZERO) for item in transactions if item.transaction_type == "cash_withdrawal"), ZERO),
        fees=fees, taxes=taxes, dividends=dividends, last_buy_price=last_buy,
        last_market_price=last_market, portfolio_value=portfolio_value, profit_loss=profit,
        return_percent=return_percent, missing_market_assets=missing,
    )


@dataclass(frozen=True)
class ForecastYear:
    year: int
    contributions: Decimal
    value: Decimal
    growth: Decimal


@dataclass(frozen=True)
class ForecastScenario:
    annual_return: Decimal
    monthly_rate: Decimal
    total_contributions: Decimal
    final_value: Decimal
    growth: Decimal
    years: tuple[ForecastYear, ...]


def forecast(monthly: Decimal, years: int, annual_return: Decimal, start_value: Decimal = ZERO) -> ForecastScenario:
    if monthly < ZERO or start_value < ZERO:
        raise GrowthLedgerError("Monatsrate und Startwert dürfen nicht negativ sein.")
    if years <= 0 or years > 200:
        raise GrowthLedgerError("Laufzeit muss zwischen 1 und 200 Jahren liegen.")
    if annual_return <= Decimal("-100"):
        raise GrowthLedgerError("Die Jahresrendite muss größer als -100 % sein.")
    with localcontext() as context:
        context.prec = 40
        monthly_rate = (Decimal("1") + annual_return / Decimal("100")) ** (Decimal("1") / Decimal("12")) - Decimal("1")
        value = start_value
        rows: list[ForecastYear] = []
        for month_index in range(1, years * 12 + 1):
            value = value * (Decimal("1") + monthly_rate) + monthly  # Einzahlung am Monatsende
            if month_index % 12 == 0:
                paid = start_value + monthly * month_index
                rows.append(ForecastYear(month_index // 12, paid, value, value - paid))
        paid = start_value + monthly * years * 12
        return ForecastScenario(annual_return, monthly_rate, paid, value, value - paid, tuple(rows))


def make_manual_transaction(args: argparse.Namespace, *, interactive: bool = True) -> Transaction:
    def ask(current: object, prompt: str, default: str = "") -> str:
        if current is not None:
            return str(current)
        if not interactive:
            return default
        suffix = f" [{default}]" if default else ""
        entered = input(f"{prompt}{suffix}: ").strip()
        return entered or default

    raw_date = ask(args.date, "Datum (YYYY-MM-DD)", Date.today().isoformat())
    raw_buy = ask(args.buy_price, "Kaufkurs", "")
    raw_sell = ask(args.sell_price, "Verkaufskurs", "")
    raw_type = ask(args.transaction_type, "Typ", "etf_buy" if raw_buy else "cash_deposit")
    if raw_type not in TRANSACTION_TYPES:
        raise GrowthLedgerError("Ungültiger Transaktionstyp. Erlaubt: " + ", ".join(sorted(TRANSACTION_TYPES)))
    raw_amount = ask(args.amount, "Betrag", "")
    raw_shares = ask(args.shares, "Stückzahl", "")
    amount = parse_decimal(raw_amount, "amount")
    buy_price = parse_decimal(raw_buy, "buy_price")
    sell_price = parse_decimal(raw_sell, "sell_price")
    shares = parse_decimal(raw_shares, "shares")
    if shares is None and raw_type == "etf_buy" and amount is not None and buy_price not in {None, ZERO}:
        shares = amount / buy_price
    if shares is None and raw_type == "etf_sell" and amount is not None and sell_price not in {None, ZERO}:
        shares = amount / sell_price
    if raw_type in {"etf_buy", "etf_sell"} and shares is None:
        raise GrowthLedgerError("Stückzahl fehlt und kann nicht aus Betrag und Kurs berechnet werden.")
    if raw_type == "etf_buy" and buy_price is None:
        raise GrowthLedgerError("Für einen ETF-Kauf ist --buy-price erforderlich.")
    if raw_type == "etf_sell" and sell_price is None:
        raise GrowthLedgerError("Für einen ETF-Verkauf ist --sell-price erforderlich.")
    if amount is None and raw_type == "etf_buy":
        amount = shares * buy_price
        amount_source = "calculated"
    elif amount is None and raw_type == "etf_sell":
        amount = shares * sell_price
        amount_source = "calculated"
    else:
        amount_source = "manual" if amount is not None else ""
    identifier = ask(args.identifier, "ISIN oder Symbol", "")
    market_price = parse_decimal(ask(args.market_price, "Markt-/Monatsendkurs", ""), "market_price")
    fee = parse_decimal(ask(args.fee, "Gebühren", "0"), "fee") or ZERO
    tax = parse_decimal(ask(args.tax, "Steuern", "0"), "tax") or ZERO
    if raw_type == "fee" and fee == ZERO and amount is not None:
        fee = abs(amount)
    if raw_type == "tax" and tax == ZERO and amount is not None:
        tax = abs(amount)
    return Transaction(
        transaction_id=args.transaction_id or f"manual-{uuid.uuid4()}",
        date=raw_date,
        transaction_type=raw_type,
        name=ask(args.name, "ETF-Name", ""),
        symbol=identifier,
        isin=identifier.upper() if is_isin(identifier) else "",
        shares=shares,
        buy_price=buy_price,
        sell_price=sell_price,
        market_price=market_price,
        amount=amount,
        amount_source=amount_source,
        fee=fee,
        tax=tax,
        currency=ask(args.currency, "Währung", "EUR"),
        description=args.description or "Manuelle Eingabe",
        source="manual",
        price_source="manual" if any(value is not None for value in (buy_price, sell_price, market_price)) else "",
        price_date=raw_date if market_price is not None else "",
        price_timestamp=utc_now() if market_price is not None else "",
        price_capture="manual",
        imported_at=utc_now(),
    )


def print_import_result(result: ImportResult, *, verbose: bool = False) -> None:
    labels = [
        ("Gelesene Zeilen", result.read_rows), ("Importierte Transaktionen", result.imported),
        ("Übersprungene Duplikate", result.duplicates), ("Ungültige Zeilen", result.invalid),
        ("Unbekannte Transaktionen", result.unknown), ("Kontoeinzahlungen", result.cash_deposits),
        ("ETF-Käufe", result.etf_buys), ("ETF-Verkäufe", result.etf_sells),
        ("Dividenden/Ausschüttungen", result.dividends), ("Gebühren", result.fees), ("Steuern", result.taxes),
    ]
    for label, value in labels:
        print(f"{label}: {value}")
    if verbose:
        for error in result.errors:
            print(f"Fehler: {error}", file=sys.stderr)


def print_transactions(transactions: Sequence[Transaction]) -> None:
    if not transactions:
        print("Keine Transaktionen vorhanden.")
        return
    print(f"{'Datum':10}  {'Typ':16}  {'ETF/Kennung':28}  {'Betrag':14}  {'Stück':12}  {'Kurs':12}  Quelle")
    print("-" * 112)
    for item in sorted(transactions, key=lambda tx: (tx.date, tx.datetime, tx.transaction_id)):
        asset = (item.name or item.isin or item.symbol or "–")[:28]
        price = item.buy_price if item.buy_price is not None else item.sell_price
        print(f"{item.date:10}  {item.transaction_type:16}  {asset:28}  {number(item.amount, 2):>14}  {number(item.shares):>12}  {number(price, 4):>12}  {item.source}")


def print_report(transactions: Sequence[Transaction]) -> None:
    summary = summarize(transactions)
    assets = sorted({(item.name or "–", item.isin or item.symbol or "–") for item in transactions if item.transaction_type in {"etf_buy", "etf_sell"}})
    print(f"GrowthLedger-Bericht ({', '.join(f'{name} / {ident}' for name, ident in assets) or 'kein ETF'})")
    print(f"Transaktionen: {summary.transaction_count}")
    print(f"Kontoeinzahlungen: {money(summary.deposits)}")
    print(f"Kontoauszahlungen: {money(summary.withdrawals)}")
    print(f"ETF-Kaufbeträge: {money(summary.buy_amounts)}")
    print(f"Verkaufserlöse: {money(summary.sell_proceeds)}")
    print(f"Gekaufte / verkaufte Anteile: {number(summary.bought_shares)} / {number(summary.sold_shares)}")
    print(f"Aktueller Anteilbestand: {number(summary.holdings)}")
    print(f"Gewichteter durchschnittlicher Kaufkurs: {money(summary.weighted_buy_price)}")
    print(f"Gebühren / Steuern: {money(summary.fees)} / {money(summary.taxes)}")
    print(f"Dividenden: {money(summary.dividends)}")
    print(f"Letzter Kaufkurs: {money(summary.last_buy_price)}")
    print(f"Letzter Markt-/Monatsendkurs: {money(summary.last_market_price)}")
    if summary.portfolio_value is None:
        print("Depotwert: nicht berechenbar – für aktive Positionen fehlt ein manueller market_price.")
        if summary.missing_market_assets:
            print("Fehlende Marktpreise: " + ", ".join(summary.missing_market_assets))
    else:
        print(f"Depotwert: {money(summary.portfolio_value)}")
        print(f"Vereinfachter Gewinn/Verlust: {money(summary.profit_loss)}")
        print(f"Vereinfachte Rendite: {number(summary.return_percent, 2)} %")
    print("Hinweis: Gesamtbetrachtung ohne steuerliche Loszuordnung; keine Trennung realisierter/unrealisierter Gewinne.")


def print_forecasts(scenarios: Sequence[ForecastScenario]) -> None:
    print("Prognose (Einzahlungen jeweils am Monatsende; unverbindliches Rechenmodell)")
    for scenario in scenarios:
        print(f"\nJahresrendite {number(scenario.annual_return, 2)} % | Einzahlungen {money(scenario.total_contributions)} | Endwert {money(scenario.final_value)} | Wertzuwachs {money(scenario.growth)}")
        print("Jahr  Einzahlungen       Depotwert       Wertzuwachs")
        for row in scenario.years:
            print(f"{row.year:>4}  {money(row.contributions):>16}  {money(row.value):>16}  {money(row.growth):>16}")
    print("\nKeine Finanzberatung oder Garantie. Renditen schwanken; Verluste sind möglich.")


def ascii_chart(title: str, points: Sequence[tuple[str, Decimal]], width: int = 40) -> None:
    print(f"\n{title}")
    if not points:
        print("  Keine Daten verfügbar.")
        return
    maximum = max((abs(value) for _, value in points), default=ZERO)
    for label, value in points:
        size = int(abs(value) / maximum * width) if maximum else 0
        marker = "#" * size
        print(f"{label[:12]:12} | {marker:<{width}} {number(value, 2)}")


def chart_data(transactions: Sequence[Transaction]) -> tuple[list[tuple[str, Decimal]], list[tuple[str, Decimal]]]:
    running_buys = ZERO
    bought: list[tuple[str, Decimal]] = []
    values: list[tuple[str, Decimal]] = []
    holdings: dict[str, Decimal] = {}
    prices: dict[str, Decimal] = {}
    for item in sorted(transactions, key=lambda tx: (tx.date, tx.datetime, tx.transaction_id)):
        if item.transaction_type == "etf_buy":
            running_buys += abs(item.amount or ZERO)
            holdings[item.asset_key] = holdings.get(item.asset_key, ZERO) + (item.shares or ZERO)
            bought.append((item.date, running_buys))
        elif item.transaction_type == "etf_sell":
            holdings[item.asset_key] = holdings.get(item.asset_key, ZERO) - (item.shares or ZERO)
        if item.market_price is not None:
            prices[item.asset_key] = item.market_price
            if all(key in prices for key, shares in holdings.items() if shares != ZERO):
                values.append((item.date, sum((shares * prices[key] for key, shares in holdings.items()), ZERO)))
    return bought, values


EXPORT_FIELDS = [
    ("Datum", "date"), ("Transaktionstyp", "transaction_type"), ("ETF-Name", "name"),
    ("ISIN oder Symbol", "identifier"), ("Stückzahl", "shares"), ("Kaufkurs", "buy_price"),
    ("Verkaufskurs", "sell_price"), ("Marktpreis", "market_price"), ("Betrag", "amount"),
    ("Herkunft des Betrags", "amount_source"), ("Gebühren", "fee"), ("Steuern", "tax"),
    ("Währung", "currency"), ("Datenquelle", "source"), ("Kursquelle", "price_source"),
    ("transaction_id", "transaction_id"),
]


def export_csv(transactions: Sequence[Transaction], output: Path | str) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[label for label, _ in EXPORT_FIELDS], delimiter=";")
            writer.writeheader()
            for item in transactions:
                row: dict[str, str] = {}
                for label, attribute in EXPORT_FIELDS:
                    value: object = item.isin or item.symbol if attribute == "identifier" else getattr(item, attribute)
                    row[label] = decimal_text(value) if isinstance(value, Decimal) else str(value or "")
                writer.writerow(row)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return path


def sample_transactions() -> list[Transaction]:
    return [
        Transaction("sample-deposit-001", date="2025-01-02", transaction_type="cash_deposit", amount=Decimal("100"), amount_source="manual", shares=ZERO, description="ANONYMISIERTE BEISPIELDATEN", source="sample"),
        Transaction("sample-buy-001", date="2025-01-03", transaction_type="etf_buy", asset_class="FUND", name="Beispiel Welt ETF", symbol="SAMPLE", shares=Decimal("1"), buy_price=Decimal("100"), market_price=Decimal("105"), amount=Decimal("100"), amount_source="manual", fee=ZERO, tax=ZERO, description="ANONYMISIERTE BEISPIELDATEN", source="sample", price_source="manual", price_date="2025-01-31", price_capture="manual"),
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GrowthLedger – lokale ETF-Sparplanverwaltung (Phase 1, ohne automatischen Kursabruf)")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="Lokales Datenverzeichnis (Standard: data/ neben dem Programm)")
    sub = parser.add_subparsers(dest="command", required=True)

    importer = sub.add_parser("import-trade-republic", help="Trade-Republic-CSV sicher importieren")
    importer.add_argument("--file", required=True, type=Path, help="CSV-Datei")
    importer.add_argument("--preview", action="store_true", help="Erkannte Datensätze anzeigen, nicht speichern")
    importer.add_argument("--dry-run", action="store_true", help="Gesamten Import prüfen, nicht speichern")
    importer.add_argument("--skip-duplicates", action="store_true", help="Bekannte IDs überspringen")
    importer.add_argument("--verbose", action="store_true", help="Ausführliche Informationen")

    add = sub.add_parser("add", help="Transaktion manuell erfassen; fehlende Werte werden abgefragt")
    add.add_argument("--date")
    add.add_argument("--transaction-type", choices=sorted(TRANSACTION_TYPES))
    add.add_argument("--amount")
    add.add_argument("--buy-price")
    add.add_argument("--sell-price")
    add.add_argument("--market-price")
    add.add_argument("--shares")
    add.add_argument("--fee")
    add.add_argument("--tax")
    add.add_argument("--name")
    add.add_argument("--identifier", help="ISIN oder Symbol")
    add.add_argument("--currency")
    add.add_argument("--description")
    add.add_argument("--transaction-id")
    add.add_argument("--non-interactive", action="store_true", help=argparse.SUPPRESS)

    sub.add_parser("list", help="Transaktionen ohne sensible Daten anzeigen")
    sub.add_parser("report", help="Portfolio-Bericht anzeigen")

    projection = sub.add_parser("forecast", help="Sparplan-Szenarien berechnen")
    projection.add_argument("--monthly", required=True, help="Monatliche Einzahlung")
    projection.add_argument("--years", required=True, type=int, help="Laufzeit in Jahren")
    rates = projection.add_mutually_exclusive_group(required=True)
    rates.add_argument("--return", dest="single_return", help="Angenommene Jahresrendite in Prozent")
    rates.add_argument("--returns", nargs="+", help="Mehrere Jahresrenditen in Prozent")
    projection.add_argument("--start-value", help="Optionaler Startwert; sonst vorhandener Depotwert")

    chart = sub.add_parser("chart", help="ASCII-Diagramme anzeigen")
    chart.add_argument("--monthly", default="25", help="Monatsrate für Prognosechart")
    chart.add_argument("--years", type=int, default=10, help="Jahre für Prognosechart")
    chart.add_argument("--return", dest="annual_return", default="5", help="Jahresrendite für Prognosechart")

    export = sub.add_parser("export", help="Excel-/ONLYOFFICE-kompatible CSV exportieren")
    export.add_argument("--output", required=True, type=Path)
    sub.add_parser("sample-data", help="Anonymisierte Beispieldaten ergänzen")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    storage = CSVStorage(args.data_dir)
    try:
        if args.command == "import-trade-republic":
            result = import_trade_republic(args.file, storage, preview=args.preview, dry_run=args.dry_run, skip_duplicates=args.skip_duplicates)
            if args.preview:
                print_transactions(result.transactions or [])
            print_import_result(result, verbose=args.verbose or bool(result.errors))
            if result.errors:
                print("Import abgebrochen; vorhandene Daten wurden nicht verändert.", file=sys.stderr)
                return 2
            if args.preview:
                print("Preview: Es wurden keine Daten gespeichert.")
            elif args.dry_run:
                print("Dry-run erfolgreich: Es wurden keine Daten gespeichert.")
        elif args.command == "add":
            supplied = any(getattr(args, name) is not None for name in (
                "date", "transaction_type", "amount", "buy_price", "sell_price", "market_price",
                "shares", "fee", "tax", "name", "identifier", "currency", "description",
            ))
            transaction = make_manual_transaction(args, interactive=not args.non_interactive and not supplied)
            storage.append(transaction)
            print(f"Transaktion gespeichert: {transaction.transaction_id}")
        elif args.command == "list":
            print_transactions(storage.load())
        elif args.command == "report":
            print_report(storage.load())
        elif args.command == "forecast":
            monthly = parse_decimal(args.monthly, "monthly", allow_empty=False)
            transactions = storage.load()
            current_value = summarize(transactions).portfolio_value
            start = parse_decimal(args.start_value, "start_value") if args.start_value is not None else (current_value or ZERO)
            raw_rates = [args.single_return] if args.single_return is not None else args.returns
            scenarios = [forecast(monthly, args.years, parse_decimal(rate, "return", allow_empty=False), start) for rate in raw_rates]
            print_forecasts(scenarios)
        elif args.command == "chart":
            transactions = storage.load()
            buys, values = chart_data(transactions)
            ascii_chart("Kumulierte ETF-Käufe", buys)
            ascii_chart("Historische Depotwerte (nur vorhandene Marktpreise)", values)
            summary = summarize(transactions)
            comparison = [("Investiert", summary.buy_amounts)]
            if summary.portfolio_value is not None:
                comparison.append(("Depotwert", summary.portfolio_value))
            ascii_chart("Investierter Betrag und Depotwert", comparison)
            scenario = forecast(parse_decimal(args.monthly, "monthly", allow_empty=False), args.years, parse_decimal(args.annual_return, "return", allow_empty=False), summary.portfolio_value or ZERO)
            ascii_chart("Prognoseentwicklung", [(f"Jahr {row.year}", row.value) for row in scenario.years])
            print("\nPrognose ist unverbindlich, keine Finanzberatung oder Garantie; Verluste sind möglich.")
        elif args.command == "export":
            output = export_csv(storage.load(), args.output)
            print(f"Export geschrieben: {output}")
        elif args.command == "sample-data":
            existing = storage.load()
            existing_ids = {item.transaction_id for item in existing}
            additions = [item for item in sample_transactions() if item.transaction_id not in existing_ids]
            if not additions:
                raise GrowthLedgerError("Beispieldaten sind bereits vorhanden; nichts wurde überschrieben.")
            storage.save([*existing, *additions])
            print(f"{len(additions)} deutlich gekennzeichnete Beispieldatensätze gespeichert; bestehende Daten blieben erhalten.")
        return 0
    except GrowthLedgerError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nAbgebrochen; es wurden keine unvollständigen Eingaben gespeichert.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
