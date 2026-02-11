"""Tests for nordpy.models — Pydantic validators, coercion, computed properties."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from nordpy.models import (
    Account,
    AccountBalance,
    Holding,
    Instrument,
    MoneyAmount,
    NoteInfo,
    Order,
    Trade,
    Transaction,
)


# ── MoneyAmount ──


class TestMoneyAmount:
    def test_basic_construction(self):
        """MoneyAmount uses validation_alias='currencyCode', so currency must
        be passed as currencyCode during validation/construction."""
        m = MoneyAmount.model_validate({"value": 100.0, "currencyCode": "DKK"})
        assert m.value == 100.0
        assert m.currency == "DKK"

    def test_currency_code_alias(self):
        """The API sometimes sends 'currencyCode' instead of 'currency'."""
        m = MoneyAmount.model_validate({"value": 50.0, "currencyCode": "USD"})
        assert m.currency == "USD"

    def test_none_currency_coerced_to_empty_string(self):
        m = MoneyAmount.model_validate({"value": 0.0, "currency": None})
        assert m.currency == ""

    def test_missing_currency_defaults_to_empty(self):
        m = MoneyAmount.model_validate({"value": 0.0})
        assert m.currency == ""


# ── NoteInfo ──


class TestNoteInfo:
    def test_unwrap_value_dict(self):
        """NoteInfo fields can arrive as {"value": 1.5} dicts from the API."""
        note = NoteInfo.model_validate({"commission": {"value": 1.5}, "charge": 2.0})
        assert note.commission == 1.5
        assert note.charge == 2.0

    def test_none_fields(self):
        note = NoteInfo()
        assert note.commission is None
        assert note.foreign_charge is None

    def test_alias_fields(self):
        note = NoteInfo.model_validate(
            {"foreignCharge": {"value": 3.0}, "handlingFee": 0.5, "stampTax": 0.1}
        )
        assert note.foreign_charge == 3.0
        assert note.handling_fee == 0.5
        assert note.stamp_tax == 0.1


# ── Instrument ──


class TestInstrument:
    def test_defaults(self):
        inst = Instrument()
        assert inst.name == ""
        assert inst.symbol is None
        assert inst.isin is None

    def test_full_construction(self):
        inst = Instrument(name="Apple", symbol="AAPL", isin="US0378331005")
        assert inst.name == "Apple"
        assert inst.symbol == "AAPL"


# ── Account ──


class TestAccount:
    def test_accno_coerced_from_int(self):
        """Nordnet API returns accno as int; validator coerces to str."""
        acc = Account.model_validate({"accid": 1, "accno": 42333260, "type": "ASK"})
        assert acc.accno == "42333260"
        assert isinstance(acc.accno, str)

    def test_display_name_with_alias(self):
        acc = Account(accid=1, accno="123", type="ASK", alias="My Depot")
        assert acc.display_name == "My Depot"

    def test_display_name_fallback_to_type(self):
        acc = Account(accid=1, accno="123", type="ASK")
        assert acc.display_name == "ASK"

    def test_display_name_empty_alias(self):
        acc = Account(accid=1, accno="123", type="ASK", alias="")
        assert acc.display_name == "ASK"


# ── AccountBalance ──


class TestAccountBalance:
    def test_from_info_response_dict(self):
        """account_sum uses 'currency' key, but MoneyAmount only accepts
        'currencyCode' via validation_alias — currency defaults to ''."""
        data = {"account_sum": {"value": 5000.0, "currency": "DKK"}}
        bal = AccountBalance.from_info_response(1, data)
        assert bal.accid == 1
        assert bal.balance.value == 5000.0
        assert bal.balance.currency == ""  # 'currency' key not recognized by alias

    def test_from_info_response_list(self):
        """Some endpoints return a list instead of a single dict."""
        data = [{"account_sum": {"value": 7500.0, "currency": "SEK"}}]
        bal = AccountBalance.from_info_response(2, data)
        assert bal.balance.value == 7500.0

    def test_from_info_response_missing_account_sum(self):
        data = {}
        bal = AccountBalance.from_info_response(1, data)
        assert bal.balance.value == 0
        assert bal.balance.currency == ""


# ── Holding ──


class TestHolding:
    def test_qty_alias(self):
        h = Holding.model_validate(
            {
                "instrument": {"name": "X"},
                "qty": 5.0,
                "acq_price": {"value": 100.0, "currency": "DKK"},
                "market_value": {"value": 120.0, "currency": "DKK"},
            }
        )
        assert h.quantity == 5.0

    def test_gain_loss(self, sample_holding):
        # acq_price=150, qty=10, market_value=175 (from fixture via model_validate)
        expected = sample_holding.market_value.value - (
            sample_holding.acq_price.value * sample_holding.quantity
        )
        assert sample_holding.gain_loss == expected

    def test_gain_loss_pct(self, sample_holding):
        cost = sample_holding.acq_price.value * sample_holding.quantity
        expected = (sample_holding.gain_loss / cost) * 100
        assert sample_holding.gain_loss_pct == pytest.approx(expected)

    def test_gain_loss_pct_zero_cost(self):
        h = Holding(
            instrument=Instrument(name="Free"),
            qty=10.0,
            acq_price=MoneyAmount(value=0.0, currency="DKK"),
            market_value=MoneyAmount(value=50.0, currency="DKK"),
        )
        assert h.gain_loss_pct == 0.0

    def test_parse_money_non_dict(self):
        """Non-dict values for acq_price/market_value get default 0."""
        h = Holding.model_validate(
            {
                "instrument": {"name": "X"},
                "qty": 1.0,
                "acq_price": "invalid",
                "market_value": "invalid",
            }
        )
        assert h.acq_price.value == 0
        assert h.market_value.value == 0


# ── Transaction ──


class TestTransaction:
    def test_field_aliases(self, transaction_response_dict):
        tx = Transaction.model_validate(transaction_response_dict)
        assert tx.transaction_id == "tx-001"
        assert tx.accounting_date == date(2024, 1, 15)
        assert tx.transaction_type_name == "BUY"

    def test_contract_note_number_coerced_from_int(self):
        data = {
            "transactionId": "tx-002",
            "accountingDate": "2024-06-01",
            "transactionTypeName": "BUY",
            "amount": {"value": -100.0},
            "contractNoteNumber": 2076145332,
        }
        tx = Transaction.model_validate(data)
        assert tx.contract_note_number == "2076145332"
        assert isinstance(tx.contract_note_number, str)

    def test_contract_note_number_none(self):
        data = {
            "transactionId": "tx-003",
            "accountingDate": "2024-01-01",
            "transactionTypeName": "DEPOSIT",
            "amount": {"value": 1000.0},
            "contractNoteNumber": None,
        }
        tx = Transaction.model_validate(data)
        assert tx.contract_note_number is None

    def test_optional_fields_default(self):
        data = {
            "transactionId": "tx-004",
            "accountingDate": "2024-01-01",
            "transactionTypeName": "DEPOSIT",
            "amount": {"value": 1000.0},
        }
        tx = Transaction.model_validate(data)
        assert tx.settlement_date is None
        assert tx.instrument_name is None
        assert tx.quantity is None
        assert tx.price is None
        assert tx.balance is None
        assert tx.total_charges is None
        assert tx.note_info is None

    def test_parse_money_or_none_with_none(self):
        data = {
            "transactionId": "tx-005",
            "accountingDate": "2024-01-01",
            "transactionTypeName": "X",
            "amount": {"value": 0.0},
            "price": None,
        }
        tx = Transaction.model_validate(data)
        assert tx.price is None

    def test_parse_money_or_none_non_dict(self):
        data = {
            "transactionId": "tx-006",
            "accountingDate": "2024-01-01",
            "transactionTypeName": "X",
            "amount": {"value": 0.0},
            "price": "invalid",
        }
        tx = Transaction.model_validate(data)
        assert tx.price.value == 0


# ── Trade ──


class TestTrade:
    def test_basic_construction(self):
        t = Trade.model_validate(
            {
                "trade_time": "2024-06-15T10:30:00",
                "side": "BUY",
                "instrument": {"name": "Apple", "symbol": "AAPL"},
                "volume": 5.0,
                "price": {"value": 200.0, "currency": "USD"},
            }
        )
        assert t.side == "BUY"
        assert t.volume == 5.0
        assert isinstance(t.trade_time, datetime)

    def test_price_non_dict(self):
        t = Trade.model_validate(
            {
                "trade_time": "2024-01-01T00:00:00",
                "side": "SELL",
                "instrument": {"name": "X"},
                "volume": 1.0,
                "price": "bad",
            }
        )
        assert t.price.value == 0


# ── Order ──


class TestOrder:
    def test_basic_construction(self):
        o = Order.model_validate(
            {
                "order_date": "2024-06-15",
                "side": "BUY",
                "instrument": {"name": "Apple"},
                "volume": 10.0,
                "price": {"value": 150.0, "currency": "USD"},
                "order_state": "FILLED",
            }
        )
        assert o.side == "BUY"
        assert o.order_state == "FILLED"
        assert isinstance(o.order_date, date)

    def test_price_non_dict(self):
        o = Order.model_validate(
            {
                "order_date": "2024-01-01",
                "side": "SELL",
                "instrument": {"name": "X"},
                "volume": 1.0,
                "price": "bad",
                "order_state": "CANCELLED",
            }
        )
        assert o.price.value == 0
