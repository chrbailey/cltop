"""Layer 1 passive discovery - find running Claude sessions and parse their state."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

import psutil

from .models import FleetState, Session, SessionMetrics, SessionSource, SessionStatus, ToolCall
from .pricing import BYTES_PER_TOKEN, PlanType, detect_plan_type, estimate_tokens_from_bytes


async def discover_sessions() -> list[Session]:
    """Discover all running Claude sessions and their current state."""
    sessions: list[Session] = []

    # Find all candidate processes
    processes = await _find_claude_processes()

    # Map each process to session data
    for proc_info in processes:
        try:
            session = await _build_session_from_process(proc_info)
            if session:
                sessions.append(session)
        except Exception as e:
            # Don't crash the whole scan if one session fails
            print(f"Warning: Failed to discover session for PID {proc_info['pid']}: {e}")
            continue

    return sessions


async def build_fleet_state() -> FleetState:
    """Build complete fleet state from discovered sessions."""
    sessions = await discover_sessions()

    # Calculate month-to-date API spend
    api_spent = sum(
        s.metrics.cost_dollars
        for s in sessions
        if s.metrics.plan_type == PlanType.API
    )

    return FleetState(
        sessions=sessions,
        api_spent_monthly=api_spent,
    )


async def _find_claude_processes() -> list[dict]:
    """Find running Claude session processes (not helpers or MCP servers).

    Returns list of dicts with: pid, cmdline, name, create_time, cwd
    """
    processes = []

    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time', 'cwd']):
        try:
            info = proc.info
            name = info.get('name', '')
            cmdline = info.get('cmdline') or []
            cmdline_str = ' '.join(cmdline)

            # Skip helper processes immediately
            if 'helper' in name.lower() or 'crashpad' in name.lower() or 'shipit' in name.lower():
                continue

            # Skip MCP server processes (node running Claude Extensions)
            if name.lower() == 'node' and 'Claude Extensions' in cmdline_str:
                continue

            # Skip disclaimer wrapper processes
            if 'disclaimer' in name.lower() or (cmdline and 'disclaimer' in cmdline[0]):
                continue

            # Claude Code CLI: exact binary name "claude"
            if name == 'claude':
                processes.append(info)
                continue

            # Claude.app: main process only (exact MacOS binary, no Helper)
            if name == 'Claude':
                try:
                    exe = proc.exe()
                    if exe == '/Applications/Claude.app/Contents/MacOS/Claude':
                        processes.append(info)
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass
                continue

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    return processes


async def _build_session_from_process(proc_info: dict) -> Session | None:
    """Map a discovered process to a Session object."""
    pid = proc_info['pid']
    name = proc_info.get('name', '')
    cmdline = proc_info.get('cmdline') or []
    create_time = proc_info.get('create_time')
    cwd = proc_info.get('cwd', '')

    # Determine source
    source = _detect_source(name, cmdline)

    # Try to find corresponding session JSONL
    jsonl_path = await _find_session_jsonl(pid, cwd, cmdline)

    if jsonl_path is None:
        # No session file found - maybe Claude.app or just-started process
        # Return basic session info
        return Session(
            id=str(pid),
            pid=pid,
            source=source,
            status=SessionStatus.UNKNOWN,
            project_dir=cwd,
            started_at=datetime.fromtimestamp(create_time, tz=timezone.utc) if create_time else None,
            metrics=SessionMetrics(plan_type=detect_plan_type(pid, source.value)),
        )

    # Parse session state from JSONL
    session_data = await _parse_session_jsonl(jsonl_path)

    # Extract project directory from JSONL path or cwd
    project_dir = _extract_project_dir(jsonl_path, cwd)

    # Detect git branch
    branch = await _detect_git_branch(project_dir)

    # Build metrics
    metrics = SessionMetrics(
        tokens_used=session_data['tokens_used'],
        tasks_completed=session_data['tasks_completed'],
        tasks_total=session_data['tasks_total'],
        plan_type=detect_plan_type(pid, source.value),
        requests_per_hour=session_data['requests_per_hour'],
    )

    return Session(
        id=str(pid),
        pid=pid,
        source=source,
        status=session_data['status'],
        project_dir=project_dir,
        branch=branch,
        current_task=session_data['current_task'],
        current_file=session_data['current_file'],
        started_at=datetime.fromtimestamp(create_time, tz=timezone.utc) if create_time else None,
        last_activity=session_data['last_activity'],
        metrics=metrics,
        recent_tools=session_data['recent_tools'],
        jsonl_path=jsonl_path,
    )


def _detect_source(name: str, cmdline: list[str]) -> SessionSource:
    """Determine session source from process info."""
    cmdline_str = ' '.join(cmdline)

    # Check for Claude.app main process
    if name == 'Claude' and '/Applications/Claude.app/Contents/MacOS/Claude' in cmdline_str:
        return SessionSource.CLAUDE_APP

    # Check for Claude Code CLI
    if name == 'claude':
        # Check if it's a cowork session by looking for --resume flag with session ID pattern
        if '--resume' in cmdline:
            # Check if there's a session ID pattern after --resume
            try:
                resume_idx = cmdline.index('--resume')
                if resume_idx + 1 < len(cmdline):
                    next_arg = cmdline[resume_idx + 1]
                    # Session IDs are typically short alphanumeric strings
                    if len(next_arg) > 5 and len(next_arg) < 20:
                        return SessionSource.COWORK
            except ValueError:
                pass
        
        return SessionSource.CLAUDE_CODE

    return SessionSource.API


def _extract_session_id_from_cmdline(cmdline: list[str]) -> str | None:
    """Extract session ID from --resume flag in cmdline.

    Session IDs are UUIDs like: fe580b5f-c6e2-4017-a29b-34008b9ad491
    """
    for i, arg in enumerate(cmdline):
        if arg == '--resume' and i + 1 < len(cmdline):
            candidate = cmdline[i + 1]
            # Session IDs are UUIDs (36 chars, 4 hyphens)
            if len(candidate) == 36 and candidate.count('-') == 4:
                return candidate
    return None


async def _find_session_jsonl(pid: int, cwd: str, cmdline: list[str] | None = None) -> Path | None:
    """Find the session JSONL file corresponding to this process.

    Claude Code sessions store transcripts at:
    ~/.claude/projects/{project-hash}/{session-id}.jsonl

    Strategy:
    1. First check cmdline for --resume <session-id> and directly match filename
    2. Check CLAUDE_SESSION_ID env var (via process environment)
    3. Fall back to time-based heuristic (most recently modified .jsonl)
    """
    claude_dir = Path.home() / '.claude' / 'projects'
    if not claude_dir.exists():
        return None

    try:
        proc = psutil.Process(pid)
        proc_start_time = datetime.fromtimestamp(proc.create_time(), tz=timezone.utc)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None

    # Try to extract session ID from cmdline
    session_id = None
    if cmdline:
        session_id = _extract_session_id_from_cmdline(cmdline)

    # If we have a session ID, search for matching file
    if session_id:
        for jsonl in claude_dir.rglob(f'{session_id}.jsonl'):
            try:
                # Verify the file was modified after process started
                mtime = jsonl.stat().st_mtime
                if datetime.fromtimestamp(mtime, tz=timezone.utc) >= proc_start_time:
                    return jsonl
            except OSError:
                continue

    # Fall back to time-based heuristic
    # Find all .jsonl files modified after process started
    jsonl_files: list[tuple[Path, float]] = []
    for jsonl in claude_dir.rglob('*.jsonl'):
        try:
            mtime = jsonl.stat().st_mtime
            # Only consider files modified after process started
            if datetime.fromtimestamp(mtime, tz=timezone.utc) >= proc_start_time:
                jsonl_files.append((jsonl, mtime))
        except OSError:
            continue

    if not jsonl_files:
        return None

    # Return most recently modified
    jsonl_files.sort(key=lambda x: x[1], reverse=True)
    return jsonl_files[0][0]


async def _parse_session_jsonl(jsonl_path: Path) -> dict:
    """Parse the last ~50 lines of a session JSONL file.

    Returns dict with:
    - status: SessionStatus
    - current_task: str
    - current_file: str
    - tokens_used: int
    - tasks_completed: int
    - tasks_total: int
    - last_activity: datetime
    - recent_tools: list[ToolCall]
    - requests_per_hour: float
    """
    # Read last N bytes for efficiency (don't load entire file)
    tail_bytes = 50_000  # ~50KB should give us plenty of recent entries

    try:
        file_size = jsonl_path.stat().st_size
        with open(jsonl_path, 'rb') as f:
            # Seek to end - tail_bytes
            seek_pos = max(0, file_size - tail_bytes)
            f.seek(seek_pos)

            # Read to end
            tail_data = f.read().decode('utf-8', errors='ignore')
    except OSError:
        return _empty_session_data()

    # Split into lines and parse JSON
    lines = tail_data.strip().split('\n')

    # Skip first line if we seeked (might be partial)
    if file_size > tail_bytes:
        lines = lines[1:]

    entries: list[dict] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not entries:
        return _empty_session_data()

    # Extract data from entries
    status = _determine_status(entries)
    current_task = _extract_current_task(entries)
    current_file = _extract_current_file(entries)
    last_activity = _extract_last_activity(entries)
    recent_tools = _extract_recent_tools(entries)
    tasks_completed, tasks_total = _extract_task_counts(entries)
    requests_per_hour = _estimate_request_rate(entries)

    # Estimate tokens from file size
    tokens_used = estimate_tokens_from_bytes(file_size)

    return {
        'status': status,
        'current_task': current_task,
        'current_file': current_file,
        'tokens_used': tokens_used,
        'tasks_completed': tasks_completed,
        'tasks_total': tasks_total,
        'last_activity': last_activity,
        'recent_tools': recent_tools,
        'requests_per_hour': requests_per_hour,
    }


def _empty_session_data() -> dict:
    """Return empty session data structure."""
    return {
        'status': SessionStatus.UNKNOWN,
        'current_task': '',
        'current_file': '',
        'tokens_used': 0,
        'tasks_completed': 0,
        'tasks_total': 0,
        'last_activity': None,
        'recent_tools': [],
        'requests_per_hour': 0.0,
    }


def _determine_status(entries: list[dict]) -> SessionStatus:
    """Determine session status from recent JSONL entries.

    Status logic:
    - ACTIVE: tool call result < 10s ago
    - THINKING: assistant message in progress (no result yet)
    - IDLE: > 30s since last activity
    - BLOCKED: last message was system asking for user input
    """
    if not entries:
        return SessionStatus.UNKNOWN

    now = datetime.now(timezone.utc)
    last_entry = entries[-1]

    # Check if blocked (waiting for user input)
    if last_entry.get('type') == 'system':
        message = last_entry.get('message', {})
        content = message.get('content', '')
        if isinstance(content, str) and 'input' in content.lower():
            return SessionStatus.BLOCKED

    # Find most recent tool call result
    last_tool_result_time = None
    for entry in reversed(entries[-20:]):  # Check last 20 entries
        if entry.get('type') == 'user':
            message = entry.get('message', {})
            content = message.get('content', [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'tool_result':
                        timestamp = entry.get('timestamp')
                        if timestamp:
                            try:
                                last_tool_result_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                                break
                            except (ValueError, AttributeError):
                                pass
            if last_tool_result_time:
                break

    if last_tool_result_time:
        seconds_since = (now - last_tool_result_time).total_seconds()
        if seconds_since < 10:
            return SessionStatus.ACTIVE
        elif seconds_since > 30:
            return SessionStatus.IDLE
        else:
            return SessionStatus.THINKING

    # Check for recent assistant message
    for entry in reversed(entries[-10:]):
        if entry.get('type') == 'assistant':
            timestamp = entry.get('timestamp')
            if timestamp:
                try:
                    msg_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    seconds_since = (now - msg_time).total_seconds()
                    if seconds_since < 30:
                        return SessionStatus.THINKING
                except (ValueError, AttributeError):
                    pass

    return SessionStatus.IDLE


def _extract_current_task(entries: list[dict]) -> str:
    """Extract current task description from recent task updates."""
    for entry in reversed(entries[-30:]):
        # Look for task list updates or assistant messages describing current work
        if entry.get('type') == 'assistant':
            message = entry.get('message', {})
            content = message.get('content', [])

            if isinstance(content, list):
                # Check for tool_use blocks with TaskCreate/TaskUpdate
                for block in content:
                    if isinstance(block, dict):
                        if block.get('type') == 'tool_use':
                            tool_name = block.get('name', '')
                            if tool_name in ('TaskCreate', 'TaskUpdate'):
                                params = block.get('input', {})
                                subject = params.get('subject', '')
                                if subject:
                                    return subject

                        # Also check text blocks for first sentence
                        elif block.get('type') == 'text':
                            text = block.get('text', '')
                            if text:
                                first_sentence = text.split('.')[0].strip()
                                if first_sentence and len(first_sentence) < 100:
                                    return first_sentence

    return ''


def _extract_current_file(entries: list[dict]) -> str:
    """Extract most recently accessed file from tool calls."""
    for entry in reversed(entries[-20:]):
        if entry.get('type') == 'assistant':
            message = entry.get('message', {})
            content = message.get('content', [])

            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'tool_use':
                        tool_name = block.get('name', '')
                        params = block.get('input', {})

                        # File operations
                        if tool_name in ('Read', 'Edit', 'Write'):
                            file_path = params.get('file_path', '')
                            if file_path:
                                return Path(file_path).name

                        # Grep/Glob results
                        if tool_name in ('Grep', 'Glob'):
                            path = params.get('path', '')
                            if path:
                                return Path(path).name

    return ''


def _extract_last_activity(entries: list[dict]) -> datetime | None:
    """Extract timestamp of most recent activity."""
    if not entries:
        return None

    # Check last few entries for timestamp
    for entry in reversed(entries[-5:]):
        timestamp = entry.get('timestamp')
        if timestamp:
            try:
                return datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                continue

    return None


def _extract_recent_tools(entries: list[dict]) -> list[ToolCall]:
    """Extract recent tool calls from JSONL entries."""
    tool_calls: list[ToolCall] = []

    for entry in reversed(entries[-30:]):
        if entry.get('type') == 'assistant':
            message = entry.get('message', {})
            content = message.get('content', [])
            timestamp = entry.get('timestamp')

            if not timestamp:
                continue

            try:
                ts = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                continue

            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'tool_use':
                        tool_name = block.get('name', '')
                        params = block.get('input', {})

                        if not tool_name:
                            continue

                        # Build summary
                        summary = _build_tool_summary(tool_name, params)

                        tool_calls.append(ToolCall(
                            timestamp=ts,
                            tool_name=tool_name,
                            summary=summary,
                        ))

    # Return in chronological order (oldest first)
    return list(reversed(tool_calls))


def _build_tool_summary(tool_name: str, params: dict) -> str:
    """Build a short summary string for a tool call."""
    # File operations
    if tool_name == 'Read':
        file_path = params.get('file_path', '')
        return f"Read {Path(file_path).name}" if file_path else 'Read'

    if tool_name == 'Edit':
        file_path = params.get('file_path', '')
        return f"Edit {Path(file_path).name}" if file_path else 'Edit'

    if tool_name == 'Write':
        file_path = params.get('file_path', '')
        return f"Write {Path(file_path).name}" if file_path else 'Write'

    # Bash
    if tool_name == 'Bash':
        command = params.get('command', '')
        # Truncate long commands
        cmd_short = command.split()[0] if command else 'bash'
        return f"Bash: {cmd_short}"

    # Search
    if tool_name == 'Grep':
        pattern = params.get('pattern', '')
        return f"Grep: {pattern[:30]}" if pattern else 'Grep'

    if tool_name == 'Glob':
        pattern = params.get('pattern', '')
        return f"Glob: {pattern[:30]}" if pattern else 'Glob'

    # Tasks
    if tool_name in ('TaskCreate', 'TaskUpdate', 'TaskList'):
        return tool_name

    # Default
    return tool_name


def _extract_task_counts(entries: list[dict]) -> tuple[int, int]:
    """Extract task counts from TaskList or TaskUpdate calls.

    Returns (completed, total).
    """
    completed = 0
    total = 0

    # Look for most recent TaskList result
    for entry in reversed(entries[-50:]):
        # Check if this is a tool result (in user message)
        if entry.get('type') == 'user':
            message = entry.get('message', {})
            content = message.get('content', [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'tool_result':
                        result_content = block.get('content', '')
                        if isinstance(result_content, str):
                            # Try to parse task list from text
                            if 'completed' in result_content.lower() and 'pending' in result_content.lower():
                                # Simple regex-free parsing
                                lines = result_content.split('\n')
                                for line in lines:
                                    if 'status:' in line.lower():
                                        if 'completed' in line.lower():
                                            completed += 1
                                        total += 1

        # Also check tool_use for TaskUpdate with status=completed
        if entry.get('type') == 'assistant':
            message = entry.get('message', {})
            content = message.get('content', [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'tool_use':
                        if block.get('name') == 'TaskUpdate':
                            params = block.get('input', {})
                            if params.get('status') == 'completed':
                                completed += 1

    return completed, total


def _estimate_request_rate(entries: list[dict]) -> float:
    """Estimate requests per hour from recent activity.

    Strategy: Count API request/response pairs in recent entries,
    calculate time span, extrapolate to hourly rate.
    """
    if not entries:
        return 0.0

    # Find all assistant messages (= API requests)
    request_times: list[datetime] = []

    for entry in entries[-50:]:
        if entry.get('type') == 'assistant':
            timestamp = entry.get('timestamp')
            if timestamp:
                try:
                    ts = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    request_times.append(ts)
                except (ValueError, AttributeError):
                    continue

    if len(request_times) < 2:
        return 0.0

    # Calculate time span
    time_span = (request_times[-1] - request_times[0]).total_seconds()
    if time_span < 60:  # Less than 1 minute - not enough data
        return 0.0

    # Requests per second -> requests per hour
    requests_per_second = len(request_times) / time_span
    return requests_per_second * 3600


def _extract_project_dir(jsonl_path: Path, cwd: str) -> str:
    """Extract project directory from JSONL path structure.

    JSONL path format: ~/.claude/projects/{project-hash}/{session-id}.jsonl
    Project hash corresponds to a project working directory.

    For now, fall back to cwd if we can't decode the hash.
    """
    if cwd:
        return cwd

    # Could implement project-hash -> directory mapping here
    # by reading ~/.claude/projects/*/metadata or similar

    return str(jsonl_path.parent)


async def _detect_git_branch(project_dir: str) -> str:
    """Detect current git branch for a project directory."""
    if not project_dir:
        return ''

    try:
        result = await asyncio.create_subprocess_exec(
            'git', '-C', project_dir, 'branch', '--show-current',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await result.communicate()

        if result.returncode == 0:
            return stdout.decode().strip()
    except Exception:
        pass

    return ''
