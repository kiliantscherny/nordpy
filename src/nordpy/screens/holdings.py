"""HoldingsPane — DataTable showing account positions with sparklines."""

from __future__ import annotations

from datetime import date, timedelta

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Input, Static
from textual.worker import get_current_worker

from nordpy.client import NordnetAPIError, NordnetClient
from nordpy.models import Holding
from nordpy.screens.instrument_chart import InstrumentChartScreen
from nordpy.services.price_history import PriceHistoryService


# Sparkline characters (8 levels)
SPARK_CHARS = "▁▂▃▄▅▆▇█"


def make_sparkline(values: list[float], width: int = 12) -> str:
    """Create an ASCII sparkline from a list of values."""
    if not values or len(values) < 2:
        return "─" * width

    # Sample values to fit width
    if len(values) > width:
        step = len(values) / width
        sampled = [values[int(i * step)] for i in range(width)]
    else:
        sampled = values

    min_val = min(sampled)
    max_val = max(sampled)
    val_range = max_val - min_val

    if val_range == 0:
        return SPARK_CHARS[4] * len(sampled)

    result = []
    for v in sampled:
        # Normalize to 0-7 range
        idx = int((v - min_val) / val_range * 7)
        idx = max(0, min(7, idx))
        result.append(SPARK_CHARS[idx])

    return "".join(result)


