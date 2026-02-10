"""Fleet overview table widget for cltop."""

from __future__ import annotations

from datetime import datetime, timezone

from textual.reactive import reactive
from textual.widgets import DataTable

from ..models import Session, SessionStatus
from ..pricing import format_tokens


class FleetTable(DataTable):
    """Fleet overview table showing all Claude sessions."""

    selected_session_id: reactive[str] = reactive("")

    def on_mount(self) -> None:
        """Set up table columns on mount."""
        self.cursor_type = "row"
        self.add_columns(
            "",  # Status icon
            "PID",
            "Project",
            "Status",
            "Tokens",
            "Last Activity",
        )

    def update_sessions(self, sessions: list[Session]) -> None:
        """Refresh the table with current session data."""
        # Clear existing rows
        self.clear()

        # Add rows for each session
        for session in sessions:
            status_icon = self._get_status_icon(session.status)
            pid_display = self._get_pid_display(session)
            project = session.display_name
            status_text = session.status.value
            tokens = format_tokens(session.metrics.tokens_used)
            last_activity = self._format_last_activity(session.last_activity)

            self.add_row(
                status_icon,
                pid_display,
                project,
                status_text,
                tokens,
                last_activity,
                key=session.id,
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Emit selected session ID when row is clicked/navigated."""
        if event.row_key is not None:
            self.selected_session_id = str(event.row_key.value)

    @staticmethod
    def _get_status_icon(status: SessionStatus) -> str:
        """Return a colored circle based on session status."""
        match status:
            case SessionStatus.ACTIVE:
                return "[green]●[/]"
            case SessionStatus.THINKING:
                return "[yellow]●[/]"
            case SessionStatus.BACKGROUND:
                return "[blue]●[/]"
            case SessionStatus.IDLE:
                return "[white]●[/]"
            case SessionStatus.BLOCKED:
                return "[red]●[/]"
            case _:
                return "[dim]●[/]"

    @staticmethod
    def _get_pid_display(session: Session) -> str:
        """Return PID or session source identifier."""
        if session.pid is not None:
            return str(session.pid)
        match session.source.value:
            case "cowork":
                return "cowork"
            case "claude_app":
                return "app"
            case _:
                return "—"

    @staticmethod
    def _format_last_activity(last_activity: datetime | None) -> str:
        """Format last activity as relative time."""
        if last_activity is None:
            return "—"

        now = datetime.now(timezone.utc)
        delta = now - last_activity
        seconds = delta.total_seconds()

        if seconds < 60:
            return f"{int(seconds)}s"
        if seconds < 3600:
            return f"{int(seconds / 60)}m"
        if seconds < 86400:
            return f"{int(seconds / 3600)}h"
        return f"{int(seconds / 86400)}d"
