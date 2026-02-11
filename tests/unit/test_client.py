"""Tests for nordpy.client — API client, token management, pagination, retry."""

from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timezone

import pytest
import responses

from nordpy.client import NordnetAPIError, NordnetClient

BASE_URL = "https://www.nordnet.dk"
TX_API_URL = "https://api.prod.nntech.io"


@pytest.fixture
def client(mock_session) -> NordnetClient:
    return NordnetClient(mock_session)


def _make_jwt(exp: int | None = None) -> str:
    """Build a minimal JWT string with an exp claim."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=")
    payload_data: dict = {}
    if exp is not None:
        payload_data["exp"] = exp
    payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b"=")
    sig = base64.urlsafe_b64encode(b"sig").rstrip(b"=")
    return f"{header.decode()}.{payload.decode()}.{sig.decode()}"


# ── _get() ──


class TestGet:
    @responses.activate
    def test_get_200(self, client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api/2/accounts",
            json=[{"accid": 1}],
            status=200,
        )
        result = client._get("/api/2/accounts")
        assert result == [{"accid": 1}]

    @responses.activate
    def test_get_204_returns_empty_list(self, client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api/2/accounts/1/trades",
            status=204,
        )
        result = client._get("/api/2/accounts/1/trades")
        assert result == []

    @responses.activate
    def test_get_non_200_raises(self, client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api/2/accounts",
            body="Forbidden",
            status=403,
        )
        with pytest.raises(NordnetAPIError) as exc_info:
            client._get("/api/2/accounts")
        assert exc_info.value.status_code == 403


# ── JWT parsing ──


class TestJWT:
    def test_parse_jwt_expiry_valid(self):
        exp = int(time.time()) + 3600
        token = _make_jwt(exp=exp)
        result = NordnetClient._parse_jwt_expiry(token)
        assert result is not None
        assert result.tzinfo == timezone.utc

    def test_parse_jwt_expiry_missing_exp(self):
        token = _make_jwt(exp=None)
        result = NordnetClient._parse_jwt_expiry(token)
        assert result is None

    def test_parse_jwt_expiry_invalid_token(self):
        result = NordnetClient._parse_jwt_expiry("not.a.jwt")
        assert result is None

    def test_token_seconds_remaining_no_token(self, client):
        assert client.token_seconds_remaining is None

    def test_token_seconds_remaining_with_token(self, client):
        exp = int(datetime.now(timezone.utc).timestamp()) + 300
        token = _make_jwt(exp=exp)
        client._bearer_token = token
        client._token_expiry = NordnetClient._parse_jwt_expiry(token)
        remaining = client.token_seconds_remaining
        assert remaining is not None
        assert 295 <= remaining <= 305


# ── Bearer token ──


class TestBearerToken:
    @responses.activate
    def test_get_bearer_token_caches(self, client):
        exp = int(time.time()) + 3600
        token = _make_jwt(exp=exp)
        responses.add(
            responses.POST,
            f"{BASE_URL}/nnxapi/authorization/v1/tokens",
            json={"jwt": token},
            status=200,
        )
        t1 = client._get_bearer_token()
        t2 = client._get_bearer_token()
        assert t1 == t2
        assert len(responses.calls) == 1  # Only one HTTP call

    @responses.activate
    def test_get_bearer_token_force_refresh(self, client):
        exp = int(time.time()) + 3600
        token1 = _make_jwt(exp=exp)
        token2 = _make_jwt(exp=exp + 100)
        responses.add(
            responses.POST,
            f"{BASE_URL}/nnxapi/authorization/v1/tokens",
            json={"jwt": token1},
            status=200,
        )
        responses.add(
            responses.POST,
            f"{BASE_URL}/nnxapi/authorization/v1/tokens",
            json={"jwt": token2},
            status=200,
        )
        t1 = client._get_bearer_token()
        t2 = client._get_bearer_token(force_refresh=True)
        assert t1 != t2
        assert len(responses.calls) == 2

    @responses.activate
    def test_get_bearer_token_fails(self, client):
        responses.add(
            responses.POST,
            f"{BASE_URL}/nnxapi/authorization/v1/tokens",
            body="Unauthorized",
            status=401,
        )
        with pytest.raises(NordnetAPIError):
            client._get_bearer_token()


# ── Account/Balance/Holdings methods ──


class TestAccountMethods:
    @responses.activate
    def test_get_accounts(self, client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api/2/accounts",
            json=[{"accid": 1, "accno": 42333260, "type": "ASK"}],
            status=200,
        )
        accounts = client.get_accounts()
        assert len(accounts) == 1
        assert accounts[0].accno == "42333260"

    @responses.activate
    def test_get_balance(self, client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api/2/accounts/1/info",
            json={"account_sum": {"value": 5000.0, "currency": "DKK"}},
            status=200,
        )
        bal = client.get_balance(1)
        assert bal.balance.value == 5000.0

    @responses.activate
    def test_get_holdings(self, client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api/2/accounts/1/positions",
            json=[
                {
                    "instrument": {"name": "AAPL"},
                    "qty": 10.0,
                    "acq_price": {"value": 100.0},
                    "market_value": {"value": 120.0},
                }
            ],
            status=200,
        )
        holdings = client.get_holdings(1)
        assert len(holdings) == 1
        assert holdings[0].quantity == 10.0


# ── Trades/Orders ──


class TestTradesOrders:
    @responses.activate
    def test_get_trades_200(self, client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api/2/accounts/1/trades",
            json=[
                {
                    "trade_time": "2024-01-01T10:00:00",
                    "side": "BUY",
                    "instrument": {"name": "X"},
                    "volume": 5.0,
                    "price": {"value": 100.0},
                }
            ],
            status=200,
        )
        trades = client.get_trades(1)
        assert len(trades) == 1

    @responses.activate
    def test_get_trades_204_empty(self, client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api/2/accounts/1/trades",
            status=204,
        )
        trades = client.get_trades(1)
        assert trades == []

    @responses.activate
    def test_get_orders_204_empty(self, client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api/2/accounts/1/orders",
            status=204,
        )
        orders = client.get_orders(1)
        assert orders == []


# ── _get_tx_api() with 401 retry ──


class TestTxApi:
    @responses.activate
    def test_401_retries_with_fresh_token(self, client):
        exp = int(time.time()) + 3600
        token = _make_jwt(exp=exp)

        # Token endpoint (called twice: initial + refresh)
        responses.add(
            responses.POST,
            f"{BASE_URL}/nnxapi/authorization/v1/tokens",
            json={"jwt": token},
            status=200,
        )
        responses.add(
            responses.POST,
            f"{BASE_URL}/nnxapi/authorization/v1/tokens",
            json={"jwt": token},
            status=200,
        )

        # First attempt: 401, second attempt: 200
        responses.add(
            responses.GET,
            f"{TX_API_URL}/transaction/v1/summary",
            status=401,
        )
        responses.add(
            responses.GET,
            f"{TX_API_URL}/transaction/v1/summary",
            json={"total": 5},
            status=200,
        )

        result = client._get_tx_api("/transaction/v1/summary")
        assert result == {"total": 5}


# ── get_transactions() pagination ──


class TestGetTransactions:
    @responses.activate
    def test_single_batch(self, client):
        exp = int(time.time()) + 3600
        token = _make_jwt(exp=exp)
        responses.add(
            responses.POST,
            f"{BASE_URL}/nnxapi/authorization/v1/tokens",
            json={"jwt": token},
            status=200,
        )

        # Summary
        responses.add(
            responses.GET,
            f"{TX_API_URL}/transaction/transaction-and-notes/v1/transaction-summary",
            json={"totalNumberOfTransactions": 2},
            status=200,
        )
        # Page
        responses.add(
            responses.GET,
            f"{TX_API_URL}/transaction/transaction-and-notes/v1/transactions/page",
            json={
                "transactions": [
                    {
                        "transactionId": "tx-1",
                        "accountingDate": "2024-01-01",
                        "transactionTypeName": "BUY",
                        "amount": {"value": -100.0},
                    },
                    {
                        "transactionId": "tx-2",
                        "accountingDate": "2024-01-02",
                        "transactionTypeName": "SELL",
                        "amount": {"value": 200.0},
                    },
                ]
            },
            status=200,
        )

        txns = client.get_transactions("12345", accid=1)
        assert len(txns) == 2
        assert txns[0].transaction_id == "tx-1"

    @responses.activate
    def test_empty_transactions(self, client):
        exp = int(time.time()) + 3600
        token = _make_jwt(exp=exp)
        responses.add(
            responses.POST,
            f"{BASE_URL}/nnxapi/authorization/v1/tokens",
            json={"jwt": token},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{TX_API_URL}/transaction/transaction-and-notes/v1/transaction-summary",
            json={"totalNumberOfTransactions": 0},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{TX_API_URL}/transaction/transaction-and-notes/v1/transactions/page",
            json={"transactions": []},
            status=200,
        )

        txns = client.get_transactions("12345", accid=1)
        assert txns == []

    @responses.activate
    def test_progress_callback(self, client):
        exp = int(time.time()) + 3600
        token = _make_jwt(exp=exp)
        responses.add(
            responses.POST,
            f"{BASE_URL}/nnxapi/authorization/v1/tokens",
            json={"jwt": token},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{TX_API_URL}/transaction/transaction-and-notes/v1/transaction-summary",
            json={"totalNumberOfTransactions": 1},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{TX_API_URL}/transaction/transaction-and-notes/v1/transactions/page",
            json={
                "transactions": [
                    {
                        "transactionId": "tx-1",
                        "accountingDate": "2024-01-01",
                        "transactionTypeName": "X",
                        "amount": {"value": 0.0},
                    }
                ]
            },
            status=200,
        )

        progress_calls = []
        client.get_transactions(
            "12345",
            accid=1,
            on_progress=lambda f, t: progress_calls.append((f, t)),
        )
        assert len(progress_calls) == 1
        assert progress_calls[0] == (1, 1)
