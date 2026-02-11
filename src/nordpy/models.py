"""Pydantic v2 models for Nordnet API data."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


class MoneyAmount(BaseModel):
    """Monetary value with currency. Handles both API field name variants."""

    value: float
    currency: str = Field(default="", validation_alias="currencyCode")

    @field_validator("currency", mode="before")
    @classmethod
    def _coerce_currency(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v)


class NoteInfo(BaseModel):
    """Fee breakdown for a transaction."""

    commission: float | None = None
    charge: float | None = None
    foreign_charge: float | None = Field(default=None, alias="foreignCharge")
    handling_fee: float | None = Field(default=None, alias="handlingFee")
    stamp_tax: float | None = Field(default=None, alias="stampTax")

    @field_validator("*", mode="before")
    @classmethod
    def _unwrap_value_dict(cls, v: object) -> object:
        if isinstance(v, dict) and "value" in v:
            return dict.get(v, "value")
        return v


class Instrument(BaseModel):
    """A financial instrument (stock, ETF, fund, etc.)."""

    name: str = ""
    symbol: str | None = None
    isin: str | None = None


# ── Account models (US1) ──


class Account(BaseModel):
    """A Nordnet investment account."""

    accid: int
    accno: str
    type: str
    alias: str | None = None

    @field_validator("accno", mode="before")
    @classmethod
    def _coerce_accno(cls, v: object) -> str:
        return str(v)

    @property
    def display_name(self) -> str:
        return self.alias or self.type


class AccountBalance(BaseModel):
    """Balance information for a specific account."""

    accid: int
    balance: MoneyAmount

    @classmethod
    def from_info_response(cls, accid: int, info_data: dict) -> AccountBalance:
        """Parse the /api/2/accounts/{accid}/info response."""
        data = info_data
        if isinstance(data, list) and len(data) > 0:
            data = data[0]
        account_sum = data.get("account_sum", {"value": 0, "currency": ""})
        return cls(accid=accid, balance=MoneyAmount.model_validate(account_sum))


# ── Holding model (US2) ──


class Holding(BaseModel):
    """A position (security holding) in an account."""

    instrument: Instrument
    quantity: float = Field(alias="qty")
    acq_price: MoneyAmount
    market_value: MoneyAmount

    model_config = {"populate_by_name": True}

    @field_validator("acq_price", "market_value", mode="before")
    @classmethod
    def _parse_money(cls, v: object) -> object:
        if isinstance(v, dict):
            return v
        return {"value": 0, "currency": ""}

    @property
    def gain_loss(self) -> float:
        return self.market_value.value - (self.acq_price.value * self.quantity)

    @property
    def gain_loss_pct(self) -> float:
        cost = self.acq_price.value * self.quantity
        if cost == 0:
            return 0.0
        return (self.gain_loss / cost) * 100


# ── Transaction model (US3) ──


class Transaction(BaseModel):
    """A historical financial event on an account."""

    transaction_id: str = Field(alias="transactionId")
    accounting_date: date = Field(alias="accountingDate")
    settlement_date: date | None = Field(default=None, alias="settlementDate")
    business_date: date | None = Field(default=None, alias="businessDate")
    transaction_type_name: str = Field(alias="transactionTypeName")
    transaction_type_code: str = Field(default="", alias="transactionTypeCode")
    instrument_name: str | None = Field(default=None, alias="instrumentName")
    instrument_short_name: str | None = Field(default=None, alias="instrumentShortName")
    isin_code: str | None = Field(default=None, alias="isinCode")
    quantity: float | None = None
    price: MoneyAmount | None = None
    amount: MoneyAmount
    balance: MoneyAmount | None = None
    total_charges: MoneyAmount | None = Field(default=None, alias="totalCharges")
    note_info: NoteInfo | None = Field(default=None, alias="noteInfo")
    contract_note_number: str | None = Field(default=None, alias="contractNoteNumber")

    model_config = {"populate_by_name": True}

    @field_validator("contract_note_number", mode="before")
    @classmethod
    def _coerce_contract_note(cls, v: object) -> str | None:
        if v is None:
            return None
        return str(v)

    @field_validator("price", "amount", "balance", "total_charges", mode="before")
    @classmethod
    def _parse_money_or_none(cls, v: object) -> object:
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        return {"value": 0, "currency": ""}


# ── Trade model (US5) ──


class Trade(BaseModel):
    """An executed trade on an account."""

    trade_time: datetime = Field(alias="trade_time")
    side: str
    instrument: Instrument
    volume: float
    price: MoneyAmount

    model_config = {"populate_by_name": True}

    @field_validator("price", mode="before")
    @classmethod
    def _parse_money(cls, v: object) -> object:
        if isinstance(v, dict):
            return v
        return {"value": 0, "currency": ""}


# ── Order model (US5) ──


class Order(BaseModel):
    """A pending or historical order on an account."""

    order_date: date = Field(alias="order_date")
    side: str
    instrument: Instrument
    volume: float
    price: MoneyAmount
    order_state: str = Field(alias="order_state")

    model_config = {"populate_by_name": True}

    @field_validator("price", mode="before")
    @classmethod
    def _parse_money(cls, v: object) -> object:
        if isinstance(v, dict):
            return v
        return {"value": 0, "currency": ""}
