"""AccountSortDialog — modal overlay for choosing account sort order."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, RadioButton, RadioSet

from nordpy.services.account_sort import SortField, SortSpec

_FIELD_LABELS: list[tuple[SortField, str]] = [
    (SortField.TOTAL, "Total (balance + holdings)"),
    (SortField.HOLDINGS, "Holdings value"),
    (SortField.CASH, "Cash balance"),
    (SortField.NAME, "Name"),
    (SortField.TYPE, "Account type"),
    (SortField.ACCNO, "Account number"),
]


class AccountSortDialog(ModalScreen[SortSpec | None]):
    """Modal dialog for selecting the account sort field and direction."""

    DEFAULT_CSS = """
    AccountSortDialog {
        align: center middle;
    }

    AccountSortDialog > Vertical {
        width: 50;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary 60%;
        padding: 1 2;
    }

    AccountSortDialog #sort-title {
        text-style: bold;
        color: $primary;
        width: 100%;
        content-align: center middle;
        margin-bottom: 1;
    }

    AccountSortDialog RadioSet {
        width: 100%;
        margin-bottom: 1;
    }

    AccountSortDialog #sort-buttons {
        width: 100%;
        height: auto;
        align-horizontal: right;
    }

    AccountSortDialog #sort-buttons Button {
        margin-left: 1;
    }
    """

    def __init__(self, current: SortSpec) -> None:
        super().__init__()
        self._current = current

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Sort accounts", id="sort-title")
            with RadioSet(id="sort-field"):
                for field, label in _FIELD_LABELS:
                    yield RadioButton(label, value=field == self._current.field)
            with RadioSet(id="sort-direction"):
                yield RadioButton(
                    "Descending (high to low)", value=self._current.descending
                )
                yield RadioButton(
                    "Ascending (low to high)", value=not self._current.descending
                )
            with Horizontal(id="sort-buttons"):
                yield Button("Cancel", variant="default", id="sort-cancel")
                yield Button("Apply", variant="primary", id="sort-apply")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "sort-cancel":
            self.dismiss(None)
            return
        field_set = self.query_one("#sort-field", RadioSet)
        dir_set = self.query_one("#sort-direction", RadioSet)
        field = _FIELD_LABELS[field_set.pressed_index][0]
        descending = dir_set.pressed_index == 0
        self.dismiss(SortSpec(field=field, descending=descending))
