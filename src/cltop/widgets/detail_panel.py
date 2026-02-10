"""Detail panel widget for session information."""

from __future__ import annotations

from textual.widgets import Static

from ..models import Session


class DetailPanel(Static):
    """Detail view for a selected Claude session."""

    def update_session(self, session: Session | None) -> None:
        """Update the detail view with session information."""
        if session is None:
            self.update("[dim]No session selected[/]")
            return

        # Build the detail view content
        lines: list[str] = []

        # Header
        pid_str = str(session.pid) if session.pid else "—"
        branch_str = f" [{session.branch}]" if session.branch else ""
        lines.append(f"[bold]▶ Session: {pid_str} · {session.display_name}{branch_str}[/]")
        lines.append("")

        # Current task and file
        if session.current_task:
            lines.append(f"[cyan]Task:[/] {session.current_task}")
        if session.current_file:
            lines.append(f"[cyan]File:[/] {session.current_file}")

        if session.current_task or session.current_file:
            lines.append("")

        # Hook status hint
        if not session.has_hook:
            lines.append("[dim italic]Install hook for richer data[/]")
            lines.append("")

        # Recent tool calls
        if session.recent_tools:
            lines.append("[bold]Recent Tools:[/]")
            for tool_call in session.recent_tools[-10:]:  # Last 10 tools
                timestamp = tool_call.timestamp.strftime("%H:%M:%S")
                tool_name = tool_call.tool_name
                summary = tool_call.summary

                # Format duration if available
                duration_str = ""
                if tool_call.duration_ms is not None:
                    if tool_call.duration_ms > 1000:
                        duration_str = f" ({tool_call.duration_ms / 1000:.1f}s)"
                    else:
                        duration_str = f" ({tool_call.duration_ms}ms)"

                # Check if tool is still running (no duration)
                running_indicator = ""
                if tool_call.duration_ms is None:
                    running_indicator = " [dim](running...)[/]"

                lines.append(
                    f"  [dim]{timestamp}[/]  [yellow]{tool_name:8s}[/] {summary}{duration_str}{running_indicator}"
                )
        else:
            lines.append("[dim]No tool calls recorded[/]")

        self.update("\n".join(lines))
