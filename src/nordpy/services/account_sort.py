"""Pure account-sorting logic — no Textual dependency, fully unit-testable."""

from __future__ import annotations

from enum import StrEnum

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
