"""Tests for portfolio chart calculation service."""

from __future__ import annotations

from datetime import date

import pytest

from nordpy.models import Transaction
from nordpy.services.portfolio_chart import PortfolioChartService


@pytest.fixture
def sample_transactions() -> list[Transaction]:
    """Sample transactions for testing portfolio calculation."""
    return [
        Transaction.model_validate(
            {
                "transactionId": "1",
                "accountingDate": "2024-01-01",
                "transactionTypeName": "DEPOSIT",
                "amount": {"value": 10000.0, "currencyCode": "DKK"},
            }
        ),
        Transaction.model_validate(
            {
                "transactionId": "2",
                "accountingDate": "2024-01-15",
                "transactionTypeName": "BUY",
                "instrumentName": "Apple",
                "isinCode": "US0378331005",
                "quantity": 10.0,
                "price": {"value": 150.0, "currencyCode": "USD"},
                "amount": {"value": -1500.0, "currencyCode": "DKK"},
            }
        ),
        Transaction.model_validate(
            {
                "transactionId": "3",
                "accountingDate": "2024-02-01",
                "transactionTypeName": "SELL",
                "instrumentName": "Apple",
                "isinCode": "US0378331005",
                "quantity": 5.0,
                "price": {"value": 160.0, "currencyCode": "USD"},
                "amount": {"value": 800.0, "currencyCode": "DKK"},
            }
        ),
    ]


class TestPortfolioChartService:
    def test_empty_transactions(self):
        service = PortfolioChartService([])
        history = service.calculate_history()
        assert history == []

    def test_deposit_only(self):
        txns = [
            Transaction.model_validate(
                {
                    "transactionId": "1",
                    "accountingDate": "2024-01-01",
                    "transactionTypeName": "DEPOSIT",
                    "amount": {"value": 5000.0, "currencyCode": "DKK"},
                }
            )
        ]
        service = PortfolioChartService(txns)
        history = service.calculate_history()

        assert len(history) == 1
        assert history[0].value == 5000.0
        assert history[0].cash_balance == 5000.0
        assert history[0].holdings_value == 0.0

    def test_buy_transaction(self):
        txns = [
            Transaction.model_validate(
                {
                    "transactionId": "1",
                    "accountingDate": "2024-01-01",
                    "transactionTypeName": "DEPOSIT",
                    "amount": {"value": 10000.0, "currencyCode": "DKK"},
                }
            ),
            Transaction.model_validate(
                {
                    "transactionId": "2",
                    "accountingDate": "2024-01-15",
                    "transactionTypeName": "BUY",
                    "instrumentName": "Test Stock",
                    "isinCode": "TEST123",
                    "quantity": 10.0,
                    "price": {"value": 100.0, "currencyCode": "DKK"},
                    "amount": {"value": -1000.0, "currencyCode": "DKK"},
                }
            ),
        ]
        service = PortfolioChartService(txns)
        history = service.calculate_history()

        assert len(history) == 2

        # After deposit
        assert history[0].date == date(2024, 1, 1)
        assert history[0].cash_balance == 10000.0
        assert history[0].holdings_value == 0.0

        # After buy
        assert history[1].date == date(2024, 1, 15)
        assert history[1].cash_balance == 9000.0  # 10000 - 1000
        assert history[1].holdings_value == 1000.0  # 10 * 100

    def test_buy_sell_cycle(self, sample_transactions):
        service = PortfolioChartService(sample_transactions)
        history = service.calculate_history()

        assert len(history) == 3

        # After deposit
        assert history[0].date == date(2024, 1, 1)
        assert history[0].cash_balance == 10000.0

        # After buy
        assert history[1].date == date(2024, 1, 15)
        assert history[1].cash_balance == 8500.0  # 10000 - 1500
        assert history[1].holdings_value == 1500.0  # 10 * 150

        # After sell
        assert history[2].date == date(2024, 2, 1)
        assert history[2].cash_balance == 9300.0  # 8500 + 800
        # Holdings: 5 shares * 150 (avg price) = 750
        assert history[2].holdings_value == 750.0

    def test_progress_callback(self, sample_transactions):
        service = PortfolioChartService(sample_transactions)
        calls: list[tuple[int, int]] = []

        service.calculate_history(on_progress=lambda curr, total: calls.append((curr, total)))

        assert len(calls) == 3
        assert calls[-1] == (3, 3)

    def test_danish_transaction_types(self):
        """Test Danish transaction type names are recognized."""
        txns = [
            Transaction.model_validate(
                {
                    "transactionId": "1",
                    "accountingDate": "2024-01-01",
                    "transactionTypeName": "KOB",  # Danish for buy
                    "instrumentName": "Test",
                    "quantity": 5.0,
                    "price": {"value": 100.0, "currencyCode": "DKK"},
                    "amount": {"value": -500.0, "currencyCode": "DKK"},
                }
            ),
            Transaction.model_validate(
                {
                    "transactionId": "2",
                    "accountingDate": "2024-01-15",
                    "transactionTypeName": "SALG",  # Danish for sell
                    "instrumentName": "Test",
                    "quantity": 5.0,
                    "price": {"value": 110.0, "currencyCode": "DKK"},
                    "amount": {"value": 550.0, "currencyCode": "DKK"},
                }
            ),
        ]
        service = PortfolioChartService(txns)
        history = service.calculate_history()

        assert len(history) == 2
        # After KOB (buy): cash = -500, holdings = 500
        assert history[0].holdings_value == 500.0
        # After SALG (sell): position closed, cash = 50
        assert history[1].holdings_value == 0.0

    def test_dividend_transaction(self):
        """Test dividend adds to cash balance."""
        txns = [
            Transaction.model_validate(
                {
                    "transactionId": "1",
                    "accountingDate": "2024-01-01",
                    "transactionTypeName": "DIVIDEND",
                    "amount": {"value": 100.0, "currencyCode": "DKK"},
                }
            ),
        ]
        service = PortfolioChartService(txns)
        history = service.calculate_history()

        assert len(history) == 1
        assert history[0].cash_balance == 100.0

    def test_infer_currency(self, sample_transactions):
        service = PortfolioChartService(sample_transactions)
        history = service.calculate_history()

        assert history[0].currency == "DKK"

    def test_infer_currency_empty(self):
        service = PortfolioChartService([])
        assert service._infer_currency() == "DKK"
