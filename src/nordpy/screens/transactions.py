"""TransactionsPane — DataTable with filter controls for transaction history."""

from __future__ import annotations

from datetime import date

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Input, Select, Static
from textual.worker import get_current_worker

from nordpy.client import NordnetAPIError, NordnetClient
from nordpy.models import Transaction


class TransactionsPane(Vertical):
    """Transaction history DataTable with filter bar and sorting."""

    def __init__(self, *, client: NordnetClient, accno: str, accid: int) -> None:
        super().__init__()
        self.client = client
        self.accno = accno
        self.accid = accid
        self._all_transactions: list[Transaction] = []
        self._filtered: list[Transaction] = []
        self._sort_column: str | None = None
        self._sort_reverse: bool = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="filter-bar"):
            yield Input(placeholder="Instrument name...", id="filter-instrument")
            yield Select(
                [("All Types", "ALL")],
                value="ALL",
                id="filter-type",
                allow_blank=False,
            )
            yield Input(placeholder="From (YYYY-MM-DD)", id="filter-from")
            yield Input(placeholder="To (YYYY-MM-DD)", id="filter-to")
        yield DataTable(id="transactions-table", cursor_type="row")
        yield Static("", id="tx-empty", classes="empty-state")
        yield Static("Click column headers to sort", classes="hint-text")
        yield Static("", id="tx-status")

    def on_mount(self) -> None:
        table = self.query_one("#transactions-table", DataTable)
        table.add_columns(
            "Date",
            "Type",
            "Instrument",
            "ISIN",
            "Qty",
            "Price",
            "Amount",
            "Currency",
            "Balance",
        )
        self.load_data()

    @work(thread=True)
    def load_data(self) -> None:
        """Fetch all transactions in a background thread."""
        worker = get_current_worker()
        table = self.query_one("#transactions-table", DataTable)
        status = self.query_one("#tx-status", Static)
        self.app.call_from_thread(setattr, table, "loading", True)

        def on_progress(fetched: int, total: int) -> None:
            if not worker.is_cancelled:
                self.app.call_from_thread(
                    status.update, f"Loading transactions... {fetched}/{total}"
                )

        try:
            transactions = self.client.get_transactions(
                self.accno, accid=self.accid, on_progress=on_progress
            )
            if worker.is_cancelled:
                return

            self._all_transactions = transactions
            self.app.call_from_thread(self._update_type_filter)
            self.app.call_from_thread(self._apply_filters)
            self.app.call_from_thread(
                status.update,
                f"Loaded {len(transactions)} transactions",
            )
        except NordnetAPIError as e:
            if not worker.is_cancelled:
                self.app.call_from_thread(
                    self.notify,
                    f"Failed to load transactions: {e}",
                    severity="error",
                )
        finally:
            if not worker.is_cancelled:
                self.app.call_from_thread(setattr, table, "loading", False)

    def _update_type_filter(self) -> None:
        """Populate the type filter Select with unique transaction types."""
        types = sorted({t.transaction_type_name for t in self._all_transactions})
        options: list[tuple[str, str]] = [("All Types", "ALL")]
        options.extend((t, t) for t in types)
        type_select = self.query_one("#filter-type", Select)
        type_select.set_options(options)

    def _apply_filters(self) -> None:
        """Filter transactions and repopulate the DataTable."""
        instrument_input = self.query_one("#filter-instrument", Input)
        type_select = self.query_one("#filter-type", Select)
        from_input = self.query_one("#filter-from", Input)
        to_input = self.query_one("#filter-to", Input)

        instrument_q = instrument_input.value.strip().lower()
        type_val = type_select.value
        from_str = from_input.value.strip()
        to_str = to_input.value.strip()

        from_date = _parse_date(from_str)
        to_date = _parse_date(to_str)

        filtered = self._all_transactions

        if instrument_q:
            filtered = [
                t
                for t in filtered
                if t.instrument_name and instrument_q in t.instrument_name.lower()
            ]

        if type_val and type_val != "ALL":
            filtered = [t for t in filtered if t.transaction_type_name == type_val]

        if from_date:
            filtered = [t for t in filtered if t.accounting_date >= from_date]

        if to_date:
            filtered = [t for t in filtered if t.accounting_date <= to_date]

        # Apply sorting
        if self._sort_column:
            filtered = self._sort_transactions(filtered)

        self._filtered = filtered
        self._populate_table()

    def _sort_transactions(self, transactions: list[Transaction]) -> list[Transaction]:
        """Sort transactions by the selected column."""
        key_funcs = {
            "Date": lambda t: t.accounting_date,
            "Type": lambda t: t.transaction_type_name.lower(),
            "Instrument": lambda t: (t.instrument_name or "").lower(),
            "ISIN": lambda t: (t.isin_code or "").lower(),
            "Qty": lambda t: t.quantity or 0,
            "Price": lambda t: t.price.value if t.price else 0,
            "Amount": lambda t: t.amount.value,
            "Currency": lambda t: t.amount.currency.lower(),
            "Balance": lambda t: t.balance.value if t.balance else 0,
        }

        key_func = key_funcs.get(self._sort_column)
        if key_func:
            return sorted(transactions, key=key_func, reverse=self._sort_reverse)
        return transactions

    def _populate_table(self) -> None:
        """Populate the DataTable with filtered transaction data."""
        table = self.query_one("#transactions-table", DataTable)
        empty_msg = self.query_one("#tx-empty", Static)
        table.clear()

        if not self._filtered:
            msg = (
                "No transactions match the current filters."
                if self._all_transactions
                else "No transactions found."
            )
            empty_msg.update(msg)
            table.display = False
            empty_msg.display = True
            return

        empty_msg.display = False
        table.display = True

        for t in self._filtered:
            qty = f"{t.quantity:,.2f}" if t.quantity else ""
            price = f"{t.price.value:,.2f}" if t.price else ""
            amount = f"{t.amount.value:,.2f}"
            currency = t.amount.currency
            balance = f"{t.balance.value:,.2f}" if t.balance else ""
            table.add_row(
                str(t.accounting_date),
                t.transaction_type_name,
                t.instrument_name or "",
                t.isin_code or "",
                qty,
                price,
                amount,
                currency,
                balance,
            )

    @on(Input.Submitted, "#filter-instrument")
    @on(Input.Submitted, "#filter-from")
    @on(Input.Submitted, "#filter-to")
    def on_filter_input_submitted(self) -> None:
        self._apply_filters()

    @on(Input.Changed, "#filter-instrument")
    def on_instrument_changed(self) -> None:
        self._apply_filters()

    @on(Select.Changed, "#filter-type")
    def on_type_changed(self) -> None:
        self._apply_filters()

    @on(DataTable.HeaderSelected)
    def on_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Handle column header click for sorting."""
        column_name = str(event.label)

        if self._sort_column == column_name:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column_name
            self._sort_reverse = False

        self._apply_filters()


def _parse_date(s: str) -> date | None:
    """Parse a YYYY-MM-DD string to a date, or return None."""
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None
