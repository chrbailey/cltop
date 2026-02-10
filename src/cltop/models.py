"""Data models for cltop sessions and metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class SessionStatus(Enum):
    ACTIVE = "active"       # Tool call within last 10s
    THINKING = "thinking"   # API call in flight, no recent tool result
    IDLE = "idle"           # No activity > 30s
    BLOCKED = "blocked"     # Waiting on user input
    BACKGROUND = "background"  # Cowork/subagent session
    UNKNOWN = "unknown"


class SessionSource(Enum):
    CLAUDE_CODE = "claude_code"   # CLI session
    CLAUDE_APP = "claude_app"     # Desktop app
    COWORK = "cowork"             # Background agent
    API = "api"                   # Direct API usage


class PlanType(Enum):
    MAX = "max"   # Max plan — rate-limited, not token-billed
    API = "api"   # API — dollar-billed per token


@dataclass
class ToolCall:
    """A single tool invocation from a session."""
    timestamp: datetime
    tool_name: str
    summary: str  # e.g., "Read src/foo.ts" or "Bash npm test"
    duration_ms: int | None = None


@dataclass
class SessionMetrics:
    """Metrics for a single session."""
    # Context usage
    tokens_used: int = 0
    tokens_max: int = 200_000  # Default context window

    # Progress (from TodoList or hook)
    tasks_completed: int = 0
    tasks_total: int = 0
    estimated_progress_pct: float | None = None  # Time-based estimate

    # Cost / Rate
    plan_type: PlanType = PlanType.MAX
    cost_dollars: float = 0.0
    budget_dollars: float | None = None  # User-set budget (API only)
    requests_per_hour: float = 0.0

    @property
    def context_pct(self) -> float:
        if self.tokens_max == 0:
            return 0.0
        return (self.tokens_used / self.tokens_max) * 100

    @property
    def progress_pct(self) -> float:
        if self.tasks_total == 0:
            return 0.0
        return (self.tasks_completed / self.tasks_total) * 100

    @property
    def cost_pct(self) -> float | None:
        if self.budget_dollars is None or self.budget_dollars == 0:
            return None
        return (self.cost_dollars / self.budget_dollars) * 100


@dataclass
class Session:
    """A discovered Claude session."""
    id: str                           # Unique identifier (PID or session hash)
    pid: int | None                   # OS process ID
    source: SessionSource
    status: SessionStatus = SessionStatus.UNKNOWN
    project_dir: str = ""             # Working directory / project name
    branch: str = ""                  # Git branch if detectable
    current_task: str = ""            # What the session is doing now
    current_file: str = ""            # File being edited/read
    started_at: datetime | None = None
    last_activity: datetime | None = None
    metrics: SessionMetrics = field(default_factory=SessionMetrics)
    recent_tools: list[ToolCall] = field(default_factory=list)
    has_hook: bool = False            # Whether Layer 2 hook data is available
    jsonl_path: Path | None = None    # Path to session transcript

    @property
    def display_name(self) -> str:
        if self.project_dir:
            # Shorten to last 2 path components
            parts = Path(self.project_dir).parts
            return "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
        return self.source.value

    @property
    def idle_seconds(self) -> float | None:
        if self.last_activity is None:
            return None
        return (datetime.now(timezone.utc) - self.last_activity).total_seconds()


@dataclass
class FleetState:
    """Aggregate state of all Claude sessions."""
    sessions: list[Session] = field(default_factory=list)
    api_budget_monthly: float = 50.0  # User's monthly API budget
    api_spent_monthly: float = 0.0    # Month-to-date API spend

    @property
    def active_count(self) -> int:
        return sum(1 for s in self.sessions if s.status in (
            SessionStatus.ACTIVE, SessionStatus.THINKING, SessionStatus.BACKGROUND
        ))

    @property
    def max_sessions(self) -> list[Session]:
        return [s for s in self.sessions if s.metrics.plan_type == PlanType.MAX]

    @property
    def api_sessions(self) -> list[Session]:
        return [s for s in self.sessions if s.metrics.plan_type == PlanType.API]

    @property
    def total_requests_per_hour(self) -> float:
        return sum(s.metrics.requests_per_hour for s in self.max_sessions)
