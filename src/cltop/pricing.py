"""Token pricing and cost estimation for Claude models."""

from __future__ import annotations

from .models import PlanType

# Pricing per million tokens (USD) as of Feb 2026
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"input": 0.80, "output": 4.0},
}

# Default model when we can't detect
DEFAULT_MODEL = "claude-sonnet-4-5"

# Rough heuristic: bytes in JSONL → approximate tokens
# Based on observation: ~3.5 bytes per token in conversation JSONL
BYTES_PER_TOKEN = 3.5


def estimate_tokens_from_bytes(byte_count: int) -> int:
    """Rough token estimate from JSONL file size."""
    return max(0, int(byte_count / BYTES_PER_TOKEN))


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    model: str = DEFAULT_MODEL,
) -> float:
    """Estimate dollar cost for token usage."""
    pricing = MODEL_PRICING.get(model, MODEL_PRICING[DEFAULT_MODEL])
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost


def detect_plan_type(pid: int | None, source: str) -> PlanType:
    """Infer whether a session is on Max plan or API billing.

    Heuristic: Claude Code CLI and Claude.app are typically Max plan.
    Explicit API processes or unknown sources default to API.
    """
    if source in ("claude_code", "claude_app", "cowork"):
        return PlanType.MAX
    return PlanType.API


def format_cost(dollars: float) -> str:
    """Format dollar amount for display."""
    if dollars < 0.01:
        return "<$0.01"
    if dollars < 1.0:
        return f"${dollars:.2f}"
    return f"${dollars:.2f}"


def format_tokens(count: int) -> str:
    """Format token count for display (e.g., 48.2K, 1.2M)."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)
