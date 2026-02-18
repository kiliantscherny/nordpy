"""NordpyApp — main Textual application and CLI entry point."""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    import rich.console
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.theme import Theme
from textual.widgets import Footer, Header, LoadingIndicator

from nordpy import __version__
from nordpy.client import NordnetClient
from nordpy.http import create_session
from nordpy.session import SessionManager

NORDPY_THEME = Theme(
    name="nordpy",
    primary="#a78bfa",
    secondary="#60a5fa",
    accent="#c084fc",
    foreground="#e2e8f0",
    background="#0f0f1a",
    surface="#1a1b2e",
    panel="#252640",
    success="#4ade80",
    warning="#fbbf24",
    error="#f87171",
    dark=True,
    variables={
        "footer-key-foreground": "#a78bfa",
        "footer-description-foreground": "#94a3b8",
        "input-selection-background": "#60a5fa 35%",
        "block-cursor-text-style": "none",
        "block-cursor-foreground": "#e2e8f0",
        "block-cursor-background": "#a78bfa",
    },
)


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
        proxy: str | None = None,
        force_login: bool = False,
    ) -> None:
        super().__init__()
        self.register_theme(NORDPY_THEME)
        self.theme = "nordpy"
        self.user = user
        self.proxy = proxy
        self.force_login = force_login

        self.http_session = create_session(proxy=proxy)

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
            self.sub_title = "Session: EXPIRED — press q to quit and re-login with the '--force-login' flag"
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


def _configure_logging(verbose: bool = False) -> None:
    """Set up loguru to write to nordpy.log (and stderr if verbose)."""
    from pathlib import Path

    log_path = Path(__file__).resolve().parent.parent.parent / "nordpy.log"
    logger.remove()  # Remove default stderr handler
    logger.add(
        str(log_path),
        rotation="5 MB",
        retention="3 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} | {message}",
    )
    if verbose:
        logger.add(sys.stderr, level="DEBUG")
    logger.info("nordpy started — logging to {}", log_path)
    # Also print so the user can find it even if Textual swallows stderr
    print(f"[nordpy] Log file: {log_path}")


class _ColorHelpFormatter(argparse.HelpFormatter):
    """Argparse formatter with green argument names and aligned descriptions."""

    _GREEN = "\033[32m"
    _YELLOW = "\033[33m"
    _RESET = "\033[0m"
    _BOLD = "\033[1m"

    def __init__(self, prog: str) -> None:
        # +9 to compensate for invisible ANSI color codes in option strings
        super().__init__(prog, max_help_position=48)

    def _get_help_string(self, action: argparse.Action) -> str | None:
        help_text = super()._get_help_string(action)
        if help_text and action.required:
            help_text += f" {self._YELLOW}(required){self._RESET}"
        return help_text

    def _format_action_invocation(self, action: argparse.Action) -> str:
        result = super()._format_action_invocation(action)
        return f"{self._GREEN}{result}{self._RESET}"

    def _format_usage(
        self,
        usage: str | None,
        actions: Any,
        groups: Any,
        prefix: str | None,
    ) -> str:
        result = super()._format_usage(usage, actions, groups, prefix)
        # Color "usage:" prefix bold
        result = result.replace("usage:", f"{self._BOLD}usage:{self._RESET}", 1)
        return result

    def start_section(self, heading: str | None) -> None:
        # Make section headers (e.g. "options:") bold
        if heading:
            heading = f"{self._BOLD}{heading}{self._RESET}"
        super().start_section(heading)


