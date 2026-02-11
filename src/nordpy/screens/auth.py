"""AuthScreen — MitID authentication screen."""

from __future__ import annotations

import threading

import requests
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Center, Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    LoadingIndicator,
    Static,
)
from textual.worker import get_current_worker

from nordpy.auth import AuthError, AuthManager
from nordpy.session import SessionManager


class AuthScreen(Screen[requests.Session | None]):
    """MitID authentication screen. Dismisses with the session on success."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        session: requests.Session,
        session_manager: SessionManager,
        *,
        user: str,
        method: str = "APP",
        password: str | None = None,
    ) -> None:
        super().__init__()
        self.http_session = session
        self.session_manager = session_manager
        self.user = user
        self.method = method
        self.password = password
        self._input_event = threading.Event()
        self._input_value: str = ""

    def compose(self) -> ComposeResult:
        yield Header()
        with Center():
            with VerticalScroll(id="auth-container"):
                yield Static("MitID Authentication", classes="auth-title")
                yield Static(f"User: {self.user}", classes="auth-info")
                yield Static(f"Method: {self.method}", classes="auth-info")
                if self.method == "TOKEN":
                    yield Input(placeholder="Enter 6-digit TOTP code", id="totp-input")
                    if not self.password:
                        yield Input(
                            placeholder="Enter password",
                            password=True,
                            id="password-input",
                        )
                    yield Button("Authenticate", variant="primary", id="auth-button")
                else:
                    yield Static(
                        "Open your MitID app and approve the login request.",
                        id="app-instructions",
                    )
                    yield Static("", id="qr-display")
                    yield LoadingIndicator(id="auth-loading")
                yield Label("", id="auth-status")
                with Horizontal(id="cpr-group"):
                    yield Input(
                        placeholder="Enter CPR number (DDMMYYXXXX)",
                        id="cpr-input",
                    )
                    yield Button("Submit", variant="primary", id="cpr-submit")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#cpr-group").display = False
        if self.method == "APP":
            self._run_app_auth()

    @on(Button.Pressed, "#auth-button")
    def on_auth_button(self) -> None:
        """Handle TOKEN method authentication."""
        self._run_token_auth()

    @on(Button.Pressed, "#cpr-submit")
    def on_cpr_submit(self) -> None:
        """Handle CPR number submission — unblocks the waiting worker thread."""
        cpr_input = self.query_one("#cpr-input", Input)
        self._input_value = cpr_input.value.strip()
        self._input_event.set()

    @on(Input.Submitted, "#cpr-input")
    def on_cpr_enter(self) -> None:
        """Allow pressing Enter in the CPR input to submit."""
        self.on_cpr_submit()

    @work(thread=True)
    def _run_app_auth(self) -> None:
        """Run APP method authentication in a worker thread."""
        worker = get_current_worker()
        status_label = self.query_one("#auth-status", Label)
        qr_widget = self.query_one("#qr-display", Static)

        def update_status(msg: str) -> None:
            if not worker.is_cancelled:
                self.app.call_from_thread(status_label.update, msg)

        def update_qr(matrix: list[list[bool]]) -> None:
            if not worker.is_cancelled:
                rendered = self._render_qr_halfblock(matrix)
                self.app.call_from_thread(qr_widget.update, rendered)

        def request_input(prompt: str) -> str:
            """Show CPR input in the TUI and block until the user submits."""
            self._input_event.clear()
            self._input_value = ""

            def _show_cpr_input() -> None:
                cpr_group = self.query_one("#cpr-group")
                cpr_group.display = True
                self.query_one("#cpr-input", Input).focus()

            self.app.call_from_thread(_show_cpr_input)
            self._input_event.wait()

            def _hide_cpr_input() -> None:
                self.query_one("#cpr-group").display = False

            self.app.call_from_thread(_hide_cpr_input)
            return self._input_value

        try:
            auth = AuthManager(self.http_session, self.session_manager)
            auth.authenticate(
                self.user,
                self.method,
                self.password,
                on_status=update_status,
                on_qr_display=update_qr,
                on_input_needed=request_input,
            )
            if not worker.is_cancelled:
                self.app.call_from_thread(self.dismiss, self.http_session)
        except AuthError as e:
            if not worker.is_cancelled:
                self.app.call_from_thread(
                    self.notify, f"Authentication failed: {e}", severity="error"
                )
                self.app.call_from_thread(status_label.update, f"Failed: {e}")
        except Exception as e:
            if not worker.is_cancelled:
                msg = self._extract_error_message(e)
                self.app.call_from_thread(self.notify, msg, severity="error")
                self.app.call_from_thread(status_label.update, f"Failed: {msg}")

    @work(thread=True)
    def _run_token_auth(self) -> None:
        """Run TOKEN method authentication in a worker thread."""
        worker = get_current_worker()
        status_label = self.query_one("#auth-status", Label)

        totp_input = self.query_one("#totp-input", Input)
        totp_code = totp_input.value.strip()
        if not totp_code:
            self.app.call_from_thread(
                self.notify, "Please enter your TOTP code", severity="warning"
            )
            return

        password = self.password
        if not password:
            pw_input = self.query_one("#password-input", Input)
            password = pw_input.value

        def update_status(msg: str) -> None:
            if not worker.is_cancelled:
                self.app.call_from_thread(status_label.update, msg)

        def provide_totp(_prompt: str) -> str:
            return totp_code

        try:
            auth = AuthManager(self.http_session, self.session_manager)
            auth.authenticate(
                self.user,
                "TOKEN",
                password,
                on_status=update_status,
                on_input_needed=provide_totp,
            )
            if not worker.is_cancelled:
                self.app.call_from_thread(self.dismiss, self.http_session)
        except AuthError as e:
            if not worker.is_cancelled:
                self.app.call_from_thread(
                    self.notify, f"Authentication failed: {e}", severity="error"
                )
                self.app.call_from_thread(status_label.update, f"Failed: {e}")
        except Exception as e:
            if not worker.is_cancelled:
                msg = self._extract_error_message(e)
                self.app.call_from_thread(self.notify, msg, severity="error")
                self.app.call_from_thread(status_label.update, f"Failed: {msg}")

    @staticmethod
    def _render_qr_halfblock(matrix: list[list[bool]]) -> str:
        """Render a QR matrix using half-block characters (2 rows per line).

        Uses only single-width characters to avoid alignment issues in TUIs.
        Dark=True, Light=False in the matrix.
        Output: dark modules as spaces, light modules as block chars (inverted
        so the QR appears dark-on-light like a real printed QR code).
        """
        # Characters: each represents 2 vertical pixels (top, bottom)
        # We render light-on-dark: light cells are visible blocks
        BOTH_DARK = " "  # top dark, bottom dark -> space (background shows)
        TOP_DARK = "\u2584"  # top dark, bottom light -> lower half block
        BOT_DARK = "\u2580"  # top light, bottom dark -> upper half block
        BOTH_LIGHT = "\u2588"  # top light, bottom light -> full block

        rows = len(matrix)
        lines = ["Scan this QR code in the MitID app:", ""]
        for y in range(0, rows, 2):
            line = []
            for x in range(len(matrix[y])):
                top = matrix[y][x]
                bot = matrix[y + 1][x] if y + 1 < rows else False
                if top and bot:
                    line.append(BOTH_DARK)
                elif top and not bot:
                    line.append(TOP_DARK)
                elif not top and bot:
                    line.append(BOT_DARK)
                else:
                    line.append(BOTH_LIGHT)
            lines.append("".join(line))
        return "\n".join(lines)

    @staticmethod
    def _extract_error_message(exc: Exception) -> str:
        """Extract a human-readable message from MitID/auth exceptions."""
        import json

        arg = exc.args[0] if exc.args else exc

        # BrowserClient raises Exception(dict) or Exception(bytes)
        if isinstance(arg, dict):
            data = arg
        elif isinstance(arg, bytes):
            try:
                data = json.loads(arg.decode("utf-8", errors="replace"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return arg.decode("utf-8", errors="replace")[:200]
        else:
            raw = str(arg)
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                return raw[:200]

        # Try userMessage (top-level MitID error format)
        user_msg = data.get("userMessage", {})
        if isinstance(user_msg, dict):
            title = user_msg.get("title", {}).get("text", "")
            text = user_msg.get("text", {}).get("text", "")
            if title and text:
                return f"{title}: {text}"
            if title:
                return title

        # Try errors[] array (authenticator error format)
        errors = data.get("errors", [])
        if errors and isinstance(errors, list):
            err = errors[0]
            err_user_msg = err.get("userMessage", {})
            if isinstance(err_user_msg, dict):
                err_text = err_user_msg.get("text", {}).get("text", "")
                if err_text:
                    return err_text
            err_msg = err.get("message", "")
            if err_msg:
                return err_msg

        return data.get("message", str(arg)[:200])

    def action_cancel(self) -> None:
        self.dismiss(None)
