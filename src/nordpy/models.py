"""Pydantic v2 models for Nordnet API data."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import AliasChoices, BaseModel, Field, field_validator


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

    instrument_id: int | None = Field(default=None, alias="instrumentId")
    name: str = ""
    symbol: str | None = None
    isin: str | None = Field(
        default=None, validation_alias=AliasChoices("isin", "isin_code")
    )

    model_config = {"populate_by_name": True}


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
    def from_info_response(cls, accid: int, info_data: dict | list) -> AccountBalance:
        """Parse the /api/2/accounts/{accid}/info response."""
        data: dict = info_data[0] if isinstance(info_data, list) and info_data else (info_data if isinstance(info_data, dict) else {})
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


# ── Ledger model ──


class CurrencyLedger(BaseModel):
    """Currency ledger balance for an account."""

    currency: str
    total_balance: MoneyAmount = Field(alias="totalBalance")
    available_balance: MoneyAmount = Field(alias="availableBalance")
    reserved_balance: MoneyAmount = Field(alias="reservedBalance")

    model_config = {"populate_by_name": True}

    @field_validator("total_balance", "available_balance", "reserved_balance", mode="before")
    @classmethod
    def _parse_money(cls, v: object) -> object:
        if isinstance(v, dict):
            return v
        return {"value": 0, "currency": ""}


# ── Reference data models ──


class Country(BaseModel):
    """Country information from Nordnet."""

    country_code: str = Field(alias="countryCode")
    name: str

    model_config = {"populate_by_name": True}


class InstrumentType(BaseModel):
    """Instrument type definition."""

    type_id: int = Field(alias="typeId")
    name: str
    description: str = ""

    model_config = {"populate_by_name": True}

    @field_validator("type_id", mode="before")
    @classmethod
    def _coerce_type_id(cls, v: object) -> int:
        if isinstance(v, str):
            return int(v)
        return v  # type: ignore[return-value]


class Market(BaseModel):
    """Market information."""

    market_id: int = Field(alias="marketId")
    name: str
    country: str = ""
    currency: str = ""
    is_open: bool = Field(default=False, alias="isOpen")

    model_config = {"populate_by_name": True}

    @field_validator("market_id", mode="before")
    @classmethod
    def _coerce_market_id(cls, v: object) -> int:
        if isinstance(v, str):
            return int(v)
        return v  # type: ignore[return-value]


class NewsSource(BaseModel):
    """News source information."""

    source_id: int = Field(alias="sourceId")
    name: str
    language: str = ""

    model_config = {"populate_by_name": True}

    @field_validator("source_id", mode="before")
    @classmethod
    def _coerce_source_id(cls, v: object) -> int:
        if isinstance(v, str):
            return int(v)
        return v  # type: ignore[return-value]


# ── Search result models ──


class InstrumentSearchResult(BaseModel):
    """Base search result for instruments."""

    instrument_id: int = Field(alias="instrumentId")
    name: str = ""
    symbol: str | None = None
    isin: str | None = None
    instrument_type: str = Field(default="", alias="instrumentType")
    market_id: int | None = Field(default=None, alias="marketId")
    market_name: str | None = Field(default=None, alias="marketName")
    currency: str = ""
    last_price: MoneyAmount | None = Field(default=None, alias="lastPrice")

    model_config = {"populate_by_name": True}

    @field_validator("instrument_id", mode="before")
    @classmethod
    def _coerce_instrument_id(cls, v: object) -> int:
        if isinstance(v, str):
            return int(v)
        return v  # type: ignore[return-value]

    @field_validator("last_price", mode="before")
    @classmethod
    def _parse_money_or_none(cls, v: object) -> object:
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        return {"value": 0, "currency": ""}


class BullBearCertificate(InstrumentSearchResult):
    """Bull & Bear certificate search result with leverage info."""

    leverage: float | None = None
    direction: str | None = None  # "BULL" or "BEAR"
    underlying_name: str | None = Field(default=None, alias="underlyingName")
    barrier: float | None = None


class StockSearchResult(InstrumentSearchResult):
    """Stock-specific search result fields."""

    sector: str | None = None
    dividend_yield: float | None = Field(default=None, alias="dividendYield")


class MainSearchResult(BaseModel):
    """Result from Nordnet main search."""

    category: str = ""
    instrument_id: int | None = Field(default=None, alias="instrumentId")
    name: str = ""
    symbol: str | None = None
    isin: str | None = None
    market_name: str | None = Field(default=None, alias="marketName")

    model_config = {"populate_by_name": True}

    @field_validator("instrument_id", mode="before")
    @classmethod
    def _coerce_instrument_id(cls, v: object) -> int | None:
        if v is None:
            return None
        if isinstance(v, str):
            return int(v)
        return v  # type: ignore[return-value]


# ── Enhanced account info ──


class AccountInfo(BaseModel):
    """Extended account information from /info endpoint."""

    accid: int
    account_sum: MoneyAmount = Field(alias="accountSum")
    own_capital: MoneyAmount | None = Field(default=None, alias="ownCapital")
    buying_power: MoneyAmount | None = Field(default=None, alias="buyingPower")
    loan_limit: MoneyAmount | None = Field(default=None, alias="loanLimit")
    trading_power: MoneyAmount | None = Field(default=None, alias="tradingPower")
    collateral: MoneyAmount | None = None

    model_config = {"populate_by_name": True}

    @field_validator(
        "own_capital",
        "buying_power",
        "loan_limit",
        "trading_power",
        "collateral",
        mode="before",
    )
    @classmethod
    def _parse_money_or_none(cls, v: object) -> object:
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        return {"value": 0, "currency": ""}

    @field_validator("account_sum", mode="before")
    @classmethod
    def _parse_account_sum(cls, v: object) -> object:
        if isinstance(v, dict):
            return v
        return {"value": 0, "currency": ""}

    @classmethod
    def from_info_response(cls, accid: int, info_data: dict | list) -> "AccountInfo":
        """Parse the /api/2/accounts/{accid}/info response."""
        data = info_data[0] if isinstance(info_data, list) else info_data
        # Map snake_case API fields to camelCase for model validation
        mapped = {
            "accid": accid,
            "accountSum": data.get("account_sum", {"value": 0, "currency": ""}),
            "ownCapital": data.get("own_capital"),
            "buyingPower": data.get("buying_power"),
            "loanLimit": data.get("loan_limit"),
            "tradingPower": data.get("trading_power"),
            "collateral": data.get("collateral"),
        }
        return cls.model_validate(mapped)


# ── Portfolio chart models ──


class PortfolioValuePoint(BaseModel):
    """A single point in portfolio value history."""

    date: date
    value: float
    currency: str

    # Optional breakdown
    cash_balance: float | None = None
    holdings_value: float | None = None
