"""Tests for hooks module."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cltop.hooks import (
    cleanup_stale_status_files,
    is_hook_installed,
    read_hook_status,
)


def test_read_hook_status_valid_file(tmp_path: Path):
    """Test reading a valid hook status file."""
    # Create a temporary fleet directory
    fleet_dir = tmp_path / "fleet"
    fleet_dir.mkdir()

    # Write a valid status file
    status_data = {
        "pid": 1234,
        "current_task": "Writing tests",
        "tokens_estimate": 50000,
        "tasks_completed": 3,
        "tasks_total": 10,
    }
    status_file = fleet_dir / "test_session.json"
    status_file.write_text(json.dumps(status_data))

    # Mock FLEET_DIR to use our tmp_path
    with patch("cltop.hooks.FLEET_DIR", fleet_dir):
        result = read_hook_status("test_session")
        assert result is not None
        assert result["pid"] == 1234
        assert result["current_task"] == "Writing tests"
        assert result["tokens_estimate"] == 50000


def test_read_hook_status_missing_file(tmp_path: Path):
    """Test reading a non-existent status file returns None."""
    fleet_dir = tmp_path / "fleet"
    fleet_dir.mkdir()

    with patch("cltop.hooks.FLEET_DIR", fleet_dir):
        result = read_hook_status("nonexistent_session")
        assert result is None


def test_read_hook_status_corrupt_json(tmp_path: Path):
    """Test reading a corrupt JSON file returns None."""
    fleet_dir = tmp_path / "fleet"
    fleet_dir.mkdir()

    # Write invalid JSON
    status_file = fleet_dir / "corrupt.json"
    status_file.write_text("{not valid json")

    with patch("cltop.hooks.FLEET_DIR", fleet_dir):
        result = read_hook_status("corrupt")
        assert result is None


def test_cleanup_stale_status_files_removes_dead_pids(tmp_path: Path):
    """Test cleanup removes status files for dead PIDs."""
    fleet_dir = tmp_path / "fleet"
    fleet_dir.mkdir()

    # Create status files for various PIDs
    active_status = fleet_dir / "active_1234.json"
    active_status.write_text(json.dumps({"pid": 1234}))

    stale_status = fleet_dir / "stale_9999.json"
    stale_status.write_text(json.dumps({"pid": 9999}))

    # Mark PID 1234 as active, 9999 as dead
    active_pids = {1234}

    with patch("cltop.hooks.FLEET_DIR", fleet_dir):
        removed = cleanup_stale_status_files(active_pids)

        # Should remove 1 file (stale_9999)
        assert removed == 1
        assert active_status.exists()
        assert not stale_status.exists()


def test_cleanup_stale_status_files_removes_corrupt(tmp_path: Path):
    """Test cleanup removes corrupt status files."""
    fleet_dir = tmp_path / "fleet"
    fleet_dir.mkdir()

    # Create a corrupt status file
    corrupt_status = fleet_dir / "corrupt.json"
    corrupt_status.write_text("{invalid")

    active_pids = set()

    with patch("cltop.hooks.FLEET_DIR", fleet_dir):
        removed = cleanup_stale_status_files(active_pids)

        # Should remove corrupt file
        assert removed == 1
        assert not corrupt_status.exists()


def test_cleanup_stale_status_files_no_fleet_dir(tmp_path: Path):
    """Test cleanup handles missing fleet directory gracefully."""
    nonexistent_dir = tmp_path / "nonexistent_fleet"

    with patch("cltop.hooks.FLEET_DIR", nonexistent_dir):
        removed = cleanup_stale_status_files(set())
        assert removed == 0


def test_is_hook_installed_true(tmp_path: Path):
    """Test detecting installed hook."""
    settings_file = tmp_path / "settings.json"
    fleet_dir = tmp_path / "fleet"
    fleet_dir.mkdir()
    hook_script = fleet_dir / "post_tool_use.sh"

    settings_data = {
        "hooks": {
            "PostToolUse": [
                {"matcher": "", "command": str(hook_script)}
            ]
        }
    }
    settings_file.write_text(json.dumps(settings_data))

    with patch("cltop.hooks.SETTINGS_PATH", settings_file):
        with patch("cltop.hooks.HOOK_SCRIPT_PATH", hook_script):
            assert is_hook_installed() is True


def test_is_hook_installed_false_no_settings(tmp_path: Path):
    """Test detecting hook when settings.json doesn't exist."""
    settings_file = tmp_path / "nonexistent_settings.json"

    with patch("cltop.hooks.SETTINGS_PATH", settings_file):
        assert is_hook_installed() is False


def test_is_hook_installed_false_no_hooks(tmp_path: Path):
    """Test detecting hook when settings.json has no hooks."""
    settings_file = tmp_path / "settings.json"
    settings_data = {"other_config": "value"}
    settings_file.write_text(json.dumps(settings_data))

    with patch("cltop.hooks.SETTINGS_PATH", settings_file):
        assert is_hook_installed() is False


def test_is_hook_installed_false_corrupt_json(tmp_path: Path):
    """Test detecting hook when settings.json is corrupt."""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{invalid json")

    with patch("cltop.hooks.SETTINGS_PATH", settings_file):
        assert is_hook_installed() is False


def test_is_hook_installed_false_different_hook(tmp_path: Path):
    """Test detecting hook when different hook is installed."""
    settings_file = tmp_path / "settings.json"
    fleet_dir = tmp_path / "fleet"
    fleet_dir.mkdir()
    hook_script = fleet_dir / "post_tool_use.sh"

    settings_data = {
        "hooks": {
            "PostToolUse": [
                {"matcher": "", "command": "/some/other/hook.sh"}
            ]
        }
    }
    settings_file.write_text(json.dumps(settings_data))

    with patch("cltop.hooks.SETTINGS_PATH", settings_file):
        with patch("cltop.hooks.HOOK_SCRIPT_PATH", hook_script):
            assert is_hook_installed() is False
