"""HoldingsPane — DataTable showing account positions."""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Static
from textual.worker import get_current_worker

from nordpy.client import NordnetAPIError, NordnetClient
from nordpy.models import Holding


class HoldingsPane(Vertical):
    """Holdings/positions DataTable for a single account."""

    def __init__(self, *, client: NordnetClient, accid: int) -> None:
        super().__init__()
        self.client = client
        self.accid = accid
        self._holdings: list[Holding] = []

    def compose(self) -> ComposeResult:
        yield DataTable(id="holdings-table", cursor_type="row")
        yield Static("", id="holdings-empty", classes="empty-state")

    def on_mount(self) -> None:
        table = self.query_one("#holdings-table", DataTable)
        table.add_columns(
            "Instrument",
            "Symbol",
            "ISIN",
            "Quantity",
            "Acq Price",
            "Currency",
            "Market Value",
            "Gain/Loss",
            "Gain %",
        )
        self.load_data()

    @work(thread=True)
    def load_data(self) -> None:
        """Fetch holdings in a background thread."""
        worker = get_current_worker()
        table = self.query_one("#holdings-table", DataTable)
        self.app.call_from_thread(setattr, table, "loading", True)

        try:
            holdings = self.client.get_holdings(self.accid)
            if worker.is_cancelled:
                return

            self._holdings = holdings
            self.app.call_from_thread(self._populate_table)
        except NordnetAPIError as e:
            if not worker.is_cancelled:
                self.app.call_from_thread(
                    self.notify,
                    f"Failed to load holdings: {e}",
                    severity="error",
                )
        finally:
            if not worker.is_cancelled:
                self.app.call_from_thread(setattr, table, "loading", False)

    def _populate_table(self) -> None:
        """Populate the DataTable with holdings data (main thread)."""
        table = self.query_one("#holdings-table", DataTable)
        empty_msg = self.query_one("#holdings-empty", Static)
        table.clear()

        if not self._holdings:
            empty_msg.update("No holdings in this account.")
            table.display = False
            empty_msg.display = True
            return

        empty_msg.display = False
        table.display = True

        for h in self._holdings:
            table.add_row(
                h.instrument.name,
                h.instrument.symbol or "",
                h.instrument.isin or "",
                f"{h.quantity:,.2f}",
                f"{h.acq_price.value:,.2f}",
                h.acq_price.currency,
                f"{h.market_value.value:,.2f}",
                f"{h.gain_loss:,.2f}",
                f"{h.gain_loss_pct:,.1f}%",
            )
