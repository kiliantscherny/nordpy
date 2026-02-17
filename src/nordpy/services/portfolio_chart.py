"""Portfolio value chart calculation service."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Callable

from nordpy.models import Holding, PortfolioValuePoint, Transaction


class PortfolioChartService:
    """Calculates portfolio value history from transactions."""

    # Transaction type classification (includes Danish terms)
    CASH_TYPES = {"DEPOSIT", "WITHDRAWAL", "DIVIDEND", "INTEREST", "FEE", "TAX", "RENTE"}
    BUY_TYPES = {"BUY", "PURCHASE", "KOB", "KOBT", "KØB", "KØBT"}
    SELL_TYPES = {"SELL", "SALE", "SALG", "SOLGT"}

    def __init__(
        self,
        transactions: list[Transaction],
        current_holdings: list[Holding] | None = None,
    ) -> None:
        self.transactions = sorted(transactions, key=lambda t: t.accounting_date)
        self.current_holdings = current_holdings or []

    def calculate_history(
        self,
        *,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list[PortfolioValuePoint]:
        """Calculate daily portfolio value points."""
        if not self.transactions:
            return []

        # Group by date
        txns_by_date: dict[date, list[Transaction]] = defaultdict(list)
        for tx in self.transactions:
            txns_by_date[tx.accounting_date].append(tx)

        cash_balance = 0.0
        positions: dict[str, dict[str, float]] = {}
        history: list[PortfolioValuePoint] = []

        dates = sorted(txns_by_date.keys())
        total = len(dates)

        for i, dt in enumerate(dates):
            for tx in txns_by_date[dt]:
                cash_balance = self._process_transaction(tx, cash_balance, positions)

            holdings_value = sum(p["qty"] * p["avg_price"] for p in positions.values())

            history.append(
                PortfolioValuePoint(
                    date=dt,
                    value=cash_balance + holdings_value,
                    currency=self._infer_currency(),
                    cash_balance=cash_balance,
                    holdings_value=holdings_value,
                )
            )

            if on_progress:
                on_progress(i + 1, total)

        return history

    def _process_transaction(
        self,
        tx: Transaction,
        cash: float,
        positions: dict[str, dict[str, float]],
    ) -> float:
        """Process a single transaction, updating state. Returns new cash balance."""
        tx_type = tx.transaction_type_name.upper()

        # Cash transactions
        if any(t in tx_type for t in self.CASH_TYPES):
            return cash + tx.amount.value

        # Buy transactions
        if any(t in tx_type for t in self.BUY_TYPES):
            cash += tx.amount.value  # amount is negative for buys
            isin = tx.isin_code or tx.instrument_name or "UNKNOWN"
            if isin not in positions:
                positions[isin] = {"qty": 0.0, "avg_price": 0.0}

            qty = tx.quantity or 0.0
            price = tx.price.value if tx.price else 0.0
            if qty > 0:
                old_qty = positions[isin]["qty"]
                old_val = old_qty * positions[isin]["avg_price"]
                new_val = qty * price
                positions[isin]["qty"] = old_qty + qty
                if positions[isin]["qty"] > 0:
                    positions[isin]["avg_price"] = (old_val + new_val) / positions[isin][
                        "qty"
                    ]
            return cash

        # Sell transactions
        if any(t in tx_type for t in self.SELL_TYPES):
            cash += tx.amount.value  # amount is positive for sells
            isin = tx.isin_code or tx.instrument_name or "UNKNOWN"
            if isin in positions:
                qty = tx.quantity or 0.0
                positions[isin]["qty"] -= qty
                if positions[isin]["qty"] <= 0:
                    del positions[isin]
            return cash

        # Default: treat as cash transaction (fees, taxes, etc.)
        return cash + tx.amount.value

    def _infer_currency(self) -> str:
        """Infer primary currency from transactions."""
        if self.transactions:
            return self.transactions[0].amount.currency or "DKK"
        return "DKK"
