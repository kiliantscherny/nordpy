"""TradesPane and OrdersPane — DataTables for trades and orders."""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Static
from textual.worker import get_current_worker

from nordpy.client import NordnetAPIError, NordnetClient
from nordpy.models import Order, Trade


class TradesPane(Vertical):
    """Executed trades DataTable for a single account."""

    def __init__(self, *, client: NordnetClient, accid: int) -> None:
        super().__init__()
        self.client = client
        self.accid = accid
        self._trades: list[Trade] = []

    def compose(self) -> ComposeResult:
        yield DataTable(id="trades-table", cursor_type="row")
        yield Static("", id="trades-empty", classes="empty-state")

    def on_mount(self) -> None:
        table = self.query_one("#trades-table", DataTable)
        table.add_columns(
            "Date/Time",
            "Side",
            "Instrument",
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

            self._trades = trades
            self.app.call_from_thread(self._populate_table)
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

    def _populate_table(self) -> None:
        """Populate the DataTable with trade data (main thread)."""
        table = self.query_one("#trades-table", DataTable)
        empty_msg = self.query_one("#trades-empty", Static)
        table.clear()

        if not self._trades:
            empty_msg.update("No trades found.")
            table.display = False
            empty_msg.display = True
            return

        empty_msg.display = False
        table.display = True

        for t in self._trades:
            table.add_row(
                t.trade_time.strftime("%Y-%m-%d %H:%M"),
                t.side,
                t.instrument.name,
                f"{t.volume:,.2f}",
                f"{t.price.value:,.2f}",
                t.price.currency,
            )


class OrdersPane(Vertical):
    """Orders DataTable for a single account."""

    def __init__(self, *, client: NordnetClient, accid: int) -> None:
        super().__init__()
        self.client = client
        self.accid = accid
        self._orders: list[Order] = []

    def compose(self) -> ComposeResult:
        yield DataTable(id="orders-table", cursor_type="row")
        yield Static("", id="orders-empty", classes="empty-state")

    def on_mount(self) -> None:
        table = self.query_one("#orders-table", DataTable)
        table.add_columns(
            "Date",
            "Side",
            "Instrument",
            "Volume",
            "Price",
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

            self._orders = orders
            self.app.call_from_thread(self._populate_table)
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

    def _populate_table(self) -> None:
        """Populate the DataTable with order data (main thread)."""
        table = self.query_one("#orders-table", DataTable)
        empty_msg = self.query_one("#orders-empty", Static)
        table.clear()

        if not self._orders:
            empty_msg.update("No orders found.")
            table.display = False
            empty_msg.display = True
            return

        empty_msg.display = False
        table.display = True

        for o in self._orders:
            table.add_row(
                str(o.order_date),
                o.side,
                o.instrument.name,
                f"{o.volume:,.2f}",
                f"{o.price.value:,.2f}",
                o.order_state,
            )
