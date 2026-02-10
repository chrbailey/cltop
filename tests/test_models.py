"""Tests for models module."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cltop.models import (
    FleetState,
    PlanType,
    Session,
    SessionMetrics,
    SessionSource,
    SessionStatus,
)


def test_session_metrics_context_pct():
    """Test context percentage calculation."""
    metrics = SessionMetrics(tokens_used=50_000, tokens_max=200_000)
    assert metrics.context_pct == 25.0

    # Full context
    metrics = SessionMetrics(tokens_used=200_000, tokens_max=200_000)
    assert metrics.context_pct == 100.0

    # Empty context
    metrics = SessionMetrics(tokens_used=0, tokens_max=200_000)
    assert metrics.context_pct == 0.0

    # Edge case: zero max
    metrics = SessionMetrics(tokens_used=100, tokens_max=0)
    assert metrics.context_pct == 0.0


def test_session_metrics_progress_pct():
    """Test task progress percentage calculation."""
    metrics = SessionMetrics(tasks_completed=3, tasks_total=10)
    assert metrics.progress_pct == 30.0

    # Complete
    metrics = SessionMetrics(tasks_completed=5, tasks_total=5)
    assert metrics.progress_pct == 100.0

    # No tasks
    metrics = SessionMetrics(tasks_completed=0, tasks_total=0)
    assert metrics.progress_pct == 0.0


def test_session_metrics_cost_pct():
    """Test cost percentage calculation."""
    # With budget
    metrics = SessionMetrics(cost_dollars=12.50, budget_dollars=50.0)
    assert metrics.cost_pct == 25.0

    # No budget
    metrics = SessionMetrics(cost_dollars=12.50, budget_dollars=None)
    assert metrics.cost_pct is None

    # Zero budget
    metrics = SessionMetrics(cost_dollars=12.50, budget_dollars=0.0)
    assert metrics.cost_pct is None

    # Over budget
    metrics = SessionMetrics(cost_dollars=75.0, budget_dollars=50.0)
    assert metrics.cost_pct == 150.0


def test_session_display_name_with_project():
    """Test display name generation from project path."""
    # Full path with many components
    session = Session(
        id="test1",
        pid=1234,
        source=SessionSource.CLAUDE_CODE,
        project_dir="/Volumes/OWC drive/Dev/promptspeak",
    )
    assert session.display_name == "Dev/promptspeak"

    # Single component
    session = Session(
        id="test2",
        pid=1235,
        source=SessionSource.CLAUDE_CODE,
        project_dir="promptspeak",
    )
    assert session.display_name == "promptspeak"

    # Short path with 2 components
    session = Session(
        id="test3",
        pid=1236,
        source=SessionSource.CLAUDE_CODE,
        project_dir="Dev/cltop",
    )
    assert session.display_name == "Dev/cltop"


def test_session_display_name_without_project():
    """Test display name falls back to source when no project."""
    session = Session(
        id="test1",
        pid=1234,
        source=SessionSource.CLAUDE_APP,
        project_dir="",
    )
    assert session.display_name == "claude_app"


def test_session_idle_seconds():
    """Test idle time calculation."""
    # Recent activity
    session = Session(
        id="test1",
        pid=1234,
        source=SessionSource.CLAUDE_CODE,
        last_activity=datetime.now(timezone.utc) - timedelta(seconds=10),
    )
    idle = session.idle_seconds
    assert idle is not None
    assert 9 <= idle <= 11  # Allow 1s tolerance for test execution

    # Old activity
    session = Session(
        id="test2",
        pid=1235,
        source=SessionSource.CLAUDE_CODE,
        last_activity=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    idle = session.idle_seconds
    assert idle is not None
    assert 299 <= idle <= 301

    # No activity
    session = Session(
        id="test3",
        pid=1236,
        source=SessionSource.CLAUDE_CODE,
        last_activity=None,
    )
    assert session.idle_seconds is None


def test_fleet_state_active_count():
    """Test counting active sessions."""
    fleet = FleetState(
        sessions=[
            Session(
                id="s1",
                pid=1,
                source=SessionSource.CLAUDE_CODE,
                status=SessionStatus.ACTIVE,
            ),
            Session(
                id="s2",
                pid=2,
                source=SessionSource.CLAUDE_CODE,
                status=SessionStatus.THINKING,
            ),
            Session(
                id="s3",
                pid=3,
                source=SessionSource.CLAUDE_CODE,
                status=SessionStatus.IDLE,
            ),
            Session(
                id="s4",
                pid=4,
                source=SessionSource.COWORK,
                status=SessionStatus.BACKGROUND,
            ),
            Session(
                id="s5",
                pid=5,
                source=SessionSource.CLAUDE_CODE,
                status=SessionStatus.BLOCKED,
            ),
        ]
    )

    # ACTIVE, THINKING, and BACKGROUND count as active
    assert fleet.active_count == 3


def test_fleet_state_max_vs_api_sessions():
    """Test filtering sessions by plan type."""
    max_metrics = SessionMetrics(plan_type=PlanType.MAX)
    api_metrics = SessionMetrics(plan_type=PlanType.API)

    fleet = FleetState(
        sessions=[
            Session(
                id="s1",
                pid=1,
                source=SessionSource.CLAUDE_CODE,
                metrics=max_metrics,
            ),
            Session(
                id="s2",
                pid=2,
                source=SessionSource.CLAUDE_CODE,
                metrics=max_metrics,
            ),
            Session(
                id="s3",
                pid=3,
                source=SessionSource.API,
                metrics=api_metrics,
            ),
        ]
    )

    assert len(fleet.max_sessions) == 2
    assert len(fleet.api_sessions) == 1
    assert fleet.max_sessions[0].id in ("s1", "s2")
    assert fleet.api_sessions[0].id == "s3"


def test_fleet_state_total_requests_per_hour():
    """Test aggregate request rate for Max sessions."""
    fleet = FleetState(
        sessions=[
            Session(
                id="s1",
                pid=1,
                source=SessionSource.CLAUDE_CODE,
                metrics=SessionMetrics(
                    plan_type=PlanType.MAX, requests_per_hour=12.5
                ),
            ),
            Session(
                id="s2",
                pid=2,
                source=SessionSource.CLAUDE_CODE,
                metrics=SessionMetrics(
                    plan_type=PlanType.MAX, requests_per_hour=8.0
                ),
            ),
            Session(
                id="s3",
                pid=3,
                source=SessionSource.API,
                metrics=SessionMetrics(
                    plan_type=PlanType.API, requests_per_hour=100.0
                ),
            ),
        ]
    )

    # Only Max sessions count toward rate limit
    assert fleet.total_requests_per_hour == 20.5
