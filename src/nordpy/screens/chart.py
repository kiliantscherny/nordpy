"""PortfolioChartPane — Terminal chart showing portfolio value over time."""

from __future__ import annotations

from datetime import date, timedelta

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Select, Static
from textual.worker import get_current_worker
from textual_plotext import PlotextPlot

from nordpy.client import NordnetAPIError, NordnetClient
from nordpy.models import Holding, PortfolioValuePoint, Transaction
from nordpy.services.price_history import PortfolioNAVService


class PortfolioChartPane(Vertical):
    """Portfolio value chart pane for the account detail view."""

    # Time range options
    RANGES: list[tuple[str, str]] = [
        ("All Time", "all"),
        ("1 Year", "1y"),
        ("6 Months", "6m"),
        ("3 Months", "3m"),
        ("1 Month", "1m"),
    ]

    def __init__(
        self,
        *,
        client: NordnetClient,
        accno: str,
        accid: int,
    ) -> None:
        super().__init__()
        self.client = client
        self.accno = accno
        self.accid = accid
        self._transactions: list[Transaction] = []
        self._holdings: list[Holding] = []
        self._history: list[PortfolioValuePoint] = []
        self._selected_range = "all"

    def compose(self) -> ComposeResult:
        with Horizontal(id="chart-controls"):
            yield Select(
                self.RANGES,
                value="all",
                id="range-select",
                allow_blank=False,
            )

        yield PlotextPlot(id="portfolio-chart")
        yield Static("", id="chart-status")
        yield Static("", id="chart-empty", classes="empty-state")

    def on_mount(self) -> None:
        self.load_data()

    @work(thread=True)
    def load_data(self) -> None:
        """Fetch transactions and calculate portfolio NAV history with real prices."""
        worker = get_current_worker()
        status = self.query_one("#chart-status", Static)
        empty_msg = self.query_one("#chart-empty", Static)

        self.app.call_from_thread(status.update, "Loading transactions...")
        self.app.call_from_thread(setattr, empty_msg, "display", False)

        try:
            # Fetch transactions
            self._transactions = self.client.get_transactions(
                self.accno,
                accid=self.accid,
                on_progress=lambda f, t: (
                    self.app.call_from_thread(
                        status.update, f"Loading transactions... {f}/{t}"
                    )
                    if not worker.is_cancelled
                    else None
                ),
            )

            if worker.is_cancelled:
                return

            # Fetch current holdings for symbol mapping
            self.app.call_from_thread(status.update, "Loading holdings...")
            self._holdings = self.client.get_holdings(self.accid)

            if worker.is_cancelled:
                return

            # Calculate NAV history using real price data
            def on_nav_progress(msg: str, current: int, total: int) -> None:
                if not worker.is_cancelled:
                    if total > 0:
                        self.app.call_from_thread(
                            status.update, f"{msg} ({current}/{total})"
                        )
                    else:
                        self.app.call_from_thread(status.update, msg)

            nav_service = PortfolioNAVService(
                self._transactions,
                self._holdings,
            )
            self._history = nav_service.calculate_nav_history(
                on_progress=on_nav_progress
            )

            if not worker.is_cancelled:
                self.app.call_from_thread(self._render_chart)
                self.app.call_from_thread(status.update, "")

        except NordnetAPIError as e:
            if not worker.is_cancelled:
                self.app.call_from_thread(
                    self.notify,
                    f"Failed to load chart data: {e}",
                    severity="error",
                )
                self.app.call_from_thread(status.update, "")
        except Exception as e:
            if not worker.is_cancelled:
                self.app.call_from_thread(
                    self.notify,
                    f"Error calculating NAV: {e}",
                    severity="error",
                )
                self.app.call_from_thread(status.update, "")

    def _render_chart(self) -> None:
        """Render the portfolio value chart."""
        empty_msg = self.query_one("#chart-empty", Static)
        chart = self.query_one("#portfolio-chart", PlotextPlot)

        if not self._history:
            empty_msg.update("No transaction history available for chart.")
            empty_msg.display = True
            chart.display = False
            return

        empty_msg.display = False
        chart.display = True

        # Filter by selected range
        filtered = self._filter_by_range(self._history)

        if not filtered:
            empty_msg.update("No data in selected time range.")
            empty_msg.display = True
            chart.display = False
            return

        # Prepare data - format dates as DD-MM-YYYY
        dates = [p.date.strftime("%d-%m-%Y") for p in filtered]
        values = [p.value for p in filtered]

        # Update chart
        plt = chart.plt

        plt.clear_figure()

        # Show breakdown in title if we have the data
        latest = filtered[-1]
        if latest.cash_balance is not None and latest.holdings_value is not None:
            plt.title(
                f"Portfolio: {latest.value:,.0f} "
                f"(Holdings: {latest.holdings_value:,.0f}, Cash: {latest.cash_balance:,.0f})"
            )
        else:
            plt.title("Portfolio NAV Over Time")

        plt.xlabel("Date")
        plt.ylabel(f"Value ({filtered[0].currency})")

        # Calculate y-axis ticks rounded to nearest 10,000
        if values:
            min_val = min(values)
            max_val = max(values)
            # Round down min and round up max to nearest 10,000
            y_min = (int(min_val) // 10000) * 10000
            y_max = ((int(max_val) // 10000) + 1) * 10000
            # Create ticks at 10,000 intervals
            y_ticks = [float(y) for y in range(y_min, y_max + 1, 10000)]
            # Limit to reasonable number of ticks
            if len(y_ticks) > 10:
                step = len(y_ticks) // 8
                y_ticks = y_ticks[::step]
            plt.yticks(y_ticks)

        # Use date indices for x-axis
        x = [float(i) for i in range(len(dates))]
        plt.plot(x, values, marker="braille")

        # Set x-axis labels (sample every N points for readability)
        if len(dates) > 8:
            step = max(1, len(dates) // 6)
            xticks = x[::step]
            xlabels = dates[::step]
            plt.xticks(xticks, xlabels)
        elif dates:
            plt.xticks(x, dates)

        chart.refresh()

    def _filter_by_range(
        self, history: list[PortfolioValuePoint]
    ) -> list[PortfolioValuePoint]:
        """Filter history by selected time range."""
        if self._selected_range == "all" or not history:
            return history

        today = date.today()
        cutoff_map = {
            "1y": today - timedelta(days=365),
            "6m": today - timedelta(days=182),
            "3m": today - timedelta(days=91),
            "1m": today - timedelta(days=30),
        }

        cutoff = cutoff_map.get(self._selected_range, date.min)
        return [p for p in history if p.date >= cutoff]

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle time range selection change."""
        if event.select.id == "range-select":
            self._selected_range = str(event.value)
            self._render_chart()
