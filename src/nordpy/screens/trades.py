"""TradesPane and OrdersPane — DataTables for trades and orders with search/sort."""

from __future__ import annotations

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Input, Static
from textual.worker import get_current_worker

from nordpy.client import NordnetAPIError, NordnetClient
from nordpy.models import Order, Trade


class TradesPane(Vertical):
    """Executed trades DataTable with search and sorting."""

    def __init__(self, *, client: NordnetClient, accid: int) -> None:
        super().__init__()
        self.client = client
        self.accid = accid
        self._all_trades: list[Trade] = []
        self._filtered: list[Trade] = []
        self._sort_column: str | None = None
        self._sort_reverse: bool = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="trades-filter-bar"):
            yield Input(placeholder="Search instruments...", id="trades-search")
        yield DataTable(id="trades-table", cursor_type="row")
        yield Static("", id="trades-empty", classes="empty-state")
        yield Static("Click column headers to sort", classes="hint-text")

    def on_mount(self) -> None:
        table = self.query_one("#trades-table", DataTable)
        table.add_columns(
            "Date/Time",
            "Side",
            "Instrument",
            "Symbol",
            "Volume",
            "Price",
            "Currency",
        )
        self.load_data()

    @work(thread=True)
    def load_data(self) -> None:
        """Fetch trades in a background thread."""
        worker = get_current_worker()
        table = self.query_one("#trades-table", DataTable)
        self.app.call_from_thread(setattr, table, "loading", True)

        try:
            trades = self.client.get_trades(self.accid)
            if worker.is_cancelled:
                return

            self._all_trades = trades
            self._filtered = trades
            self.app.call_from_thread(self._apply_filters)
        except NordnetAPIError as e:
            if not worker.is_cancelled:
                self.app.call_from_thread(
                    self.notify,
                    f"Failed to load trades: {e}",
                    severity="error",
                )
        finally:
            if not worker.is_cancelled:
                self.app.call_from_thread(setattr, table, "loading", False)

    def _apply_filters(self) -> None:
        """Filter and sort trades, then repopulate table."""
        search_input = self.query_one("#trades-search", Input)
        query = search_input.value.strip().lower()

        if query:
            self._filtered = [
                t
                for t in self._all_trades
                if (t.instrument.name and query in t.instrument.name.lower())
                or (t.instrument.symbol and query in t.instrument.symbol.lower())
                or (t.side and query in t.side.lower())
            ]
        else:
            self._filtered = list(self._all_trades)

        if self._sort_column:
            self._filtered = self._sort_trades(self._filtered)

        self._populate_table()

    def _sort_trades(self, trades: list[Trade]) -> list[Trade]:
        """Sort trades by the selected column."""
        key_funcs = {
            "Date/Time": lambda t: t.trade_time,
            "Side": lambda t: t.side.lower(),
            "Instrument": lambda t: t.instrument.name.lower(),
            "Symbol": lambda t: (t.instrument.symbol or "").lower(),
            "Volume": lambda t: t.volume,
            "Price": lambda t: t.price.value,
            "Currency": lambda t: t.price.currency.lower(),
        }

        key_func = key_funcs.get(self._sort_column)
        if key_func:
            return sorted(trades, key=key_func, reverse=self._sort_reverse)
        return trades

    def _populate_table(self) -> None:
        """Populate the DataTable with trade data (main thread)."""
        table = self.query_one("#trades-table", DataTable)
        empty_msg = self.query_one("#trades-empty", Static)
        table.clear()

        if not self._filtered:
            msg = (
                "No trades match the search."
                if self._all_trades
                else "No trades found."
            )
            empty_msg.update(msg)
            table.display = False
            empty_msg.display = True
            return

        empty_msg.display = False
        table.display = True

        for idx, t in enumerate(self._filtered):
            table.add_row(
                t.trade_time.strftime("%Y-%m-%d %H:%M"),
                t.side,
                t.instrument.name,
                t.instrument.symbol or "",
                f"{t.volume:,.2f}",
                f"{t.price.value:,.2f}",
                t.price.currency,
                label=Text(str(idx + 1)),
            )

    @on(Input.Changed, "#trades-search")
    def on_search_changed(self) -> None:
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


