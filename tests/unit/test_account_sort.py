"""Tests for nordpy.services.account_sort — pure sort logic."""

from __future__ import annotations

from nordpy.models import Account, AccountInfo
from nordpy.services.account_sort import (
    DEFAULT_SORT,
    SortField,
    SortSpec,
    account_total,
    sort_accounts,
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


class TestSortAccounts:
    def _setup(self):
        a1 = _acc(1, accno="300", type="ASK", alias="Zeta")
        a2 = _acc(2, accno="100", type="ISK", alias="alpha")
        a3 = _acc(3, accno="200", type="ASK", alias="Beta")
        accounts = [a1, a2, a3]
        infos = {
            1: _info(1, cash=0.0, own_capital=1000.0),
            2: _info(2, cash=0.0, own_capital=3000.0),
            3: _info(3, cash=0.0, own_capital=2000.0),
        }
        holdings = {1: 0.0, 2: 0.0, 3: 0.0}
        return accounts, infos, holdings

    def test_total_descending_is_default_order(self):
        accounts, infos, holdings = self._setup()
        out = sort_accounts(accounts, infos, holdings, DEFAULT_SORT)
        assert [a.accid for a in out] == [2, 3, 1]  # 3000, 2000, 1000

    def test_total_ascending(self):
        accounts, infos, holdings = self._setup()
        spec = SortSpec(field=SortField.TOTAL, descending=False)
        out = sort_accounts(accounts, infos, holdings, spec)
        assert [a.accid for a in out] == [1, 3, 2]

    def test_name_is_case_insensitive(self):
        accounts, infos, holdings = self._setup()
        spec = SortSpec(field=SortField.NAME, descending=False)
        out = sort_accounts(accounts, infos, holdings, spec)
        assert [a.display_name for a in out] == ["alpha", "Beta", "Zeta"]

    def test_accno_is_numeric(self):
        accounts, infos, holdings = self._setup()
        spec = SortSpec(field=SortField.ACCNO, descending=False)
        out = sort_accounts(accounts, infos, holdings, spec)
        assert [a.accno for a in out] == ["100", "200", "300"]

    def test_type_sort_stable_within_ties(self):
        accounts, infos, holdings = self._setup()
        spec = SortSpec(field=SortField.TYPE, descending=False)
        out = sort_accounts(accounts, infos, holdings, spec)
        # "ASK","ASK","ISK"; equal ASK keeps input order (a1 before a3)
        assert [a.accid for a in out] == [1, 3, 2]

    def test_stable_tiebreaker_preserves_input_order(self):
        accounts, infos, holdings = self._setup()
        spec = SortSpec(field=SortField.HOLDINGS, descending=True)
        out = sort_accounts(accounts, infos, holdings, spec)
        assert [a.accid for a in out] == [1, 2, 3]

    def test_does_not_mutate_input(self):
        accounts, infos, holdings = self._setup()
        original = list(accounts)
        sort_accounts(accounts, infos, holdings, DEFAULT_SORT)
        assert accounts == original
