"""Tests for pricing module."""

import pytest

from cltop.pricing import (
    BYTES_PER_TOKEN,
    DEFAULT_MODEL,
    detect_plan_type,
    estimate_cost,
    estimate_tokens_from_bytes,
    format_cost,
    format_tokens,
)
from cltop.models import PlanType


def test_estimate_tokens_from_bytes():
    """Test token estimation from byte count."""
    # 3.5 bytes per token (heuristic)
    assert estimate_tokens_from_bytes(3500) == 1000
    assert estimate_tokens_from_bytes(7000) == 2000
    assert estimate_tokens_from_bytes(350) == 100

    # Edge cases
    assert estimate_tokens_from_bytes(0) == 0
    assert estimate_tokens_from_bytes(1) == 0  # Rounds down


def test_estimate_cost_opus():
    """Test cost estimation for Claude Opus 4.6."""
    # 1M input tokens @ $15/M + 500K output tokens @ $75/M
    cost = estimate_cost(1_000_000, 500_000, model="claude-opus-4-6")
    expected = 15.0 + 37.5
    assert cost == pytest.approx(expected, abs=0.01)


def test_estimate_cost_sonnet():
    """Test cost estimation for Claude Sonnet 4.5."""
    # 2M input tokens @ $3/M + 1M output tokens @ $15/M
    cost = estimate_cost(2_000_000, 1_000_000, model="claude-sonnet-4-5")
    expected = 6.0 + 15.0
    assert cost == pytest.approx(expected, abs=0.01)


def test_estimate_cost_haiku():
    """Test cost estimation for Claude Haiku 4.5."""
    # 10M input tokens @ $0.80/M + 5M output tokens @ $4/M
    cost = estimate_cost(10_000_000, 5_000_000, model="claude-haiku-4-5")
    expected = 8.0 + 20.0
    assert cost == pytest.approx(expected, abs=0.01)


def test_estimate_cost_default_model():
    """Test cost estimation with default model."""
    # Should use Sonnet as default
    cost = estimate_cost(1_000_000, 500_000)
    expected = 3.0 + 7.5  # Sonnet pricing
    assert cost == pytest.approx(expected, abs=0.01)


def test_estimate_cost_unknown_model():
    """Test cost estimation with unknown model falls back to default."""
    cost = estimate_cost(1_000_000, 500_000, model="claude-unknown-99")
    expected = 3.0 + 7.5  # Should fall back to Sonnet
    assert cost == pytest.approx(expected, abs=0.01)


def test_detect_plan_type_claude_code():
    """Test plan type detection for Claude Code CLI."""
    assert detect_plan_type(1234, "claude_code") == PlanType.MAX


def test_detect_plan_type_claude_app():
    """Test plan type detection for Claude desktop app."""
    assert detect_plan_type(1234, "claude_app") == PlanType.MAX


def test_detect_plan_type_cowork():
    """Test plan type detection for cowork/background sessions."""
    assert detect_plan_type(1234, "cowork") == PlanType.MAX


def test_detect_plan_type_api():
    """Test plan type detection for API sessions."""
    assert detect_plan_type(1234, "api") == PlanType.API
    assert detect_plan_type(None, "api") == PlanType.API


def test_detect_plan_type_unknown():
    """Test plan type detection for unknown sources defaults to API."""
    assert detect_plan_type(1234, "unknown") == PlanType.API
    assert detect_plan_type(None, "unknown") == PlanType.API


def test_format_cost_sub_penny():
    """Test formatting very small dollar amounts."""
    assert format_cost(0.001) == "<$0.01"
    assert format_cost(0.009) == "<$0.01"


def test_format_cost_sub_dollar():
    """Test formatting amounts under $1."""
    assert format_cost(0.01) == "$0.01"
    assert format_cost(0.42) == "$0.42"
    assert format_cost(0.99) == "$0.99"


def test_format_cost_dollars():
    """Test formatting dollar amounts."""
    assert format_cost(1.00) == "$1.00"
    assert format_cost(12.50) == "$12.50"
    assert format_cost(123.45) == "$123.45"


def test_format_tokens_small():
    """Test formatting token counts under 1K."""
    assert format_tokens(0) == "0"
    assert format_tokens(1) == "1"
    assert format_tokens(999) == "999"


def test_format_tokens_thousands():
    """Test formatting token counts in thousands."""
    assert format_tokens(1_000) == "1.0K"
    assert format_tokens(1_500) == "1.5K"
    assert format_tokens(48_200) == "48.2K"
    assert format_tokens(999_999) == "1000.0K"


def test_format_tokens_millions():
    """Test formatting token counts in millions."""
    assert format_tokens(1_000_000) == "1.0M"
    assert format_tokens(1_500_000) == "1.5M"
    assert format_tokens(12_345_678) == "12.3M"


# --- Security tests for negative token clamping ---


def test_estimate_tokens_negative_bytes():
    """Negative byte input must return 0, not a negative token count."""
    result = estimate_tokens_from_bytes(-100)
    assert result == 0
    result = estimate_tokens_from_bytes(-1)
    assert result == 0
    # Large negative value
    result = estimate_tokens_from_bytes(-999_999_999)
    assert result == 0


def test_estimate_tokens_zero_bytes():
    """Zero byte input returns exactly 0 tokens."""
    result = estimate_tokens_from_bytes(0)
    assert result == 0
