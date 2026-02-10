# cltop

**Terminal dashboard that monitors all running Claude Code, Claude.app, and Cowork sessions from a single pane.**

Running multiple Claude sessions with no visibility into what each one is doing, how much context it has consumed, or what it costs? cltop discovers Claude processes automatically and displays live status, token usage, task progress, and tool call history in a Textual TUI.


## When to use cltop

- You have 2+ Claude Code sessions running and need to see which ones are active, idle, or blocked waiting for input.
- You want to track API spend across sessions against a monthly budget.
- You need to kill a runaway Claude session without hunting through terminal tabs.
- You want to watch tool call history (Read, Edit, Bash, Grep) in real time to understand what a session is doing.


## Install

```bash
pip install cltop
cltop
```

Zero configuration. If any Claude process is running, cltop finds it.

For richer session data (exact task descriptions, file context, precise token counts):

```bash
cltop install-hook
```

This registers a PostToolUse hook in `~/.claude/settings.json`. Restart running Claude Code sessions for the hook to take effect.


## What you see

The TUI has three regions:

**Fleet table** (top) -- One row per discovered session showing PID, project name, status indicator (active / thinking / idle / blocked / background), token count, and time since last activity.

**Metrics bar** (middle) -- Three progress bars for the selected session: context window usage (tokens used vs max), task progress (completed vs total), and rate or cost (requests/hr for Max plan, dollars vs budget for API plan).

**Detail panel** (bottom) -- Project path, git branch, current task description, and a scrolling log of recent tool calls with timestamps.

An SVG recording of the TUI exists in the repository (`demo.svg`).


## Two-layer architecture

**Layer 1: Passive discovery (no setup)**
Finds Claude processes via `ps` / psutil, then reads session transcripts from `~/.claude/projects/` to extract status, token estimates, tool call history, and task progress. Works immediately.

**Layer 2: Hook enrichment (optional)**
A PostToolUse hook (`cltop install-hook`) writes structured JSON status files to `~/.claude/fleet/` on every tool call. This adds: exact task descriptions, current file being edited, precise token counts, and TodoList-derived progress tracking. The hook is a bash script that requires `jq`.


## CLI reference

| Command | What it does |
|---------|-------------|
| `cltop` | Launch the dashboard |
| `cltop install-hook` | Deploy the PostToolUse hook for richer session data |
| `cltop uninstall-hook` | Remove the hook from `~/.claude/settings.json` |
| `cltop budget api <amount>` | Set monthly API spend budget in dollars (persisted to `~/.claude/fleet/config.json`) |
| `cltop --version` | Print version |
| `cltop --help` | Print usage summary |


## Keybindings

| Key | Action |
|-----|--------|
| Up / Down | Navigate sessions in fleet table |
| `k` | Kill selected session (modal confirmation, sends SIGTERM) |
| `h` | Toggle hook install/uninstall |
| `s` | Cycle sort order: activity, tokens, project |
| `r` | Force immediate refresh |
| `q` | Quit |


## Data model

Each discovered session tracks:

| Field | Source | Description |
|-------|--------|-------------|
| `id` | Layer 1 | Process PID or session hash |
| `pid` | Layer 1 | OS process ID |
| `source` | Layer 1 | `claude_code`, `claude_app`, `cowork`, or `api` |
| `status` | Layer 1 | `active` (<10s), `thinking`, `idle` (>30s), `blocked`, `background`, `unknown` |
| `project_dir` | Layer 1 | Working directory |
| `branch` | Layer 1 | Git branch (detected via `git -C`) |
| `tokens_used` | Layer 1 (estimated from JSONL size) or Layer 2 (precise) | Token count |
| `tokens_max` | Default | Context window size (default 200K) |
| `current_task` | Layer 1 (from assistant messages) or Layer 2 (from hook) | What the session is working on |
| `current_file` | Layer 1 or Layer 2 | File being read/edited |
| `requests_per_hour` | Layer 1 | Estimated from assistant message timestamps |
| `cost_dollars` | Layer 1 | Estimated API cost (Sonnet default pricing) |
| `tasks_completed` / `tasks_total` | Layer 1 (TaskUpdate parsing) or Layer 2 | Progress from TodoList |
| `recent_tools` | Layer 1 | Last ~30 tool calls with timestamps and summaries |
| `has_hook` | Layer 2 | Whether enriched hook data is available |

Plan detection: Claude Code CLI, Claude.app, and Cowork sessions default to Max plan (rate-tracked). Unknown sources default to API plan (cost-tracked).


## Requirements

- Python 3.11+
- macOS or Linux (relies on `ps` and Unix process model)
- Runtime dependencies: `textual` (>=0.50), `psutil` (>=5.9), `watchfiles` (>=0.20)
- Optional: `jq` (required by the Layer 2 hook script)


## Status: alpha (v0.1.0)

**Works now:**
- Automatic discovery of Claude Code CLI, Claude.app, and Cowork sessions
- JSONL transcript parsing for status, tokens, tool history, and task progress
- TUI with real-time updates (3-second poll interval)
- PostToolUse hook system for enriched metadata
- Session kill with TOCTOU-safe PID verification
- Atomic config writes with file locking

**Known limitations:**
- Token estimates are rough without the hook installed (heuristic: ~3.5 bytes per token from JSONL file size)
- Claude.app sessions are more opaque than CLI sessions (less transcript data available)
- No Windows support
- Filesystem polling at 3s intervals (watchfiles integration planned but not yet wired up)
- JSONL discovery caps at 50 candidates to prevent slow directory walks


## Security

- The kill command re-verifies that the target PID still belongs to a Claude process before sending SIGTERM (TOCTOU guard).
- Hook status files are written with `umask 077` (owner-only).
- Settings.json writes use `flock` + atomic temp-file rename to prevent corruption from concurrent access.
- Config writes (budget) use atomic temp-file rename.
- No network calls. All data is local filesystem and process table.


## License

MIT
