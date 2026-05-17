"""Tests for nordpy.services.account_sort — pure sort logic."""

from __future__ import annotations

from nordpy.models import Account, AccountInfo
from nordpy.services.account_sort import (
    DEFAULT_SORT,
    SortField,
    SortSpec,
    account_total,
)


def _acc(accid: int, accno: str = "100", type: str = "ASK",
         alias: str | None = None) -> Account:
    return Account(accid=accid, accno=accno, type=type, alias=alias)


def _info(accid: int, cash: float, own_capital: float | None = None) -> AccountInfo:
    # AccountInfo's before-validators zero out non-dict input, so build it
    # the way the client does: from_info_response with raw dicts.
    data: dict = {"account_sum": {"value": cash, "currency": "DKK"}}
    if own_capital is not None:
        data["own_capital"] = {"value": own_capital, "currency": "DKK"}
    return AccountInfo.from_info_response(accid, data)


class TestAccountTotal:
    def test_prefers_own_capital(self):
        info = _info(1, cash=1000.0, own_capital=5000.0)
        assert account_total(_acc(1), info, holdings_value=999.0) == 5000.0

    def test_falls_back_to_cash_plus_holdings(self):
        info = _info(1, cash=1000.0, own_capital=None)
        assert account_total(_acc(1), info, holdings_value=2500.0) == 3500.0

    def test_missing_info_is_zero(self):
        assert account_total(_acc(1), None, holdings_value=123.0) == 0.0

    def test_real_zero_own_capital_does_not_fall_back(self):
        info = _info(1, cash=1000.0, own_capital=0.0)
        assert account_total(_acc(1), info, holdings_value=2500.0) == 0.0


class TestDefaultSort:
    def test_default_is_total_descending(self):
        assert DEFAULT_SORT == SortSpec(field=SortField.TOTAL, descending=True)
