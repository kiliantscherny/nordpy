"""NordpyApp — main Textual application and CLI entry point."""

from __future__ import annotations

import argparse

import requests
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, LoadingIndicator

from nordpy.client import NordnetClient
from nordpy.session import SessionManager


class NordpyApp(App):
    """Interactive TUI for browsing and exporting Nordnet financial data."""

    TITLE = "nordpy"
    CSS_PATH = "styles/nordpy.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "quit", "Quit", show=False),
        Binding("e", "export", "Export"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(
        self,
        *,
        user: str,
        method: str = "APP",
        password: str | None = None,
        proxy: str | None = None,
        force_login: bool = False,
    ) -> None:
        super().__init__()
        self.user = user
        self.method = method
        self.password = password
        self.proxy = proxy
        self.force_login = force_login

        self.http_session = requests.Session()
        if proxy:
            self.http_session.proxies.update(
                {"http": f"socks5://{proxy}", "https": f"socks5://{proxy}"}
            )

        self.session_manager = SessionManager()
        self.api_client = NordnetClient(self.http_session)

    def compose(self) -> ComposeResult:
        yield Header()
        yield LoadingIndicator()
        yield Footer()

    def _update_session_display(self) -> None:
        """Update the header subtitle with session expiry countdown."""
        remaining = self.session_manager.session_seconds_remaining
        if remaining is None:
            self.sub_title = ""
        elif remaining == 0:
            self.sub_title = "Session: EXPIRED — press q to quit and re-login"
        else:
            mins, secs = divmod(remaining, 60)
            self.sub_title = f"Session: {mins}m {secs:02d}s remaining"

    def on_ready(self) -> None:
        """Start a timer to update session expiry display every second."""
        self.set_interval(1, self._update_session_display)

    @work
    async def on_mount(self) -> None:
        """Check for valid session, then show auth or accounts screen."""
        from nordpy.screens.accounts import AccountsScreen
        from nordpy.screens.auth import AuthScreen

        needs_auth = self.force_login

        if not needs_auth:
            valid = self.session_manager.load_and_validate(self.http_session)
            needs_auth = not valid

        if needs_auth:
            result = await self.push_screen_wait(
                AuthScreen(
                    self.http_session,
                    self.session_manager,
                    user=self.user,
                    method=self.method,
                    password=self.password,
                )
            )
            if result is None:
                self.exit()
                return

        self.push_screen(
            AccountsScreen(
                session=self.http_session,
                client=self.api_client,
            )
        )

    async def handle_session_expiry(self) -> bool:
        """Re-authenticate when session expires (401). Returns True if successful."""
        from nordpy.screens.auth import AuthScreen

        self.notify("Session expired — re-authenticating...", severity="warning")
        result = await self.push_screen_wait(
            AuthScreen(
                self.http_session,
                self.session_manager,
                user=self.user,
                method=self.method,
                password=self.password,
            )
        )
        return result is not None

    def action_export(self) -> None:
        """Open export dialog for the current screen's data."""
        from nordpy.screens.accounts import AccountsScreen
        from nordpy.widgets.export_dialog import ExportDialog

        screen = self.screen
        if isinstance(screen, AccountsScreen) and screen._accounts:
            self.push_screen(
                ExportDialog(
                    data=screen._accounts,
                    entity_name="accounts",
                )
            )
        else:
            self.notify("No data to export on this screen", severity="warning")

    def action_refresh(self) -> None:
        """Refresh the current screen's data."""
        screen = self.screen
        if hasattr(screen, "action_refresh"):
            screen.action_refresh()


def main() -> None:
    """CLI entry point — parse args and launch the TUI."""
    parser = argparse.ArgumentParser(description="Nordnet Portfolio TUI")
    parser.add_argument("--user", required=True, help="MitID username")
    parser.add_argument(
        "--method",
        choices=["APP", "TOKEN"],
        default="APP",
        help="MitID auth method (default: APP)",
    )
    parser.add_argument("--password", help="Password for TOKEN method")
    parser.add_argument("--proxy", help="SOCKS5 proxy URL")
    parser.add_argument(
        "--force-login",
        action="store_true",
        help="Force re-authentication",
    )
    parser.add_argument(
        "--export",
        choices=["csv", "xlsx", "duckdb"],
        help="Headless export mode (no TUI)",
    )

    args = parser.parse_args()

    if args.export:
        _run_headless_export(args)
        return

    app = NordpyApp(
        user=args.user,
        method=args.method,
        password=args.password,
        proxy=args.proxy,
        force_login=args.force_login,
    )
    app.run()


def _run_headless_export(args: argparse.Namespace) -> None:
    """Authenticate, fetch all data, export to the chosen format, and exit."""
    from nordpy.auth import AuthManager
    from nordpy.client import NordnetClient
    from nordpy.export import export_csv, export_duckdb, export_xlsx
    from nordpy.session import SessionManager

    exporters = {"csv": export_csv, "xlsx": export_xlsx, "duckdb": export_duckdb}
    exporter = exporters[args.export]

    session = requests.Session()
    if args.proxy:
        session.proxies.update(
            {"http": f"socks5://{args.proxy}", "https": f"socks5://{args.proxy}"}
        )

    sm = SessionManager()
    needs_auth = args.force_login or not sm.load_and_validate(session)

    if needs_auth:
        auth = AuthManager(session, sm)
        print("Authenticating...")
        auth.authenticate(
            args.user,
            args.method,
            args.password,
            on_status=lambda msg: print(f"  {msg}"),
        )

    client = NordnetClient(session)

    print("Fetching accounts...")
    accounts = client.get_accounts()
    for acc in accounts:
        print(f"  {acc.display_name} ({acc.accno})")

        holdings = client.get_holdings(acc.accid)
        if holdings:
            path = exporter(holdings, f"holdings_{acc.accno}")
            print(f"    Holdings → {path}")

        transactions = client.get_transactions(
            acc.accno,
            accid=acc.accid,
            on_progress=lambda f, t: print(f"    Transactions: {f}/{t}", end="\r"),
        )
        if transactions:
            print()
            path = exporter(transactions, f"transactions_{acc.accno}")
            print(f"    Transactions → {path}")

    print("Done.")
