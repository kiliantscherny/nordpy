"""HoldingsPane — DataTable showing account positions with sparklines."""

from __future__ import annotations

from datetime import date, timedelta

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Input, ProgressBar, Static
from textual.worker import get_current_worker

from nordpy.client import NordnetAPIError, NordnetClient
from nordpy.models import Holding
from nordpy.screens.instrument_chart import InstrumentChartScreen
from nordpy.services.price_history import PriceHistoryService


# Sparkline characters (8 levels)
SPARK_CHARS = "▁▂▃▄▅▆▇█"

# Blue gradient from dark to bright (8 levels matching SPARK_CHARS)
SPARK_COLORS = [
    "#1a3a5c",
    "#1e5080",
    "#2266a0",
    "#2980b9",
    "#3498db",
    "#5dade2",
    "#85c1e9",
    "#aed6f1",
]


def make_sparkline(values: list[float], width: int = 12) -> Text:
    """Create a Rich Text sparkline with a blue gradient."""
    if not values or len(values) < 2:
        return Text("─" * width, style="dim")

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
        return Text(SPARK_CHARS[4] * len(sampled), style=SPARK_COLORS[4])

    result = Text()
    for v in sampled:
        idx = int((v - min_val) / val_range * 7)
        idx = max(0, min(7, idx))
        result.append(SPARK_CHARS[idx], style=SPARK_COLORS[idx])

    return result


def _styled_gain(value: float, formatted: str) -> Text:
    """Return a Rich Text with green (positive) or red (negative) styling."""
    if value > 0:
        return Text(formatted, style="green")
    elif value < 0:
        return Text(formatted, style="red")
    return Text(formatted, style="dim")


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
        self._sparklines: dict[str, Text] = {}  # symbol -> sparkline Text
        self._price_service = PriceHistoryService()
        self._sort_column: str | None = None
        self._sort_reverse: bool = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="holdings-filter-bar"):
            yield Input(placeholder="Search instruments...", id="holdings-search")
        yield DataTable(id="holdings-table", cursor_type="row")
        yield Static("", id="holdings-empty", classes="empty-state")
        with Vertical(id="trend-bar"):
            yield Static("", id="holdings-status")
            yield ProgressBar(id="trend-progress", total=100, show_eta=False, show_percentage=False)
        yield Static(
            "Press Enter to view chart | Click column headers to sort",
            id="holdings-hint",
            classes="hint-text",
        )

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
        self.query_one("#trend-bar").display = False
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

        # Count symbols that need loading
        symbols_to_load = [
            h for h in self._all_holdings if h.instrument.symbol
        ]
        total = len(symbols_to_load)
        if total == 0:
            return

        self.app.call_from_thread(self._show_progress, total)

        for h in symbols_to_load:
            if worker.is_cancelled:
                return

            symbol = h.instrument.symbol
            if not symbol:
                continue

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
                self.app.call_from_thread(self._update_sparkline_in_table, symbol)

            self.app.call_from_thread(self._advance_progress)

        if not worker.is_cancelled:
            self.app.call_from_thread(self._apply_filters)
            self.app.call_from_thread(self._hide_progress)
            self.app.call_from_thread(
                status.update, f"Loaded {len(self._all_holdings)} holdings"
            )

    def _show_progress(self, total: int) -> None:
        """Show and reset the trend progress bar (main thread)."""
        self._trend_total = total
        self._trend_loaded = 0
        progress = self.query_one("#trend-progress", ProgressBar)
        progress.update(total=total, progress=0)
        self.query_one("#trend-bar").display = True

    def _advance_progress(self) -> None:
        """Advance progress bar by one and update status text (main thread)."""
        self._trend_loaded += 1
        pct = int(self._trend_loaded / self._trend_total * 100) if self._trend_total else 0
        self.query_one("#trend-progress", ProgressBar).advance(1)
        self.query_one("#holdings-status", Static).update(
            f"Loading trends ({self._trend_loaded}/{self._trend_total}) — {pct}%"
        )

    def _hide_progress(self) -> None:
        """Hide the trend progress bar (main thread)."""
        self.query_one("#trend-bar").display = False

    def _update_sparkline_in_table(self, symbol: str) -> None:
        """Update the sparkline for a specific symbol in the table."""
        table = self.query_one("#holdings-table", DataTable)
        sparkline = self._sparklines.get(symbol, Text("─" * 12, style="dim"))

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
            sparkline = self._sparklines.get(
                symbol, Text("─" * 12, style="dim")
            )

            table.add_row(
                h.instrument.name,
                symbol,
                h.instrument.isin or "",
                f"{h.quantity:,.2f}",
                f"{h.acq_price.value:,.2f}",
                f"{h.market_value.value:,.2f}",
                h.market_value.currency,
                _styled_gain(h.gain_loss, f"{h.gain_loss:+,.2f}"),
                _styled_gain(h.gain_loss_pct, f"{h.gain_loss_pct:+.1f}%"),
                sparkline,
                label=Text(str(idx + 1)),
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
