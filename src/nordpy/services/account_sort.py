"""Pure account-sorting logic — no Textual dependency, fully unit-testable."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from nordpy.models import Account, AccountInfo


class SortField(StrEnum):
    """Field an account list can be ordered by."""

    TOTAL = "total"
    HOLDINGS = "holdings"
    CASH = "cash"
    NAME = "name"
    TYPE = "type"
    ACCNO = "accno"


class SortSpec(BaseModel):
    """A chosen account sort: which field, which direction."""

    field: SortField
    descending: bool


DEFAULT_SORT = SortSpec(field=SortField.TOTAL, descending=True)


def account_total(
    account: Account,
    info: AccountInfo | None,
    holdings_value: float,
) -> float:
    """Total account worth in the account's base currency.

    Prefers Nordnet's authoritative ``own_capital`` figure; falls back
    to cash balance + holdings only when ``own_capital`` is absent.
    Missing ``info`` entirely yields ``0.0`` (sorts last under the
    default descending order).
    """
    if info is None:
        return 0.0
    if info.own_capital is not None:
        return info.own_capital.value
    return info.account_sum.value + holdings_value


def sort_accounts(
    accounts: list[Account],
    infos: dict[int, AccountInfo],
    holdings_values: dict[int, float],
    spec: SortSpec,
) -> list[Account]:
    """Return a new list of ``accounts`` ordered per ``spec``.

    Stable: accounts with equal sort keys keep their original input
    order in both directions (Python's sort reverses the comparison,
    not the run of equal elements), giving a deterministic tiebreaker.
    Does not mutate ``accounts``.
    """

    def key(acc: Account) -> Any:
        info = infos.get(acc.accid)
        if spec.field is SortField.TOTAL:
            return account_total(acc, info, holdings_values.get(acc.accid, 0.0))
        if spec.field is SortField.HOLDINGS:
            return holdings_values.get(acc.accid, 0.0)
        if spec.field is SortField.CASH:
            return info.account_sum.value if info else 0.0
        if spec.field is SortField.NAME:
            return acc.display_name.casefold()
        if spec.field is SortField.TYPE:
            return acc.type.casefold()
        return int(acc.accno)  # SortField.ACCNO

    return sorted(accounts, key=key, reverse=spec.descending)
