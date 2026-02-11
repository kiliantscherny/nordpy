"""ExportDialog — modal overlay for choosing export format and running export."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, LoadingIndicator, RadioButton, RadioSet

from nordpy.export import export_csv, export_duckdb, export_xlsx

EXPORTERS = {
    "CSV": export_csv,
    "Excel (XLSX)": export_xlsx,
    "DuckDB": export_duckdb,
}


class ExportDialog(ModalScreen[Path | None]):
    """Modal dialog for selecting export format and running export."""

    DEFAULT_CSS = """
    ExportDialog {
        align: center middle;
    }

    ExportDialog > Vertical {
        width: 50;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $accent;
        padding: 1 2;
    }

    ExportDialog #export-title {
        text-style: bold;
        width: 100%;
        content-align: center middle;
        margin-bottom: 1;
    }

    ExportDialog RadioSet {
        width: 100%;
        margin-bottom: 1;
    }

    ExportDialog #export-buttons {
        width: 100%;
        height: auto;
        align-horizontal: right;
    }

    ExportDialog #export-buttons Button {
        margin-left: 1;
    }

    ExportDialog #export-loading {
        width: 100%;
        height: 3;
        display: none;
    }
    """

    def __init__(
        self,
        data: Sequence[BaseModel],
        entity_name: str,
    ) -> None:
        super().__init__()
        self.data = data
        self.entity_name = entity_name
        self._selected_format: str = "CSV"

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"Export {self.entity_name}", id="export-title")
            with RadioSet(id="export-format"):
                yield RadioButton("CSV", value=True)
                yield RadioButton("Excel (XLSX)")
                yield RadioButton("DuckDB")
            yield LoadingIndicator(id="export-loading")
            with Horizontal(id="export-buttons"):
                yield Button("Cancel", variant="default", id="export-cancel")
                yield Button("Export", variant="primary", id="export-confirm")

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        self._selected_format = event.pressed.label.plain

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "export-cancel":
            self.dismiss(None)
        elif event.button.id == "export-confirm":
            self._run_export()

    @work(thread=True)
    def _run_export(self) -> None:
        """Run the selected export in a background thread."""
        loading = self.query_one("#export-loading", LoadingIndicator)
        confirm_btn = self.query_one("#export-confirm", Button)
        cancel_btn = self.query_one("#export-cancel", Button)

        self.app.call_from_thread(setattr, loading, "display", True)
        self.app.call_from_thread(setattr, confirm_btn, "disabled", True)
        self.app.call_from_thread(setattr, cancel_btn, "disabled", True)

        try:
            exporter = EXPORTERS[self._selected_format]
            path = exporter(self.data, self.entity_name)
            self.app.call_from_thread(
                self.app.notify, f"Exported to {path}", severity="information"
            )
            self.app.call_from_thread(self.dismiss, path)
        except Exception as e:
            self.app.call_from_thread(
                self.app.notify, f"Export failed: {e}", severity="error"
            )
            self.app.call_from_thread(setattr, loading, "display", False)
            self.app.call_from_thread(setattr, confirm_btn, "disabled", False)
            self.app.call_from_thread(setattr, cancel_btn, "disabled", False)
