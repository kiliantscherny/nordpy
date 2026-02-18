"""AccountsScreen — account overview with card-based layout."""

from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Click
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Footer, Header, LoadingIndicator, Static
from textual.worker import get_current_worker

from nordpy.client import NordnetAPIError, NordnetClient
from nordpy.http import HttpSession
from nordpy.models import Account, AccountInfo


class AccountCard(Vertical, can_focus=True):
    """A focusable, clickable card displaying account summary information."""

    BINDINGS = [
        Binding("enter", "select", "Open", show=False),
    ]

    class Selected(Message):
        """Posted when the user clicks or presses Enter on an account card."""

        def __init__(self, accid: int) -> None:
            super().__init__()
            self.accid = accid

    def __init__(self, account: Account, accid: int) -> None:
        super().__init__(id=f"card-{accid}", classes="account-card")
        self.account = account
        self.accid = accid

    async def _on_click(self, event: Click) -> None:
        self.focus()
        self.post_message(self.Selected(self.accid))

    def action_select(self) -> None:
        self.post_message(self.Selected(self.accid))

    def key_down(self) -> None:
        self.screen.focus_next()

    def key_up(self) -> None:
        self.screen.focus_previous()

    def compose(self) -> ComposeResult:
        with Horizontal(classes="account-card-row"):
            yield Static(self.account.display_name, classes="account-name")
            yield Static(f"({self.account.accno})", classes="account-number")
            yield Static(self.account.type, classes="account-type-badge")
            yield Static("--", id=f"balance-{self.accid}", classes="metric-value")
            yield Static("--", id=f"value-{self.accid}", classes="metric-value metric-secondary")


class AccountsScreen(Screen):
    """Displays all Nordnet accounts as styled cards with key metrics."""

    BINDINGS = [
        Binding("escape", "app.quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(
        self,
        session: HttpSession,
        client: NordnetClient,
    ) -> None:
        super().__init__()
        self.http_session = session
        self.client = client
        self._accounts: list[Account] = []
        self._account_infos: dict[int, AccountInfo] = {}
        self._holdings_values: dict[int, float] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield LoadingIndicator(id="accounts-loading")
        yield VerticalScroll(id="accounts-container")
        yield Static("", id="empty-msg", classes="empty-state")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#accounts-container").display = False
        self.query_one("#empty-msg").display = False
        self._load_accounts()

    @work(thread=True)
    def _load_accounts(self) -> None:
        """Fetch accounts, account info, and holdings values in a background thread."""
        worker = get_current_worker()
        self.app.call_from_thread(
            setattr, self.query_one("#accounts-loading"), "display", True
        )

        try:
            accounts = self.client.get_accounts()
            if worker.is_cancelled:
                return

            account_infos: dict[int, AccountInfo] = {}
            holdings_values: dict[int, float] = {}

            for acc in accounts:
                if worker.is_cancelled:
                    return
                try:
                    account_infos[acc.accid] = self.client.get_account_info(acc.accid)
                except NordnetAPIError:
                    pass
                try:
                    holdings = self.client.get_holdings(acc.accid)
                    holdings_values[acc.accid] = sum(
                        h.market_value.value for h in holdings
                    )
                except NordnetAPIError:
                    pass

            if worker.is_cancelled:
                return

            self._accounts = accounts
            self._account_infos = account_infos
            self._holdings_values = holdings_values
            self.app.call_from_thread(self._populate_cards)
        except NordnetAPIError as e:
            if not worker.is_cancelled:
                self.app.call_from_thread(
                    self.notify,
                    f"Failed to load accounts: {e}",
                    severity="error",
                )
        finally:
            if not worker.is_cancelled:
                self.app.call_from_thread(
                    setattr, self.query_one("#accounts-loading"), "display", False
                )

    async def _populate_cards(self) -> None:
        """Build account cards (must run on main thread)."""
        container = self.query_one("#accounts-container", VerticalScroll)
        empty_msg = self.query_one("#empty-msg", Static)
        await container.remove_children()

        if not self._accounts:
            empty_msg.update("No accounts found.")
            container.display = False
            empty_msg.display = True
            return

        empty_msg.display = False
        container.display = True

        for acc in self._accounts:
            card = AccountCard(acc, acc.accid)
            container.mount(card)

        # Populate values and focus first card after mount
        self.call_later(self._update_card_values)
        self.call_later(self._focus_first_card)

    def _focus_first_card(self) -> None:
        """Focus the first account card for keyboard navigation."""
        cards = self.query(AccountCard)
        if cards:
            cards.first().focus()

    def _update_card_values(self) -> None:
        """Update the metric values on each card."""
        for acc in self._accounts:
            info = self._account_infos.get(acc.accid)
            value_val = self._holdings_values.get(acc.accid)
            currency = info.account_sum.currency or "DKK" if info else "DKK"

            balance_widget = self.query_one(f"#balance-{acc.accid}", Static)
            if info:
                balance_widget.update(f"Balance: {info.account_sum.value:,.2f} {currency}")
            else:
                balance_widget.update("Balance: N/A")

            value_widget = self.query_one(f"#value-{acc.accid}", Static)
            if value_val is not None:
                value_widget.update(f"Value: {value_val:,.2f} {currency}")
            else:
                value_widget.update("Value: N/A")

    @on(AccountCard.Selected)
    def on_card_selected(self, event: AccountCard.Selected) -> None:
        """Navigate to account detail when a card is clicked or Enter is pressed."""
        self._navigate_to_account(event.accid)

    def _navigate_to_account(self, accid: int) -> None:
        """Push the account detail screen for the given accid."""
        account = next((a for a in self._accounts if a.accid == accid), None)
        if account:
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
