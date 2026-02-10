"""Capture a polished demo SVG of cltop with realistic mock data."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from cltop.app import CltopApp, StatusBar
from cltop.models import (
    FleetState,
    PlanType,
    Session,
    SessionMetrics,
    SessionSource,
    SessionStatus,
    ToolCall,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mock_fleet() -> FleetState:
    """Build a realistic-looking fleet with varied session states."""
    now = _now()

    sessions = [
        Session(
            id="78421",
            pid=78421,
            source=SessionSource.CLAUDE_CODE,
            status=SessionStatus.ACTIVE,
            project_dir="/Users/dev/projects/cltop",
            branch="main",
            current_task="Fix security review findings from round 2",
            current_file="hooks.py",
            started_at=now - timedelta(hours=1, minutes=23),
            last_activity=now - timedelta(seconds=2),
            has_hook=True,
            metrics=SessionMetrics(
                tokens_used=142_800,
                tokens_max=200_000,
                tasks_completed=5,
                tasks_total=8,
                plan_type=PlanType.MAX,
                requests_per_hour=67.3,
            ),
            recent_tools=[
                ToolCall(timestamp=now - timedelta(minutes=4, seconds=12), tool_name="Read", summary="Read discovery.py"),
                ToolCall(timestamp=now - timedelta(minutes=3, seconds=45), tool_name="Edit", summary="Edit hooks.py"),
                ToolCall(timestamp=now - timedelta(minutes=3, seconds=8), tool_name="Bash", summary="Bash: pytest"),
                ToolCall(timestamp=now - timedelta(minutes=2, seconds=30), tool_name="Grep", summary="Grep: _safe_write"),
                ToolCall(timestamp=now - timedelta(minutes=1, seconds=55), tool_name="Edit", summary="Edit app.py"),
                ToolCall(timestamp=now - timedelta(minutes=1, seconds=12), tool_name="Bash", summary="Bash: pytest", duration_ms=1230),
                ToolCall(timestamp=now - timedelta(seconds=38), tool_name="Read", summary="Read pricing.py", duration_ms=45),
                ToolCall(timestamp=now - timedelta(seconds=8), tool_name="Edit", summary="Edit hooks.py", duration_ms=None),
            ],
        ),
        Session(
            id="78590",
            pid=78590,
            source=SessionSource.CLAUDE_CODE,
            status=SessionStatus.THINKING,
            project_dir="/Users/dev/projects/promptspeak/mcp-server",
            branch="feat/slim-modules",
            current_task="Remove swarm module and update exports",
            current_file="index.ts",
            started_at=now - timedelta(hours=2, minutes=47),
            last_activity=now - timedelta(seconds=18),
            has_hook=True,
            metrics=SessionMetrics(
                tokens_used=89_400,
                tokens_max=200_000,
                tasks_completed=3,
                tasks_total=6,
                plan_type=PlanType.MAX,
                requests_per_hour=42.1,
            ),
            recent_tools=[
                ToolCall(timestamp=now - timedelta(minutes=2), tool_name="Glob", summary="Glob: **/*.ts"),
                ToolCall(timestamp=now - timedelta(minutes=1, seconds=30), tool_name="Edit", summary="Edit index.ts"),
                ToolCall(timestamp=now - timedelta(seconds=18), tool_name="Bash", summary="Bash: npm"),
            ],
        ),
        Session(
            id="77103",
            pid=77103,
            source=SessionSource.CLAUDE_CODE,
            status=SessionStatus.IDLE,
            project_dir="/Users/dev/projects/daily-heat",
            branch="main",
            current_task="",
            current_file="",
            started_at=now - timedelta(hours=5, minutes=12),
            last_activity=now - timedelta(minutes=38),
            has_hook=False,
            metrics=SessionMetrics(
                tokens_used=178_200,
                tokens_max=200_000,
                tasks_completed=0,
                tasks_total=0,
                plan_type=PlanType.MAX,
                requests_per_hour=0.0,
            ),
            recent_tools=[],
        ),
        Session(
            id="79001",
            pid=79001,
            source=SessionSource.COWORK,
            status=SessionStatus.BACKGROUND,
            project_dir="/Users/dev/projects/cltop",
            branch="main",
            current_task="Write security tests for hooks module",
            current_file="test_hooks.py",
            started_at=now - timedelta(minutes=12),
            last_activity=now - timedelta(seconds=5),
            has_hook=True,
            metrics=SessionMetrics(
                tokens_used=24_600,
                tokens_max=200_000,
                tasks_completed=2,
                tasks_total=3,
                plan_type=PlanType.MAX,
                requests_per_hour=94.7,
            ),
            recent_tools=[
                ToolCall(timestamp=now - timedelta(seconds=30), tool_name="Write", summary="Write test_hooks.py"),
                ToolCall(timestamp=now - timedelta(seconds=5), tool_name="Bash", summary="Bash: pytest", duration_ms=None),
            ],
        ),
        Session(
            id="76200",
            pid=76200,
            source=SessionSource.CLAUDE_APP,
            status=SessionStatus.BLOCKED,
            project_dir="",
            branch="",
            current_task="",
            current_file="",
            started_at=now - timedelta(hours=3),
            last_activity=now - timedelta(minutes=4),
            has_hook=False,
            metrics=SessionMetrics(
                tokens_used=56_000,
                tokens_max=200_000,
                plan_type=PlanType.MAX,
                requests_per_hour=12.4,
            ),
            recent_tools=[],
        ),
    ]

    return FleetState(sessions=sessions)


async def capture() -> None:
    """Run the app with mock data and capture SVG screenshot."""
    fleet = _mock_fleet()

    # Patch discovery so the app uses our mock data
    with patch("cltop.app.build_fleet_state", new_callable=AsyncMock, return_value=fleet):
        with patch("cltop.app.is_hook_installed", return_value=True):
            with patch("cltop.app.enrich_session_from_hook", side_effect=lambda s: s):
                with patch("cltop.app.cleanup_stale_status_files", return_value=0):
                    async with CltopApp().run_test(size=(120, 36)) as pilot:
                        # Wait for initial load
                        await pilot.pause()
                        await pilot.pause()

                        # Move to first row and select it (Enter triggers RowSelected)
                        await pilot.press("down")
                        await pilot.pause()
                        await pilot.press("enter")
                        await pilot.pause()

                        # Capture
                        pilot.app.save_screenshot("demo/demo.svg")


if __name__ == "__main__":
    asyncio.run(capture())
