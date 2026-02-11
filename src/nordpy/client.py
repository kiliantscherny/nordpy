"""Nordnet API client — wraps authenticated requests.Session with typed methods."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any

import requests

from nordpy.models import Account, AccountBalance, Holding, Order, Trade, Transaction


class NordnetAPIError(Exception):
    """Raised when a Nordnet API call fails."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"Nordnet API error {status_code}: {message}")


class NordnetClient:
    """Base API client wrapping an authenticated requests.Session."""

    BASE_URL = "https://www.nordnet.dk"
    TX_API_URL = "https://api.prod.nntech.io"
    DEFAULT_TIMEOUT = 30

    def __init__(self, session: requests.Session) -> None:
        self.session = session
        self._bearer_token: str | None = None
        self._token_expiry: datetime | None = None

    def _get(self, path: str, *, timeout: int | None = None) -> Any:
        """Make a GET request to the legacy API and return parsed JSON."""
        url = f"{self.BASE_URL}{path}"
        response = self.session.get(url, timeout=timeout or self.DEFAULT_TIMEOUT)
        if response.status_code == 204:
            return []
        if response.status_code != 200:
            raise NordnetAPIError(response.status_code, response.text[:200])
        return response.json()

    @property
    def token_expiry(self) -> datetime | None:
        """UTC expiry time of the current bearer token, or None if no token."""
        return self._token_expiry

    @property
    def token_seconds_remaining(self) -> int | None:
        """Seconds until bearer token expires, or None if no token."""
        if not self._token_expiry:
            return None
        delta = self._token_expiry - datetime.now(timezone.utc)
        return max(0, int(delta.total_seconds()))

    def _get_bearer_token(self, *, force_refresh: bool = False) -> str:
        """Obtain a JWT bearer token for the newer API endpoints."""
        if self._bearer_token and not force_refresh:
            # Check if token is still valid (with 30s buffer)
            if self._token_expiry:
                remaining = (
                    self._token_expiry - datetime.now(timezone.utc)
                ).total_seconds()
                if remaining < 30:
                    self._bearer_token = None  # Force refresh

        if self._bearer_token and not force_refresh:
            return self._bearer_token

        response = self.session.post(
            f"{self.BASE_URL}/nnxapi/authorization/v1/tokens",
            json={},
            timeout=self.DEFAULT_TIMEOUT,
        )
        if response.status_code not in (200, 201):
            raise NordnetAPIError(response.status_code, "Failed to obtain bearer token")

        token = response.json().get("jwt", "")
        self._bearer_token = token
        self._token_expiry = self._parse_jwt_expiry(token)
        return self._bearer_token

    @staticmethod
    def _parse_jwt_expiry(token: str) -> datetime | None:
        """Extract the exp claim from a JWT token."""
        try:
            payload = token.split(".")[1]
            # Add padding for base64
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += "=" * padding
            decoded = json.loads(base64.urlsafe_b64decode(payload))
            exp = decoded.get("exp")
            if exp:
                return datetime.fromtimestamp(exp, tz=timezone.utc)
        except Exception:
            pass
        return None

    # ── Account methods (US1) ──

    def get_accounts(self) -> list[Account]:
        """Fetch all accounts for the authenticated user."""
        data = self._get("/api/2/accounts")
        return [Account.model_validate(item) for item in data]

    def get_balance(self, accid: int) -> AccountBalance:
        """Fetch balance information for a specific account."""
        data = self._get(f"/api/2/accounts/{accid}/info")
        return AccountBalance.from_info_response(accid, data)

    # ── Holdings methods (US2) ──

    def get_holdings(self, accid: int) -> list[Holding]:
        """Fetch current holdings/positions for an account."""
        data = self._get(f"/api/2/accounts/{accid}/positions")
        return [Holding.model_validate(item) for item in data]

    # ── Trade and Order methods (US5) ──

    def get_trades(self, accid: int) -> list[Trade]:
        """Fetch executed trades for an account."""
        data = self._get(f"/api/2/accounts/{accid}/trades")
        return [Trade.model_validate(item) for item in data]

    def get_orders(self, accid: int) -> list[Order]:
        """Fetch orders for an account."""
        data = self._get(f"/api/2/accounts/{accid}/orders")
        return [Order.model_validate(item) for item in data]

    def _get_tx_api(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Make a GET request to the transaction API (Bearer auth). Retries once on 401."""
        for attempt in range(2):
            token = self._get_bearer_token(force_refresh=attempt > 0)
            headers = {
                "Authorization": f"Bearer {token}",
                "client-id": "NEXT",
                "x-locale": "da-DK",
            }
            url = f"{self.TX_API_URL}{path}"
            response = self.session.get(
                url,
                headers=headers,
                params=params,
                timeout=self.DEFAULT_TIMEOUT,
            )
            if response.status_code == 401 and attempt == 0:
                continue  # Retry with fresh token
            if response.status_code != 200:
                raise NordnetAPIError(response.status_code, response.text[:200])
            return response.json()

    # ── Transaction methods (US3) ──

    def get_transactions(
        self,
        accno: str,
        *,
        accid: int | None = None,
        on_progress: object = None,
    ) -> list[Transaction]:
        """Fetch all transactions for an account, paginating in batches of 800."""
        _progress = on_progress or (lambda fetched, total: None)
        from_date = "2010-01-01"
        to_date = datetime.now().strftime("%Y-%m-%d")
        base_path = "/transaction/transaction-and-notes/v1"

        # The transaction API uses accids (integer account IDs)
        acc_param = {"accids": str(accid)} if accid else {"accountNumber": accno}

        summary = self._get_tx_api(
            f"{base_path}/transaction-summary",
            params={
                **acc_param,
                "fromDate": from_date,
                "toDate": to_date,
                "includeCancellations": "false",
            },
        )
        total = summary.get(
            "totalNumberOfTransactions",
            summary.get("numberOfTransactions", 0),
        )

        all_transactions: list[Transaction] = []
        offset = 0
        limit = 800

        while True:
            data = self._get_tx_api(
                f"{base_path}/transactions/page",
                params={
                    **acc_param,
                    "fromDate": from_date,
                    "toDate": to_date,
                    "offset": str(offset),
                    "limit": str(limit),
                    "sort": "ACCOUNTING_DATE",
                    "sortOrder": "DESC",
                    "includeCancellations": "false",
                },
            )

            batch_list = (
                data if isinstance(data, list) else data.get("transactions", [])
            )
            if not batch_list:
                break

            for item in batch_list:
                all_transactions.append(Transaction.model_validate(item))

            _progress(len(all_transactions), total)

            if len(batch_list) < limit:
                break
            offset += limit

        return all_transactions
