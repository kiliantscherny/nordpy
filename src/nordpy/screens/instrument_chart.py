"""InstrumentChartScreen — Shows price history for a single instrument."""

from __future__ import annotations

from datetime import date, timedelta

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Select, Static
from textual.worker import get_current_worker
from textual_plotext import PlotextPlot

from nordpy.models import Holding
from nordpy.services.price_history import PriceHistoryService


class InstrumentChartScreen(ModalScreen[None]):
    """Modal screen showing price history for a single instrument."""

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("q", "dismiss", "Close"),
    ]

    CSS = """
    InstrumentChartScreen {
        align: center middle;
    }

    #instrument-chart-container {
        width: 90%;
        height: 85%;
        background: $surface;
        border: thick $primary 60%;
        padding: 1;
    }

    #instrument-chart-header {
        height: 3;
        dock: top;
    }

    #instrument-chart-title {
        width: 1fr;
        text-align: center;
        text-style: bold;
        color: $primary;
    }

    #instrument-chart-close {
        width: auto;
        min-width: 10;
    }

    #instrument-chart-controls {
        height: 3;
        dock: top;
        align: center middle;
    }

    #instrument-range-select {
        width: 20;
    }

    #instrument-chart {
        height: 1fr;
    }

    #instrument-chart-status {
        height: 1;
        dock: bottom;
        text-align: center;
        color: $text-muted;
    }

    #instrument-chart-info {
        height: 2;
        dock: bottom;
        text-align: center;
        color: $secondary;
    }
    """

    RANGES: list[tuple[str, str]] = [
        ("1 Year", "1y"),
        ("6 Months", "6m"),
        ("3 Months", "3m"),
        ("1 Month", "1m"),
        ("2 Weeks", "2w"),
    ]

    def __init__(self, holding: Holding) -> None:
        super().__init__()
        self.holding = holding
        self._prices: dict[date, float] = {}
        self._selected_range = "1y"
        self._price_service = PriceHistoryService()

    def compose(self) -> ComposeResult:
        with Vertical(id="instrument-chart-container"):
            with Horizontal(id="instrument-chart-header"):
                yield Static(
                    f"{self.holding.instrument.name} ({self.holding.instrument.symbol or 'N/A'})",
                    id="instrument-chart-title",
                )
                yield Button("Close [Esc]", id="instrument-chart-close", variant="default")

            with Horizontal(id="instrument-chart-controls"):
                yield Select(
                    self.RANGES,
                    value="1y",
                    id="instrument-range-select",
                    allow_blank=False,
                )

            yield PlotextPlot(id="instrument-chart")
            yield Static("", id="instrument-chart-info")
            yield Static("", id="instrument-chart-status")

    def on_mount(self) -> None:
        self._load_prices()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "instrument-chart-close":
            self.dismiss()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "instrument-range-select":
            self._selected_range = str(event.value)
            self._render_chart()

    @work(thread=True)
    def _load_prices(self) -> None:
        """Fetch price history in background."""
        worker = get_current_worker()
        status = self.query_one("#instrument-chart-status", Static)

        self.app.call_from_thread(status.update, "Loading price history...")

        symbol = self.holding.instrument.symbol
        if not symbol:
            self.app.call_from_thread(
                status.update,
                "No symbol available for this instrument",
            )
            return

        # Determine market from ISIN country code
        market = ""
        isin = self.holding.instrument.isin
        if isin and len(isin) >= 2:
            country = isin[:2].upper()
            market = country

        # Fetch 1 year of data
        end_date = date.today()
        start_date = end_date - timedelta(days=365)

        try:
            self._prices = self._price_service.get_price_history(
                symbol, start_date, end_date, market
            )

            if worker.is_cancelled:
                return

            if self._prices:
                self.app.call_from_thread(self._render_chart)
                self.app.call_from_thread(status.update, f"Loaded {len(self._prices)} price points")
            else:
                self.app.call_from_thread(
                    status.update,
                    f"No price data found for {symbol}",
                )
        except Exception as e:
            if not worker.is_cancelled:
                self.app.call_from_thread(
                    status.update,
                    f"Error loading prices: {e}",
                )

    def _render_chart(self) -> None:
        """Render the price chart."""
        chart = self.query_one("#instrument-chart", PlotextPlot)
        info = self.query_one("#instrument-chart-info", Static)

        if not self._prices:
            return

        # Filter by selected range
        filtered = self._filter_by_range(self._prices)

        if not filtered:
            info.update("No data in selected range")
            return

        # Sort by date
        sorted_data = sorted(filtered.items())
        dates = [d.strftime("%d-%m-%Y") for d, _ in sorted_data]
        values = [v for _, v in sorted_data]

        # Calculate stats
        current = values[-1]
        start_val = values[0]
        change = current - start_val
        change_pct = (change / start_val * 100) if start_val else 0
        high = max(values)
        low = min(values)

        currency = self.holding.market_value.currency
        info.update(
            f"Current: {current:,.2f} {currency} | Change: {change:+,.2f} ({change_pct:+.1f}%) | "
            f"High: {high:,.2f} | Low: {low:,.2f}"
        )

        # Update chart
        plt = chart.plt
        plt.clear_figure()
        plt.title(f"{self.holding.instrument.symbol} Price History")
        plt.xlabel("Date")
        plt.ylabel(f"Price ({self.holding.market_value.currency})")

        # Use indices for x-axis
        x = [float(i) for i in range(len(dates))]
        plt.plot(x, values, marker="braille")

        # Set x-axis labels
        if len(dates) > 8:
            step = max(1, len(dates) // 6)
            xticks = x[::step]
            xlabels = dates[::step]
            plt.xticks(xticks, xlabels)
        elif dates:
            plt.xticks(x, dates)

        chart.refresh()

    def _filter_by_range(self, prices: dict[date, float]) -> dict[date, float]:
        """Filter prices by selected time range."""
        today = date.today()
        cutoff_map = {
            "1y": today - timedelta(days=365),
            "6m": today - timedelta(days=182),
            "3m": today - timedelta(days=91),
            "1m": today - timedelta(days=30),
            "2w": today - timedelta(days=14),
        }

        cutoff = cutoff_map.get(self._selected_range, date.min)
        return {d: p for d, p in prices.items() if d >= cutoff}
