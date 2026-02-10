"""Optional Layer 2 enrichment via PostToolUse hook."""

from __future__ import annotations

import fcntl
import json
import tempfile
from datetime import datetime
from pathlib import Path

from .models import Session


FLEET_DIR = Path.home() / ".claude" / "fleet"
SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
HOOK_SCRIPT_PATH = FLEET_DIR / "post_tool_use.sh"


def _safe_write_settings(settings: dict) -> bool:
    """Atomic, locked write of settings.json.

    Uses flock + temp file + rename to prevent corruption from concurrent writes
    (e.g., Claude Code writing settings at the same moment).
    """
    lock_path = SETTINGS_PATH.with_suffix(".json.lock")
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(lock_path, "w") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                fd = tempfile.NamedTemporaryFile(
                    mode="w", dir=SETTINGS_PATH.parent, suffix=".tmp", delete=False
                )
                tmp_path = Path(fd.name)
                json.dump(settings, fd, indent=2)
                fd.flush()
                fd.close()
                tmp_path.rename(SETTINGS_PATH)
                return True
            except OSError:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
                return False
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
    except OSError:
        return False


def read_hook_status(session_id: str) -> dict | None:
    """Read a session's status file from ~/.claude/fleet/{session_id}.json.

    Returns the parsed JSON dict, or None if file doesn't exist or is invalid.
    """
    status_file = FLEET_DIR / f"{session_id}.json"
    if not status_file.exists():
        return None

    try:
        with status_file.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def enrich_session_from_hook(session: Session) -> Session:
    """If hook status exists for this session, merge richer data into it.

    Hook data provides:
    - current_task (more detailed)
    - current_file (from tool calls)
    - tokens_estimate (cumulative estimate)
    - tasks_completed / tasks_total (from TodoList)
    - timestamp (last tool call time)

    Returns the enriched Session (modifies in place).
    """
    status = read_hook_status(session.id)
    if status is None:
        return session

    session.has_hook = True

    # Update current task/file if available
    if status.get("current_task"):
        session.current_task = status["current_task"]
    if status.get("current_file"):
        session.current_file = status["current_file"]

    # Update project_dir if we didn't have it
    if status.get("project_dir") and not session.project_dir:
        session.project_dir = status["project_dir"]

    # Update last_activity from hook timestamp
    if status.get("timestamp"):
        try:
            session.last_activity = datetime.fromisoformat(
                status["timestamp"].replace("Z", "+00:00")
            )
        except (ValueError, AttributeError):
            pass

    # Update token estimate
    if status.get("tokens_estimate"):
        session.metrics.tokens_used = status["tokens_estimate"]

    # Update task progress
    if status.get("tasks_completed") is not None:
        session.metrics.tasks_completed = status["tasks_completed"]
    if status.get("tasks_total") is not None:
        session.metrics.tasks_total = status["tasks_total"]

    return session


def install_hook() -> bool:
    """Add the PostToolUse hook to ~/.claude/settings.json.

    Preserves existing hooks — appends to the PostToolUse array.
    Creates settings.json if it doesn't exist.

    Returns True if installed successfully, False otherwise.
    """
    # Ensure fleet directory and hook script exist
    FLEET_DIR.mkdir(parents=True, exist_ok=True)
    if not HOOK_SCRIPT_PATH.exists():
        return False  # Hook script must be written first

    # Read or create settings
    settings = {}
    if SETTINGS_PATH.exists():
        try:
            with SETTINGS_PATH.open() as f:
                settings = json.load(f)
        except json.JSONDecodeError:
            return False  # Refuse to overwrite corrupt settings
        except OSError:
            return False

    # Ensure hooks object exists
    if "hooks" not in settings:
        settings["hooks"] = {}
    if "PostToolUse" not in settings["hooks"]:
        settings["hooks"]["PostToolUse"] = []

    # Check if our hook is already installed
    hook_entry = {
        "matcher": "",
        "command": str(HOOK_SCRIPT_PATH)
    }

    if hook_entry in settings["hooks"]["PostToolUse"]:
        return True  # Already installed

    # Append our hook
    settings["hooks"]["PostToolUse"].append(hook_entry)

    # Atomic locked write
    return _safe_write_settings(settings)


def uninstall_hook() -> bool:
    """Remove the cltop hook from settings.

    Returns True if removed (or wasn't present), False on error.
    """
    if not SETTINGS_PATH.exists():
        return True  # Nothing to remove

    try:
        with SETTINGS_PATH.open() as f:
            settings = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False  # Refuse to overwrite corrupt settings

    # Remove our hook entry
    hook_entry = {
        "matcher": "",
        "command": str(HOOK_SCRIPT_PATH)
    }

    if "hooks" in settings and "PostToolUse" in settings["hooks"]:
        settings["hooks"]["PostToolUse"] = [
            h for h in settings["hooks"]["PostToolUse"]
            if h != hook_entry
        ]

        # Clean up empty structures
        if not settings["hooks"]["PostToolUse"]:
            del settings["hooks"]["PostToolUse"]
        if not settings["hooks"]:
            del settings["hooks"]

    # Atomic locked write
    return _safe_write_settings(settings)


def is_hook_installed() -> bool:
    """Check if the cltop hook exists in settings."""
    if not SETTINGS_PATH.exists():
        return False

    try:
        with SETTINGS_PATH.open() as f:
            settings = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False

    hook_entry = {
        "matcher": "",
        "command": str(HOOK_SCRIPT_PATH)
    }

    return (
        "hooks" in settings
        and "PostToolUse" in settings["hooks"]
        and hook_entry in settings["hooks"]["PostToolUse"]
    )


_NON_STATUS_FILES = {"config.json"}


def cleanup_stale_status_files(active_pids: set[int]) -> int:
    """Remove status files for sessions that are no longer running.

    Args:
        active_pids: Set of PIDs for currently running Claude processes

    Returns:
        Number of status files removed
    """
    if not FLEET_DIR.exists():
        return 0

    removed = 0
    _MAX_STATUS_FILES = 200
    for i, status_file in enumerate(FLEET_DIR.glob("*.json")):
        if i >= _MAX_STATUS_FILES:
            break
        # Skip non-status files (config.json, lock files, etc.)
        if status_file.name in _NON_STATUS_FILES:
            continue

        try:
            with status_file.open() as f:
                status = json.load(f)
        except (json.JSONDecodeError, OSError):
            # Corrupt status file — remove it
            try:
                status_file.unlink()
                removed += 1
            except OSError:
                pass
            continue

        # Check if the PID is still active
        pid = status.get("pid")
        if isinstance(pid, int) and pid not in active_pids:
            try:
                status_file.unlink()
                removed += 1
            except OSError:
                pass

    return removed