class OrdersPane(Vertical):
    """Orders DataTable with search and sorting."""

    def __init__(self, *, client: NordnetClient, accid: int) -> None:
        super().__init__()
        self.client = client
        self.accid = accid
        self._all_orders: list[Order] = []
        self._filtered: list[Order] = []
        self._sort_column: str | None = None
        self._sort_reverse: bool = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="orders-filter-bar"):
            yield Input(placeholder="Search instruments...", id="orders-search")
        yield DataTable(id="orders-table", cursor_type="row")
        yield Static("", id="orders-empty", classes="empty-state")
        yield Static("Click column headers to sort", classes="hint-text")

    def on_mount(self) -> None:
        table = self.query_one("#orders-table", DataTable)
        table.add_columns(
            "Date",
            "Side",
            "Instrument",
            "Symbol",
            "Volume",
            "Price",
            "Currency",
            "State",
        )
        self.load_data()

    @work(thread=True)
    def load_data(self) -> None:
        """Fetch orders in a background thread."""
        worker = get_current_worker()
        table = self.query_one("#orders-table", DataTable)
        self.app.call_from_thread(setattr, table, "loading", True)

        try:
            orders = self.client.get_orders(self.accid)
            if worker.is_cancelled:
                return

            self._all_orders = orders
            self._filtered = orders
            self.app.call_from_thread(self._apply_filters)
        except NordnetAPIError as e:
            if not worker.is_cancelled:
                self.app.call_from_thread(
                    self.notify,
                    f"Failed to load orders: {e}",
                    severity="error",
                )
        finally:
            if not worker.is_cancelled:
                self.app.call_from_thread(setattr, table, "loading", False)

    def _apply_filters(self) -> None:
        """Filter and sort orders, then repopulate table."""
        search_input = self.query_one("#orders-search", Input)
        query = search_input.value.strip().lower()

        if query:
            self._filtered = [
                o
                for o in self._all_orders
                if (o.instrument.name and query in o.instrument.name.lower())
                or (o.instrument.symbol and query in o.instrument.symbol.lower())
                or (o.side and query in o.side.lower())
                or (o.order_state and query in o.order_state.lower())
            ]
        else:
            self._filtered = list(self._all_orders)

        if self._sort_column:
            self._filtered = self._sort_orders(self._filtered)

        self._populate_table()

    def _sort_orders(self, orders: list[Order]) -> list[Order]:
        """Sort orders by the selected column."""
        key_funcs = {
            "Date": lambda o: o.order_date,
            "Side": lambda o: o.side.lower(),
            "Instrument": lambda o: o.instrument.name.lower(),
            "Symbol": lambda o: (o.instrument.symbol or "").lower(),
            "Volume": lambda o: o.volume,
            "Price": lambda o: o.price.value,
            "Currency": lambda o: o.price.currency.lower(),
            "State": lambda o: o.order_state.lower(),
        }

        key_func = key_funcs.get(self._sort_column)
        if key_func:
            return sorted(orders, key=key_func, reverse=self._sort_reverse)
        return orders

    def _populate_table(self) -> None:
        """Populate the DataTable with order data (main thread)."""
        table = self.query_one("#orders-table", DataTable)
        empty_msg = self.query_one("#orders-empty", Static)
        table.clear()

        if not self._filtered:
            msg = (
                "No orders match the search."
                if self._all_orders
                else "No orders found."
            )
            empty_msg.update(msg)
            table.display = False
            empty_msg.display = True
            return

        empty_msg.display = False
        table.display = True

        for idx, o in enumerate(self._filtered):
            table.add_row(
                str(o.order_date),
                o.side,
                o.instrument.name,
                o.instrument.symbol or "",
                f"{o.volume:,.2f}",
                f"{o.price.value:,.2f}",
                o.price.currency,
                o.order_state,
                label=Text(str(idx + 1)),
            )

    @on(Input.Changed, "#orders-search")
    def on_search_changed(self) -> None:
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
