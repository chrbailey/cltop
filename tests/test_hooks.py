"""Tests for hooks module."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cltop.hooks import (
    _safe_write_settings,
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


# --- Security tests for _safe_write_settings ---


def test_safe_write_settings_creates_file(tmp_path: Path):
    """_safe_write_settings writes settings to a new path that didn't exist before."""
    settings_file = tmp_path / "settings.json"

    with patch("cltop.hooks.SETTINGS_PATH", settings_file):
        result = _safe_write_settings({"hooks": {}})

    assert result is True
    assert settings_file.exists()
    data = json.loads(settings_file.read_text())
    assert data == {"hooks": {}}


def test_safe_write_settings_atomic_rename(tmp_path: Path):
    """After _safe_write_settings returns True, the final file must exist (no leftover .tmp)."""
    settings_file = tmp_path / "settings.json"

    with patch("cltop.hooks.SETTINGS_PATH", settings_file):
        result = _safe_write_settings({"key": "value"})

    assert result is True
    assert settings_file.exists()

    # No stale .tmp files should remain in the directory
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == [], f"Leftover temp files found: {tmp_files}"

    # Verify content is valid JSON with expected data
    data = json.loads(settings_file.read_text())
    assert data["key"] == "value"


def test_safe_write_settings_returns_false_on_bad_dir(tmp_path: Path):
    """_safe_write_settings returns False when the directory exists but is unwritable.

    The parent directory must already exist (so mkdir succeeds), but we make
    the directory unwritable so the lock file open() fails, which is caught
    by the outer try/except OSError and returns False.
    """
    target_dir = tmp_path / "unwritable"
    target_dir.mkdir()
    settings_file = target_dir / "settings.json"

    # Make the directory unwritable so the lock file cannot be created
    target_dir.chmod(0o444)

    try:
        with patch("cltop.hooks.SETTINGS_PATH", settings_file):
            result = _safe_write_settings({"hooks": {}})

        assert result is False
    finally:
        # Restore permissions so pytest can clean up tmp_path
        target_dir.chmod(0o755)

    # Verify file was not created (check after restoring permissions)
    assert not settings_file.exists()


# --- Security tests for cleanup_stale_status_files ---


def test_cleanup_skips_config_json(tmp_path: Path):
    """cleanup_stale_status_files must never delete config.json even if it has a stale PID."""
    fleet_dir = tmp_path / "fleet"
    fleet_dir.mkdir()

    # config.json contains a PID that is NOT in active_pids — but it must survive
    config_file = fleet_dir / "config.json"
    config_file.write_text(json.dumps({"pid": 9999, "some_setting": True}))

    # Also create a normal stale status file that SHOULD be removed
    stale_file = fleet_dir / "stale_session.json"
    stale_file.write_text(json.dumps({"pid": 8888}))

    active_pids: set[int] = set()  # No active PIDs

    with patch("cltop.hooks.FLEET_DIR", fleet_dir):
        removed = cleanup_stale_status_files(active_pids)

    # config.json must survive
    assert config_file.exists(), "config.json was deleted by cleanup — this is a bug"
    # The stale session file should have been removed
    assert not stale_file.exists()
    assert removed == 1


def test_cleanup_validates_pid_type(tmp_path: Path):
    """A status file with a non-integer pid must not crash cleanup."""
    fleet_dir = tmp_path / "fleet"
    fleet_dir.mkdir()

    # Status file where pid is a string instead of int
    bad_pid_file = fleet_dir / "bad_pid.json"
    bad_pid_file.write_text(json.dumps({"pid": "not-a-number"}))

    # Status file where pid is null
    null_pid_file = fleet_dir / "null_pid.json"
    null_pid_file.write_text(json.dumps({"pid": None}))

    # Status file where pid key is missing entirely
    no_pid_file = fleet_dir / "no_pid.json"
    no_pid_file.write_text(json.dumps({"current_task": "something"}))

    active_pids: set[int] = set()

    with patch("cltop.hooks.FLEET_DIR", fleet_dir):
        # This must not raise — non-integer pids should be silently skipped
        removed = cleanup_stale_status_files(active_pids)

    # None of these files should have been removed, because the code only
    # removes files where isinstance(pid, int) and pid not in active_pids.
    # Non-int pids don't match the condition, so the files are left in place.
    assert bad_pid_file.exists()
    assert null_pid_file.exists()
    assert no_pid_file.exists()
    assert removed == 0
