"""AccountsScreen — account overview with balances DataTable."""

from __future__ import annotations

import requests
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static
from textual.worker import get_current_worker

from nordpy.client import NordnetAPIError, NordnetClient
from nordpy.models import Account, AccountBalance


class AccountsScreen(Screen):
    """Displays all Nordnet accounts with balances in a DataTable."""

    BINDINGS = [
        Binding("escape", "app.quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("enter", "select_row", "Select", show=False),
    ]

    def __init__(
        self,
        session: requests.Session,
        client: NordnetClient,
    ) -> None:
        super().__init__()
        self.http_session = session
        self.client = client
        self._accounts: list[Account] = []
        self._balances: dict[int, AccountBalance] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="accounts-table", cursor_type="row")
        yield Static("", id="empty-msg", classes="empty-state")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#accounts-table", DataTable)
        table.add_columns("Account No", "Name", "Type", "Balance", "Currency")
        self._load_accounts()

    @work(thread=True)
    def _load_accounts(self) -> None:
        """Fetch accounts and balances in a background thread."""
        worker = get_current_worker()
        table = self.query_one("#accounts-table", DataTable)
        self.app.call_from_thread(setattr, table, "loading", True)

        try:
            accounts = self.client.get_accounts()
            if worker.is_cancelled:
                return

            balances: dict[int, AccountBalance] = {}
            for acc in accounts:
                if worker.is_cancelled:
                    return
                try:
                    balances[acc.accid] = self.client.get_balance(acc.accid)
                except NordnetAPIError:
                    pass

            if worker.is_cancelled:
                return

            self._accounts = accounts
            self._balances = balances
            self.app.call_from_thread(self._populate_table)
        except NordnetAPIError as e:
            if not worker.is_cancelled:
                self.app.call_from_thread(
                    self.notify,
                    f"Failed to load accounts: {e}",
                    severity="error",
                )
        finally:
            if not worker.is_cancelled:
                self.app.call_from_thread(setattr, table, "loading", False)

    def _populate_table(self) -> None:
        """Populate the DataTable with account data (must run on main thread)."""
        table = self.query_one("#accounts-table", DataTable)
        empty_msg = self.query_one("#empty-msg", Static)
        table.clear()

        if not self._accounts:
            empty_msg.update("No accounts found.")
            table.display = False
            empty_msg.display = True
            return

        empty_msg.display = False
        table.display = True

        for acc in self._accounts:
            bal = self._balances.get(acc.accid)
            balance_str = f"{bal.balance.value:,.2f}" if bal else "N/A"
            currency = bal.balance.currency if bal else ""
            table.add_row(
                acc.accno,
                acc.display_name,
                acc.type,
                balance_str,
                currency,
                key=str(acc.accid),
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Navigate to account detail when a row is selected."""
        if event.row_key.value is None:
            return
        accid = int(event.row_key.value)
        account = next((a for a in self._accounts if a.accid == accid), None)
        if account:
            # AccountDetailScreen will be imported here once implemented (T019)
            from nordpy.screens.detail import AccountDetailScreen

            self.app.push_screen(
                AccountDetailScreen(
                    session=self.http_session,
                    client=self.client,
                    account=account,
                )
            )

    def action_refresh(self) -> None:
        self._load_accounts()

    def action_select_row(self) -> None:
        table = self.query_one("#accounts-table", DataTable)
        if table.row_count > 0:
            table.action_select_cursor()
