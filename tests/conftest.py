"""Shared test fixtures for nordpy tests."""

from __future__ import annotations

import pytest
import requests

from nordpy.models import (
    Account,
    AccountBalance,
    Holding,
    MoneyAmount,
    Transaction,
)


# ── Raw API response dicts ──


@pytest.fixture
def account_response_dict() -> dict:
    """Minimal Nordnet /api/2/accounts response item."""
    return {"accid": 1, "accno": 42333260, "type": "ASK", "alias": "My Depot"}


@pytest.fixture
def account_info_response_dict() -> dict:
    """Minimal Nordnet /api/2/accounts/{accid}/info response."""
    return {"account_sum": {"value": 12345.67, "currency": "DKK"}}


@pytest.fixture
def holding_response_dict() -> dict:
    """Minimal Nordnet positions response item."""
    return {
        "instrument": {"name": "Apple Inc", "symbol": "AAPL", "isin": "US0378331005"},
        "qty": 10.0,
        "acq_price": {"value": 150.0, "currency": "USD"},
        "market_value": {"value": 175.0, "currency": "USD"},
    }


@pytest.fixture
def transaction_response_dict() -> dict:
    """Minimal Nordnet transaction response item."""
    return {
        "transactionId": "tx-001",
        "accountingDate": "2024-01-15",
        "transactionTypeName": "BUY",
        "transactionTypeCode": "BUY",
        "instrumentName": "Apple Inc",
        "amount": {"value": -1500.0, "currencyCode": "DKK"},
        "quantity": 10.0,
        "price": {"value": 150.0, "currencyCode": "USD"},
    }


# ── Model instances ──


@pytest.fixture
def sample_account() -> Account:
    return Account(accid=1, accno="42333260", type="ASK", alias="My Depot")


@pytest.fixture
def sample_holding() -> Holding:
    """Must use model_validate with dicts — Holding's _parse_money validator
    requires dict input (non-dict → zeroed out)."""
    return Holding.model_validate(
        {
            "instrument": {
                "name": "Apple Inc",
                "symbol": "AAPL",
                "isin": "US0378331005",
            },
            "qty": 10.0,
            "acq_price": {"value": 150.0, "currencyCode": "USD"},
            "market_value": {"value": 175.0, "currencyCode": "USD"},
        }
    )


@pytest.fixture
def sample_transaction() -> Transaction:
    return Transaction.model_validate(
        {
            "transactionId": "tx-001",
            "accountingDate": "2024-01-15",
            "transactionTypeName": "BUY",
            "amount": {"value": -1500.0, "currencyCode": "DKK"},
        }
    )


@pytest.fixture
def sample_balance() -> AccountBalance:
    return AccountBalance(accid=1, balance=MoneyAmount(value=12345.67, currency="DKK"))


@pytest.fixture
def mock_session() -> requests.Session:
    """A real requests.Session (use with `responses` library to mock HTTP)."""
    return requests.Session()