class HoldingsPane(Vertical):
    """Holdings/positions DataTable with sparklines and search.

    Select a row and press Enter to view the instrument's price chart.
    Click column headers to sort.
    """

    BINDINGS = [
        ("enter", "show_chart", "View Chart"),
    ]

    def __init__(self, *, client: NordnetClient, accid: int) -> None:
        super().__init__()
        self.client = client
        self.accid = accid
        self._all_holdings: list[Holding] = []
        self._filtered: list[Holding] = []
        self._row_to_holding: dict[int, Holding] = {}
        self._sparklines: dict[str, str] = {}  # symbol -> sparkline
        self._price_service = PriceHistoryService()
        self._sort_column: str | None = None
        self._sort_reverse: bool = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="holdings-filter-bar"):
            yield Input(placeholder="Search instruments...", id="holdings-search")
        yield DataTable(id="holdings-table", cursor_type="row")
        yield Static("", id="holdings-empty", classes="empty-state")
        yield Static(
            "Press Enter to view chart | Click column headers to sort",
            id="holdings-hint",
            classes="hint-text",
        )
        yield Static("", id="holdings-status")

    def on_mount(self) -> None:
        table = self.query_one("#holdings-table", DataTable)
        table.add_columns(
            "Instrument",
            "Symbol",
            "ISIN",
            "Qty",
            "Acq Price",
            "Market Value",
            "Currency",
            "Gain/Loss",
            "Gain %",
            "3M Trend",
        )
        self.load_data()

    @work(thread=True)
    def load_data(self) -> None:
        """Fetch holdings in a background thread."""
        worker = get_current_worker()
        table = self.query_one("#holdings-table", DataTable)
        status = self.query_one("#holdings-status", Static)
        self.app.call_from_thread(setattr, table, "loading", True)

        try:
            self.app.call_from_thread(status.update, "Loading holdings...")
            holdings = self.client.get_holdings(self.accid)
            if worker.is_cancelled:
                return

            self._all_holdings = holdings
            self._filtered = holdings

            # Render table immediately with placeholder sparklines
            self.app.call_from_thread(self._apply_filters)
            self.app.call_from_thread(
                status.update, f"Loaded {len(holdings)} holdings"
            )

            # Start loading sparklines in background
            if not worker.is_cancelled:
                self.app.call_from_thread(self._start_sparkline_loading)

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

    def _start_sparkline_loading(self) -> None:
        """Start loading sparklines in a separate background worker."""
        self._load_sparklines_async()

    @work(thread=True)
    def _load_sparklines_async(self) -> None:
        """Load 3-month price history for sparklines in background."""
        worker = get_current_worker()
        status = self.query_one("#holdings-status", Static)
        end_date = date.today()
        start_date = end_date - timedelta(days=90)

        loaded = 0

        for h in self._all_holdings:
            if worker.is_cancelled:
                return

            symbol = h.instrument.symbol
            if not symbol:
                continue

            self.app.call_from_thread(
                status.update, f"Loading trends... {symbol}"
            )

            # Get market from ISIN
            market = ""
            if h.instrument.isin and len(h.instrument.isin) >= 2:
                market = h.instrument.isin[:2].upper()

            prices = self._price_service.get_price_history(
                symbol, start_date, end_date, market
            )

            if prices:
                sorted_prices = [p for _, p in sorted(prices.items())]
                self._sparklines[symbol] = make_sparkline(sorted_prices)
                # Update table with new sparkline
                self.app.call_from_thread(self._update_sparkline_in_table, symbol)

            loaded += 1

        if not worker.is_cancelled:
            # Refresh the table to show all sparklines
            self.app.call_from_thread(self._apply_filters)
            self.app.call_from_thread(
                status.update, f"Loaded {len(self._all_holdings)} holdings"
            )

    def _update_sparkline_in_table(self, symbol: str) -> None:
        """Update the sparkline for a specific symbol in the table."""
        table = self.query_one("#holdings-table", DataTable)
        sparkline = self._sparklines.get(symbol, "─" * 12)

        # Find the row with this symbol and update the sparkline column
        row_keys = list(table.rows.keys())
        for row_idx, holding in self._row_to_holding.items():
            if holding.instrument.symbol == symbol:
                try:
                    row_key = row_keys[row_idx]
                    table.update_cell(row_key, "3M Trend", sparkline)
                except (IndexError, Exception):
                    pass  # Row may have been removed due to filtering
                break

    def _apply_filters(self) -> None:
        """Filter and sort holdings, then repopulate table."""
        search_input = self.query_one("#holdings-search", Input)
        query = search_input.value.strip().lower()

        if query:
            self._filtered = [
                h
                for h in self._all_holdings
                if (h.instrument.name and query in h.instrument.name.lower())
                or (h.instrument.symbol and query in h.instrument.symbol.lower())
                or (h.instrument.isin and query in h.instrument.isin.lower())
            ]
        else:
            self._filtered = list(self._all_holdings)

        # Apply sorting
        if self._sort_column:
            self._filtered = self._sort_holdings(self._filtered)

        self._populate_table()

    def _sort_holdings(self, holdings: list[Holding]) -> list[Holding]:
        """Sort holdings by the selected column."""
        key_funcs = {
            "Instrument": lambda h: h.instrument.name.lower(),
            "Symbol": lambda h: (h.instrument.symbol or "").lower(),
            "ISIN": lambda h: (h.instrument.isin or "").lower(),
            "Qty": lambda h: h.quantity,
            "Acq Price": lambda h: h.acq_price.value,
            "Market Value": lambda h: h.market_value.value,
            "Currency": lambda h: h.market_value.currency.lower(),
            "Gain/Loss": lambda h: h.gain_loss,
            "Gain %": lambda h: h.gain_loss_pct,
        }

        key_func = key_funcs.get(self._sort_column)
        if key_func:
            return sorted(holdings, key=key_func, reverse=self._sort_reverse)
        return holdings

    def _populate_table(self) -> None:
        """Populate the DataTable with holdings data (main thread)."""
        table = self.query_one("#holdings-table", DataTable)
        empty_msg = self.query_one("#holdings-empty", Static)
        hint = self.query_one("#holdings-hint", Static)
        table.clear()
        self._row_to_holding.clear()

        if not self._filtered:
            msg = (
                "No holdings match the search."
                if self._all_holdings
                else "No holdings in this account."
            )
            empty_msg.update(msg)
            table.display = False
            empty_msg.display = True
            hint.display = False
            return

        empty_msg.display = False
        table.display = True
        hint.display = True

        for idx, h in enumerate(self._filtered):
            symbol = h.instrument.symbol or ""
            sparkline = self._sparklines.get(symbol, "─" * 12)

            table.add_row(
                h.instrument.name,
                symbol,
                h.instrument.isin or "",
                f"{h.quantity:,.2f}",
                f"{h.acq_price.value:,.2f}",
                f"{h.market_value.value:,.2f}",
                h.market_value.currency,
                f"{h.gain_loss:+,.2f}",
                f"{h.gain_loss_pct:+.1f}%",
                sparkline,
            )
            self._row_to_holding[idx] = h

    @on(Input.Changed, "#holdings-search")
    def on_search_changed(self) -> None:
        self._apply_filters()

    @on(DataTable.HeaderSelected)
    def on_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Handle column header click for sorting."""
        column_name = str(event.label)

        # Skip sorting on sparkline column
        if column_name == "3M Trend":
            return

        if self._sort_column == column_name:
            # Toggle sort direction
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column_name
            self._sort_reverse = False

        self._apply_filters()

    def action_show_chart(self) -> None:
        """Show price chart for the selected holding."""
        table = self.query_one("#holdings-table", DataTable)
        if table.cursor_row is not None and table.cursor_row in self._row_to_holding:
            holding = self._row_to_holding[table.cursor_row]
            if holding.instrument.symbol:
                self.app.push_screen(InstrumentChartScreen(holding))
            else:
                self.notify(
                    "No symbol available for this instrument", severity="warning"
                )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle double-click on a row."""
        row_idx = event.cursor_row
        if row_idx in self._row_to_holding:
            holding = self._row_to_holding[row_idx]
            if holding.instrument.symbol:
                self.app.push_screen(InstrumentChartScreen(holding))
            else:
                self.notify(
                    "No symbol available for this instrument", severity="warning"
                )
