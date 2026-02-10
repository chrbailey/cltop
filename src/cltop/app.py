"""cltop — htop for Claude. Main Textual application."""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Button, Footer, Header, Static

from .discovery import build_fleet_state
from .hooks import cleanup_stale_status_files, enrich_session_from_hook, install_hook, is_hook_installed, uninstall_hook
from .models import FleetState, PlanType, Session
from .pricing import format_cost
from .widgets import DetailPanel, FleetTable, MetricsBar


REFRESH_INTERVAL = 3.0  # seconds


class KillConfirmScreen(ModalScreen[bool]):
    """Modal confirmation before killing a session."""

    CSS = """
    KillConfirmScreen {
        align: center middle;
    }
    #kill-dialog {
        width: 50;
        height: auto;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }
    #kill-dialog Static {
        width: 100%;
        content-align: center middle;
        margin-bottom: 1;
    }
    #kill-buttons {
        width: 100%;
        height: auto;
        align: center middle;
    }
    #kill-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, pid: int, project: str) -> None:
        super().__init__()
        self._pid = pid
        self._project = project

    def compose(self) -> ComposeResult:
        with Vertical(id="kill-dialog"):
            yield Static(f"[bold red]Kill session?[/]")
            yield Static(f"PID {self._pid} · {self._project}")
            yield Static("[dim]This sends SIGTERM — the session will stop.[/]")
            with Horizontal(id="kill-buttons"):
                yield Button("Kill", variant="error", id="confirm-kill")
                yield Button("Cancel", variant="default", id="cancel-kill")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-kill")


class StatusBar(Static):
    """Top status bar showing fleet summary."""

    def update_fleet(self, fleet: FleetState) -> None:
        total = len(fleet.sessions)
        active = fleet.active_count
        max_rate = fleet.total_requests_per_hour

        parts = [f"[bold]cltop[/] — {total} session{'s' if total != 1 else ''}"]

        if fleet.api_sessions:
            spent = format_cost(fleet.api_spent_monthly)
            budget = format_cost(fleet.api_budget_monthly)
            parts.append(f"API: {spent}/{budget} mo")

        if fleet.max_sessions:
            parts.append(f"Max: {active} active · ~{max_rate:.0f} req/hr")

        hook_status = "[green]hook[/]" if is_hook_installed() else "[dim]no hook[/]"
        parts.append(hook_status)

        self.update(" · ".join(parts))


class CltopApp(App):
    """Main cltop Textual application."""

    TITLE = "cltop"
    CSS = """
    Screen {
        layout: vertical;
    }

    StatusBar {
        dock: top;
        height: 1;
        background: $accent;
        color: $text;
        padding: 0 1;
    }

    #fleet-table {
        height: 1fr;
        min-height: 6;
        border-bottom: solid $accent;
    }

    #detail-container {
        height: 2fr;
        min-height: 8;
    }

    #detail-panel {
        height: 1fr;
        padding: 0 1;
    }

    #metrics-bar {
        height: auto;
        max-height: 4;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("k", "kill_session", "Kill"),
        Binding("h", "toggle_hook", "Hook"),
        Binding("s", "cycle_sort", "Sort"),
        Binding("r", "refresh", "Refresh"),
    ]

    fleet: FleetState = FleetState()
    _selected_id: str = ""
    _refresh_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield StatusBar()
        yield FleetTable(id="fleet-table")
        with Vertical(id="detail-container"):
            yield MetricsBar(id="metrics-bar")
            yield DetailPanel(id="detail-panel")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_timer = self.set_interval(REFRESH_INTERVAL, self._refresh_fleet)
        # Initial load
        self.run_worker(self._refresh_fleet())

    async def _refresh_fleet(self) -> None:
        """Discover sessions and update all widgets."""
        try:
            self.fleet = await build_fleet_state()
        except Exception:
            return  # Don't crash on discovery failure

        # Enrich sessions with hook data
        for i, session in enumerate(self.fleet.sessions):
            self.fleet.sessions[i] = enrich_session_from_hook(session)

        # Clean up stale hook status files
        active_pids = {s.pid for s in self.fleet.sessions if s.pid is not None}
        cleanup_stale_status_files(active_pids)

        # Sort by last activity (most recent first)
        self.fleet.sessions.sort(
            key=lambda s: s.last_activity or s.started_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        # Update widgets
        self.query_one(StatusBar).update_fleet(self.fleet)
        self.query_one(FleetTable).update_sessions(self.fleet.sessions)

        # Update detail for selected session
        selected = self._find_session(self._selected_id)
        self.query_one(DetailPanel).update_session(selected)
        if selected:
            self.query_one(MetricsBar).update_metrics(selected)

    def on_data_table_row_selected(self, event: FleetTable.RowSelected) -> None:
        """Handle session selection in fleet table."""
        if event.row_key is not None:
            self._selected_id = str(event.row_key.value)
            selected = self._find_session(self._selected_id)
            self.query_one(DetailPanel).update_session(selected)
            if selected:
                self.query_one(MetricsBar).update_metrics(selected)

    def _find_session(self, session_id: str) -> Session | None:
        for s in self.fleet.sessions:
            if s.id == session_id:
                return s
        return None

    def action_kill_session(self) -> None:
        """Kill the selected session after modal confirmation."""
        session = self._find_session(self._selected_id)
        if not session or not session.pid:
            self.notify("No session selected", severity="warning")
            return

        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            import os
            import signal
            try:
                os.kill(session.pid, signal.SIGTERM)
                self.notify(f"Sent SIGTERM to PID {session.pid}")
            except ProcessLookupError:
                self.notify(f"PID {session.pid} already exited", severity="warning")
            except PermissionError:
                self.notify(f"Permission denied for PID {session.pid}", severity="error")

        self.push_screen(
            KillConfirmScreen(session.pid, session.display_name),
            on_confirm,
        )

    def action_toggle_hook(self) -> None:
        """Install or uninstall the cltop hook."""
        if is_hook_installed():
            if uninstall_hook():
                self.notify("Hook uninstalled")
            else:
                self.notify("Failed to uninstall hook", severity="error")
        else:
            if install_hook():
                self.notify("Hook installed — restart Claude Code sessions for effect")
            else:
                self.notify("Failed to install hook (is hook script deployed?)", severity="error")

    def action_cycle_sort(self) -> None:
        """Cycle sort order: activity → tokens → project."""
        # Simple cycling via a class var
        sorts = ["activity", "tokens", "project"]
        current = getattr(self, "_sort_mode", "activity")
        idx = (sorts.index(current) + 1) % len(sorts)
        self._sort_mode = sorts[idx]

        if self._sort_mode == "tokens":
            self.fleet.sessions.sort(key=lambda s: s.metrics.tokens_used, reverse=True)
        elif self._sort_mode == "project":
            self.fleet.sessions.sort(key=lambda s: s.display_name.lower())
        else:
            self.fleet.sessions.sort(
                key=lambda s: s.last_activity or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )

        self.query_one(FleetTable).update_sessions(self.fleet.sessions)
        self.notify(f"Sort: {self._sort_mode}")

    def action_refresh(self) -> None:
        """Force an immediate refresh."""
        self.run_worker(self._refresh_fleet())


def main() -> None:
    """Entry point for the cltop CLI."""
    # Handle subcommands
    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "install-hook":
            from .hooks import install_hook as do_install
            # First copy the hook script to fleet dir
            _deploy_hook_script()
            if do_install():
                print("cltop hook installed. Restart Claude Code sessions for effect.")
            else:
                print("Failed to install hook.", file=sys.stderr)
                sys.exit(1)
            return

        if cmd == "uninstall-hook":
            if uninstall_hook():
                print("cltop hook uninstalled.")
            else:
                print("Failed to uninstall hook.", file=sys.stderr)
                sys.exit(1)
            return

        if cmd == "budget":
            # cltop budget api <amount>
            if len(sys.argv) >= 4 and sys.argv[2] == "api":
                try:
                    amount = float(sys.argv[3])
                    _set_api_budget(amount)
                    print(f"API monthly budget set to ${amount:.2f}")
                except ValueError:
                    print("Usage: cltop budget api <amount>", file=sys.stderr)
                    sys.exit(1)
            else:
                print("Usage: cltop budget api <amount>", file=sys.stderr)
                sys.exit(1)
            return

        if cmd == "--version":
            from . import __version__
            print(f"cltop {__version__}")
            return

        if cmd == "--help":
            print("cltop — htop for Claude")
            print()
            print("Usage:")
            print("  cltop                  Launch the dashboard")
            print("  cltop install-hook     Install PostToolUse hook for richer data")
            print("  cltop uninstall-hook   Remove the cltop hook")
            print("  cltop budget api <$>   Set monthly API budget")
            print("  cltop --version        Show version")
            print()
            print("Keybindings:")
            print("  ↑/↓   Navigate sessions")
            print("  k      Kill selected session")
            print("  h      Toggle hook install")
            print("  s      Cycle sort order")
            print("  r      Force refresh")
            print("  q      Quit")
            return

    app = CltopApp()
    app.run()


def _deploy_hook_script() -> None:
    """Copy the bundled hook script to ~/.claude/fleet/."""
    from pathlib import Path
    import importlib.resources
    import shutil

    fleet_dir = Path.home() / ".claude" / "fleet"
    fleet_dir.mkdir(parents=True, exist_ok=True)

    dest = fleet_dir / "post_tool_use.sh"

    # Try to find the bundled hook script
    hook_source = Path(__file__).parent.parent.parent / "hook" / "post_tool_use.sh"
    if hook_source.exists():
        shutil.copy2(hook_source, dest)
        dest.chmod(0o755)
    else:
        # Write a minimal inline version
        dest.write_text(_INLINE_HOOK_SCRIPT)
        dest.chmod(0o755)


def _set_api_budget(amount: float) -> None:
    """Persist API budget to a config file."""
    import json
    from pathlib import Path

    config_path = Path.home() / ".claude" / "fleet" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    config = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
        except json.JSONDecodeError:
            pass

    config["api_budget_monthly"] = amount
    config_path.write_text(json.dumps(config, indent=2))


_INLINE_HOOK_SCRIPT = """#!/bin/bash
# cltop PostToolUse hook — writes session status to ~/.claude/fleet/
set -euo pipefail

FLEET_DIR="$HOME/.claude/fleet"
mkdir -p "$FLEET_DIR"

# Read tool call data from stdin
INPUT=$(cat)

# Extract session ID (prefer env var, fallback to PID)
SESSION_ID="${CLAUDE_SESSION_ID:-$$}"

# Extract fields with jq
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool // "unknown"')
CURRENT_TASK=$(echo "$INPUT" | jq -r '.context.current_task // ""')
PROJECT_DIR=$(echo "$INPUT" | jq -r '.context.project_dir // ""')

# Write status file using jq for proper JSON escaping
jq -n \\
  --arg session_id "$SESSION_ID" \\
  --argjson pid "$$" \\
  --arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \\
  --arg project_dir "$PROJECT_DIR" \\
  --arg current_task "$CURRENT_TASK" \\
  --arg tool_name "$TOOL_NAME" \\
  '{
    session_id: $session_id,
    pid: $pid,
    timestamp: $timestamp,
    project_dir: $project_dir,
    current_task: $current_task,
    tool_name: $tool_name
  }' > "$FLEET_DIR/$SESSION_ID.json"
"""


if __name__ == "__main__":
    main()
