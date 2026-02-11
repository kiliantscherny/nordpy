"""AccountDetailScreen — tabbed detail view for a single account."""

from __future__ import annotations

import requests
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, TabbedContent, TabPane

from nordpy.client import NordnetClient
from nordpy.models import Account
from nordpy.screens.holdings import HoldingsPane
from nordpy.screens.trades import OrdersPane, TradesPane
from nordpy.screens.transactions import TransactionsPane
from nordpy.widgets.export_dialog import ExportDialog


class AccountDetailScreen(Screen):
    """Tabbed detail view for a single Nordnet account."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("backspace", "go_back", "Back", show=False),
        Binding("e", "export", "Export"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(
        self,
        *,
        session: requests.Session,
        client: NordnetClient,
        account: Account,
    ) -> None:
        super().__init__()
        self.http_session = session
        self.client = client
        self.account = account

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent():
            with TabPane("Holdings", id="tab-holdings"):
                yield HoldingsPane(client=self.client, accid=self.account.accid)
            with TabPane("Transactions", id="tab-transactions"):
                yield TransactionsPane(
                    client=self.client,
                    accno=self.account.accno,
                    accid=self.account.accid,
                )
            with TabPane("Trades", id="tab-trades"):
                yield TradesPane(client=self.client, accid=self.account.accid)
            with TabPane("Orders", id="tab-orders"):
                yield OrdersPane(client=self.client, accid=self.account.accid)
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = self.account.display_name

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_export(self) -> None:
        """Export the data from the currently active tab."""
        tabs = self.query_one(TabbedContent)
        active = tabs.active

        if active == "tab-holdings":
            pane = self.query_one(HoldingsPane)
            data = pane._holdings
            entity = f"holdings_{self.account.accno}"
        elif active == "tab-transactions":
            pane = self.query_one(TransactionsPane)
            data = pane._filtered
            entity = f"transactions_{self.account.accno}"
        elif active == "tab-trades":
            pane = self.query_one(TradesPane)
            data = pane._trades
            entity = f"trades_{self.account.accno}"
        elif active == "tab-orders":
            pane = self.query_one(OrdersPane)
            data = pane._orders
            entity = f"orders_{self.account.accno}"
        else:
            self.notify("Export not available for this tab", severity="warning")
            return

        if not data:
            self.notify("No data to export", severity="warning")
            return

        self.app.push_screen(ExportDialog(data=data, entity_name=entity))

    def action_refresh(self) -> None:
        self.query_one(HoldingsPane).load_data()
        self.query_one(TransactionsPane).load_data()
        self.query_one(TradesPane).load_data()
        self.query_one(OrdersPane).load_data()