def main() -> None:
    """CLI entry point — parse args and launch the TUI."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    from rich.theme import Theme as RichTheme

    theme = RichTheme({
        "title": "bold #a78bfa",
        "accent": "#c084fc",
        "info": "#60a5fa",
        "success": "bold #4ade80",
        "warn": "#fbbf24",
        "err": "bold #f87171",
        "dim": "#64748b",
        "val": "bold #e2e8f0",
    })
    console = Console(theme=theme)

    banner = Text(justify="center")
    banner.append("> nordpy ", style="bold #a78bfa on #252640")
    banner.append("\n✼ A TUI for your Nordnet portfolio ✼", style="#f58742")
    console.print(Panel(banner, border_style="#a78bfa", expand=False, padding=(0, 2)))
    console.print()

    parser = argparse.ArgumentParser(
        description="Interactive TUI for browsing and exporting your Nordnet investments data",
        formatter_class=_ColorHelpFormatter,
    )
    parser.add_argument(
        "--version", "-V",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument("--user", "-u", metavar="", help="MitID username")
    parser.add_argument(
        "--force-login", "-f",
        action="store_true",
        help="Force re-authentication",
    )
    parser.add_argument(
        "--export", "-e",
        choices=["csv", "xlsx", "duckdb"],
        help="Headless export mode (no TUI)",
    )
    parser.add_argument(
        "--output-dir", "-o",
        metavar="",
        help="Export destination (default: exports/)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Also log to stderr",
    )
    parser.add_argument("--proxy", "-p", metavar="", help="SOCKS5 proxy URL (e.g. host:port)")
    parser.add_argument(
        "--logout",
        action="store_true",
        help="Delete saved session and exit",
    )

    args = parser.parse_args()

    if args.logout:
        from nordpy.session import SessionManager
        sm = SessionManager()
        if sm.session_path.exists():
            sm.session_path.unlink()
            console.print("[success]Session file removed.[/success]")
        else:
            console.print("[dim]No saved session found.[/dim]")
        return

    if not args.user:
        parser.error("--user is required")

    _configure_logging(verbose=args.verbose)

    if args.export:
        _run_headless_export(args, console)
        return

    app = NordpyApp(
        user=args.user,
        proxy=args.proxy,
        force_login=args.force_login,
    )
    app.run()


def _run_headless_export(
    args: argparse.Namespace, console: "rich.console.Console"
) -> None:
    """Authenticate, fetch all data, export to the chosen format, and exit."""
    from pathlib import Path

    from rich.table import Table

    from nordpy.auth import AuthManager
    from nordpy.client import NordnetClient
    from nordpy.export import export_csv, export_duckdb, export_xlsx
    from nordpy.session import SessionManager

    exporters = {"csv": export_csv, "xlsx": export_xlsx, "duckdb": export_duckdb}
    exporter = exporters[args.export]
    output_dir = Path(args.output_dir) if args.output_dir else None

    if output_dir:
        console.print(f"  Output folder: [val]{output_dir}[/val]")
    console.print(f"  Format: [val]{args.export.upper()}[/val]")
    console.print()

    session = create_session(proxy=args.proxy)

    sm = SessionManager()
    needs_auth = args.force_login or not sm.load_and_validate(session)

    if needs_auth:
        auth = AuthManager(session, sm)
        with console.status("[accent]Authenticating via MitID...[/accent]"):
            auth.authenticate(
                args.user,
                "APP",
                None,
                on_status=lambda msg: console.print(f"  [dim]{msg}[/dim]"),
            )
        console.print("  [success]Authenticated[/success]")
        console.print()

    client = NordnetClient(session)

    with console.status("[info]Fetching accounts...[/info]"):
        accounts = client.get_accounts()

    console.print(f"  Found [val]{len(accounts)}[/val] account(s)")
    console.print()

    exported: list[tuple[str, str, str]] = []

    for acc in accounts:
        console.rule(f"[title]{acc.display_name}[/title] [dim]({acc.accno})[/dim]")

        with console.status("[info]Fetching holdings...[/info]"):
            holdings = client.get_holdings(acc.accid)
        if holdings:
            path = exporter(holdings, f"holdings_{acc.accno}", output_dir=output_dir)
            console.print(f"  [success]Holdings[/success]  {len(holdings)} rows -> [val]{path}[/val]")
            exported.append((acc.display_name, "Holdings", str(path)))
        else:
            console.print("  [dim]Holdings  (none)[/dim]")

        with console.status("[info]Fetching transactions...[/info]"):
            transactions = client.get_transactions(
                acc.accno,
                accid=acc.accid,
                on_progress=lambda f, t: None,
            )
        if transactions:
            path = exporter(transactions, f"transactions_{acc.accno}", output_dir=output_dir)
            console.print(f"  [success]Transactions[/success]  {len(transactions)} rows -> [val]{path}[/val]")
            exported.append((acc.display_name, "Transactions", str(path)))
        else:
            console.print("  [dim]Transactions  (none)[/dim]")

        console.print()

    if exported:
        table = Table(title="Exported files", title_style="title", border_style="#64748b")
        table.add_column("Account", style="info")
        table.add_column("Data", style="accent")
        table.add_column("Path", style="val")
        for account, data_type, path in exported:
            table.add_row(account, data_type, path)
        console.print(table)
    else:
        console.print("[warn]No data exported.[/warn]")

    console.print()
    console.print("[success]Done.[/success]")
