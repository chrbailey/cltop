"""Tri-bar metrics display widget."""

from __future__ import annotations

from textual.widgets import Static

from ..models import PlanType, Session


class MetricsBar(Static):
    """Tri-bar metrics display (context, progress, rate/cost)."""

    BAR_WIDTH = 20
    FILLED_CHAR = "█"
    EMPTY_CHAR = "░"

    def update_metrics(self, session: Session) -> None:
        """Render the three metric bars for a session."""
        lines: list[str] = []

        # Bar 1: Context (tokens used / max)
        lines.append(self._render_context_bar(session))

        # Bar 2: Progress (tasks completed / total)
        lines.append(self._render_progress_bar(session))

        # Bar 3: Rate|Cost
        lines.append(self._render_rate_cost_bar(session))

        self.update("\n".join(lines))

    def _render_context_bar(self, session: Session) -> str:
        """Render the context usage bar."""
        metrics = session.metrics
        pct = metrics.context_pct
        label = f"Context: {metrics.tokens_used:,} / {metrics.tokens_max:,}"
        bar = self._create_bar(pct)
        return f"{label:40s} {bar} {pct:5.1f}%"

    def _render_progress_bar(self, session: Session) -> str:
        """Render the task progress bar."""
        metrics = session.metrics
        pct = metrics.progress_pct

        # Use estimated progress if available and tasks are zero
        estimated_marker = ""
        if metrics.estimated_progress_pct is not None and metrics.tasks_total == 0:
            pct = metrics.estimated_progress_pct
            estimated_marker = f" [dim](est {pct:.0f}%)[/]"

        label = f"Progress: {metrics.tasks_completed} / {metrics.tasks_total}"
        bar = self._create_bar(pct)
        return f"{label:40s} {bar} {pct:5.1f}%{estimated_marker}"

    def _render_rate_cost_bar(self, session: Session) -> str:
        """Render the rate/cost bar based on plan type."""
        metrics = session.metrics

        if metrics.plan_type == PlanType.MAX:
            # Show requests per hour with intensity label
            req_per_hour = metrics.requests_per_hour
            intensity = self._get_intensity_label(req_per_hour)
            label = f"Rate: {req_per_hour:.1f} req/hr"

            # Use arbitrary thresholds for rate visualization
            # 0-60 req/hr = normal, 60-120 = high, 120+ = very high
            pct = min((req_per_hour / 120) * 100, 100)
            bar = self._create_bar(pct)
            return f"{label:40s} {bar} {intensity}"

        else:
            # API plan: show cost vs budget
            cost = metrics.cost_dollars
            budget = metrics.budget_dollars

            if budget is None or budget == 0:
                label = f"Cost: ${cost:.2f}"
                bar = self._create_bar(0)
                return f"{label:40s} {bar} [dim]no budget set[/]"

            cost_pct = metrics.cost_pct or 0
            label = f"Cost: ${cost:.2f} / ${budget:.2f}"
            bar = self._create_bar(cost_pct)

            # Warning threshold at 60% and 85%
            warning = ""
            if cost_pct >= 85:
                warning = " [red bold]CRITICAL[/]"
            elif cost_pct >= 60:
                warning = " [yellow]WARNING[/]"

            return f"{label:40s} {bar} {cost_pct:5.1f}%{warning}"

    def _create_bar(self, pct: float) -> str:
        """Create a single progress bar with color coding."""
        filled_count = int((pct / 100) * self.BAR_WIDTH)
        filled_count = max(0, min(filled_count, self.BAR_WIDTH))
        empty_count = self.BAR_WIDTH - filled_count

        filled = self.FILLED_CHAR * filled_count
        empty = self.EMPTY_CHAR * empty_count

        # Color based on percentage thresholds
        if pct >= 85:
            color = "red"
        elif pct >= 60:
            color = "yellow"
        else:
            color = "green"

        return f"[{color}]{filled}[/][dim]{empty}[/]"

    @staticmethod
    def _get_intensity_label(req_per_hour: float) -> str:
        """Return intensity label for request rate."""
        if req_per_hour < 30:
            return "[green]Low[/]"
        if req_per_hour < 60:
            return "[green]Normal[/]"
        if req_per_hour < 90:
            return "[yellow]High[/]"
        if req_per_hour < 120:
            return "[yellow]Very High[/]"
        return "[red]Extreme[/]"
