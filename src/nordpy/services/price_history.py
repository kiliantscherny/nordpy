"""Price history service using yfinance for historical instrument prices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

import yfinance as yf

from nordpy.models import Holding, PortfolioValuePoint, Transaction


@dataclass
class PricePoint:
    """A single price point for an instrument."""

    date: date
    close: float
    currency: str


class PriceHistoryService:
    """Fetches historical prices for instruments using yfinance."""

    # Market suffixes for different exchanges
    MARKET_SUFFIXES = {
        "DK": ".CO",  # Copenhagen
        "SE": ".ST",  # Stockholm
        "NO": ".OL",  # Oslo
        "FI": ".HE",  # Helsinki
        "DE": ".DE",  # Germany (XETRA)
        "US": "",  # US markets (no suffix)
        "GB": ".L",  # London
        "NL": ".AS",  # Amsterdam
        "FR": ".PA",  # Paris
        "IT": ".MI",  # Milan
        "CH": ".SW",  # Swiss
        "ES": ".MC",  # Madrid
        "AT": ".VI",  # Vienna
        "BE": ".BR",  # Brussels
        "PT": ".LS",  # Lisbon
        "IE": ".DE",  # Irish ETFs often trade on XETRA
        "LU": ".DE",  # Luxembourg funds often on XETRA
    }

    # Fallback exchanges to try if primary lookup fails (for ETFs etc.)
    FALLBACK_SUFFIXES = [".DE", ".AS", ".L", ".PA", ".MI", ""]

    def __init__(self) -> None:
        self._price_cache: dict[str, dict[date, float]] = {}
        self._symbol_suffix_cache: dict[str, str] = {}  # Cache working suffixes

    def get_price_history_by_isin(
        self,
        isin: str,
        start_date: date,
        end_date: date | None = None,
        symbol: str = "",
        market: str = "",
    ) -> dict[date, float]:
        """
        Fetch historical prices, preferring symbol lookup.

        Args:
            isin: ISIN code (not used directly, kept for API compatibility)
            start_date: Start date for history
            end_date: End date (defaults to today)
            symbol: Ticker symbol for yfinance
            market: Market code for exchange suffix (e.g., "DK", "SE")

        Returns:
            Dict mapping dates to closing prices
        """
        # Use symbol for yfinance lookup
        if symbol:
            return self.get_price_history(symbol, start_date, end_date, market)
        return {}

    def get_price_history(
        self,
        symbol: str,
        start_date: date,
        end_date: date | None = None,
        market: str = "",
    ) -> dict[date, float]:
        """
        Fetch historical closing prices for a symbol.

        Tries the primary market suffix first, then falls back to trying
        multiple common exchanges (useful for ETFs).

        Args:
            symbol: Ticker symbol (e.g., "AAPL", "NOVO-B")
            start_date: Start date for history
            end_date: End date (defaults to today)
            market: Market code for suffix (e.g., "DK", "SE")

        Returns:
            Dict mapping dates to closing prices
        """
        if not symbol:
            return {}

        end_date = end_date or date.today()
        base_symbol = symbol.split(".")[0] if "." in symbol else symbol

        # Check if we already know the working suffix for this symbol
        if base_symbol in self._symbol_suffix_cache:
            working_suffix = self._symbol_suffix_cache[base_symbol]
            prices = self._fetch_prices(f"{base_symbol}{working_suffix}", start_date, end_date)
            if prices:
                return prices

        # Build list of suffixes to try
        suffixes_to_try = []

        # First try the market-specific suffix
        if market and market in self.MARKET_SUFFIXES:
            suffixes_to_try.append(self.MARKET_SUFFIXES[market])

        # Then try fallback suffixes
        for suffix in self.FALLBACK_SUFFIXES:
            if suffix not in suffixes_to_try:
                suffixes_to_try.append(suffix)

        # Try each suffix until we find data
        for suffix in suffixes_to_try:
            ticker = f"{base_symbol}{suffix}" if suffix else base_symbol
            prices = self._fetch_prices(ticker, start_date, end_date)
            if prices:
                # Cache the working suffix for future lookups
                self._symbol_suffix_cache[base_symbol] = suffix
                return prices

        return {}

    def _fetch_prices(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> dict[date, float]:
        """Fetch prices for a specific ticker from yfinance."""
        cache_key = ticker

        # Check cache
        if cache_key in self._price_cache:
            cached = self._price_cache[cache_key]
            if cached and min(cached.keys()) <= start_date:
                return {d: p for d, p in cached.items() if start_date <= d <= end_date}

        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(
                start=start_date.isoformat(),
                end=(end_date + timedelta(days=1)).isoformat(),
            )

            if hist.empty:
                return {}

            prices = {}
            for idx, row in hist.iterrows():
                dt = idx.date() if hasattr(idx, "date") else idx
                if isinstance(dt, datetime):
                    dt = dt.date()
                prices[dt] = float(row["Close"])

            # Cache the results
            self._price_cache[cache_key] = prices

            return {d: p for d, p in prices.items() if start_date <= d <= end_date}

        except Exception:
            return {}


class PortfolioNAVService:
    """Calculates portfolio NAV over time using actual price history."""

    def __init__(
        self,
        transactions: list[Transaction],
        holdings: list[Holding],
        price_service: PriceHistoryService | None = None,
    ) -> None:
        self.transactions = sorted(transactions, key=lambda t: t.accounting_date)
        self.holdings = holdings
        self.price_service = price_service or PriceHistoryService()
        self._symbol_map: dict[str, str] = {}  # ISIN -> symbol mapping

        # Build symbol map from holdings
        for h in holdings:
            if h.instrument.isin and h.instrument.symbol:
                self._symbol_map[h.instrument.isin] = h.instrument.symbol

    def calculate_nav_history(
        self,
        *,
        on_progress: Callable[[str, int, int], None] | None = None,
    ) -> list[PortfolioValuePoint]:
        """
        Calculate portfolio NAV over time using actual historical prices.

        This reconstructs the portfolio at each date based on transactions,
        then values the positions using historical prices.
        """
        if not self.transactions:
            return []

        # Determine date range
        start_date = self.transactions[0].accounting_date
        end_date = date.today()

        # Get all unique instruments from transactions
        instruments = self._get_instruments_from_transactions()

        # Fetch price history for all instruments
        if on_progress:
            on_progress("Fetching price history...", 0, len(instruments))

        price_histories: dict[str, dict[date, float]] = {}
        found_prices = 0
        for i, (isin, symbol) in enumerate(instruments.items()):
            # Fetch historical prices by ISIN with symbol fallback (yfinance)
            prices = self.price_service.get_price_history_by_isin(
                isin, start_date, end_date, symbol=symbol
            )
            if prices:
                price_histories[isin] = prices
                found_prices += 1
            if on_progress:
                status = "found" if prices else "not found"
                on_progress(
                    f"Prices for {symbol or isin}: {status}",
                    i + 1,
                    len(instruments),
                )

        if on_progress:
            on_progress(
                f"Found prices for {found_prices}/{len(instruments)} instruments",
                len(instruments),
                len(instruments),
            )

        # Build portfolio state over time
        if on_progress:
            on_progress("Calculating portfolio values...", 0, 0)

        return self._calculate_daily_nav(price_histories, start_date, end_date)

    def _get_instruments_from_transactions(self) -> dict[str, str]:
        """Extract unique instruments from transactions. Returns ISIN -> symbol map."""
        instruments: dict[str, str] = {}
        for tx in self.transactions:
            isin = tx.isin_code
            if isin and isin not in instruments:
                # Try to get symbol from holdings map or use instrument name
                symbol = self._symbol_map.get(isin, "")
                instruments[isin] = symbol
        return instruments

    def _calculate_daily_nav(
        self,
        price_histories: dict[str, dict[date, float]],
        start_date: date,
        end_date: date,
    ) -> list[PortfolioValuePoint]:
        """Calculate daily NAV based on positions and prices.

        Uses market prices when available, falls back to cost basis from
        buy transactions when market prices aren't found.
        """
        # Transaction type classification
        cash_types = {"DEPOSIT", "WITHDRAWAL", "DIVIDEND", "INTEREST", "FEE", "TAX", "RENTE"}
        buy_types = {"BUY", "PURCHASE", "KOB", "KOBT", "KØB", "KØBT"}
        sell_types = {"SELL", "SALE", "SALG", "SOLGT"}

        # Track state
        cash_balance = 0.0
        positions: dict[str, float] = {}  # ISIN -> quantity
        cost_basis: dict[str, float] = {}  # ISIN -> total cost
        last_known_price: dict[str, float] = {}  # ISIN -> last transaction price
        tx_idx = 0

        nav_points: list[PortfolioValuePoint] = []
        current_date = start_date

        while current_date <= end_date:
            # Process all transactions up to and including current date
            while tx_idx < len(self.transactions) and self.transactions[tx_idx].accounting_date <= current_date:
                tx = self.transactions[tx_idx]
                tx_type = tx.transaction_type_name.upper()
                isin = tx.isin_code or "CASH"

                if any(t in tx_type for t in cash_types):
                    cash_balance += tx.amount.value
                elif any(t in tx_type for t in buy_types):
                    cash_balance += tx.amount.value  # Negative for buys
                    qty = tx.quantity or 0.0
                    positions[isin] = positions.get(isin, 0.0) + qty
                    # Track cost basis (negative amount = cost)
                    cost_basis[isin] = cost_basis.get(isin, 0.0) + abs(tx.amount.value)
                    # Track last known price from transaction
                    if tx.price and tx.price.value > 0:
                        last_known_price[isin] = tx.price.value
                elif any(t in tx_type for t in sell_types):
                    cash_balance += tx.amount.value  # Positive for sells
                    qty = tx.quantity or 0.0
                    old_qty = positions.get(isin, 0.0)
                    # Reduce cost basis proportionally
                    if old_qty > 0 and isin in cost_basis:
                        sold_fraction = min(qty / old_qty, 1.0)
                        cost_basis[isin] = cost_basis[isin] * (1 - sold_fraction)
                    positions[isin] = old_qty - qty
                    if positions.get(isin, 0.0) <= 0:
                        positions.pop(isin, None)
                        cost_basis.pop(isin, None)
                    # Track last known price from transaction
                    if tx.price and tx.price.value > 0:
                        last_known_price[isin] = tx.price.value
                else:
                    # Default: treat as cash transaction
                    cash_balance += tx.amount.value

                tx_idx += 1

            # Calculate holdings value at current date
            holdings_value = 0.0
            for isin, qty in positions.items():
                if qty <= 0:
                    continue

                price = None

                # Try market price first
                if isin in price_histories:
                    price = self._get_price_on_date(price_histories[isin], current_date)

                if price:
                    # Use market price
                    holdings_value += qty * price
                elif isin in last_known_price:
                    # Fall back to last known transaction price
                    holdings_value += qty * last_known_price[isin]
                elif isin in cost_basis and qty > 0:
                    # Fall back to cost basis (total cost for the position)
                    holdings_value += cost_basis[isin]

            total_value = cash_balance + holdings_value

            # Only add point if we have any value or it's a transaction date
            if total_value != 0 or current_date == start_date:
                nav_points.append(
                    PortfolioValuePoint(
                        date=current_date,
                        value=total_value,
                        currency="DKK",  # Assume DKK for now
                        cash_balance=cash_balance,
                        holdings_value=holdings_value,
                    )
                )

            current_date += timedelta(days=1)

        # Filter to only include dates with actual data (reduce noise)
        return self._filter_to_weekly_or_monthly(nav_points)

    def _get_price_on_date(self, prices: dict[date, float], target_date: date) -> float | None:
        """Get price on a specific date, or the most recent price before it."""
        if target_date in prices:
            return prices[target_date]

        # Find most recent price before target date
        available_dates = sorted(d for d in prices.keys() if d <= target_date)
        if available_dates:
            return prices[available_dates[-1]]
        return None

    def _filter_to_weekly_or_monthly(
        self, points: list[PortfolioValuePoint]
    ) -> list[PortfolioValuePoint]:
        """Reduce data points to weekly samples for cleaner charts."""
        if len(points) <= 52:  # Less than a year of data
            return points

        # Sample weekly
        filtered: list[PortfolioValuePoint] = []
        last_date: date | None = None

        for point in points:
            if last_date is None or (point.date - last_date).days >= 7:
                filtered.append(point)
                last_date = point.date

        # Always include the last point
        if points and (not filtered or filtered[-1] != points[-1]):
            filtered.append(points[-1])

        return filtered
