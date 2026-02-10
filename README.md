# cltop

**htop for Claude**

Monitor all your Claude Code, Claude.app, and Cowork sessions in a single terminal dashboard.

```
┌─────────────────────────────────────────────────────────────────┐
│  cltop — 4 sessions · API: $8.42/$50.00 mo · Max: 3 active     │
├───┬──────────┬────────────────────┬────────┬─────────┬──────────┤
│ ● │ PID      │ Project            │ Status │ Tokens  │ Last Act │
├───┼──────────┼────────────────────┼────────┼─────────┼──────────┤
│ 🟢│ 96128    │ promptspeak/mcp    │ active │ 48.2K   │ 3s       │
│ 🟡│ 68625    │ daily-heat         │ think  │ 12.1K   │ 8s       │
│ 🔵│ cowork-1 │ promptspeak/mcp    │ active │ 6.3K    │ 1s       │
│ ⚪│ app      │ Claude.app         │ idle   │ —       │ 4m       │
├───┴──────────┴────────────────────┴────────┴─────────┴──────────┤
│ ▶ 96128 · promptspeak/mcp-server [main]                        │
│                                                                 │
│  Context  ████████████░░░░░░░░  48K/100K             48%       │
│  Progress ██████████░░░░░░░░░░  3/6 tasks      50%▸est 80%    │
│  Rate     ██████░░░░░░░░░░░░░░  ~340 req/hr    moderate       │
│                                                                 │
│  11:17:32  Read   src/governance/validator.ts                   │
│  11:17:35  Grep   "validatePolicy" across src/                  │
│  11:17:38  Edit   validator.ts:42-58                            │
│  11:17:41  Bash   npm test                                      │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
pip install cltop
cltop
```

Zero config. Works immediately if Claude is running.

## How It Works

Two-layer architecture:

**Layer 1 (Passive)** — Discovers Claude processes via `ps`, reads session transcripts from `~/.claude/projects/`. No setup needed. Gets you: session list, status, rough token estimates, recent tool calls.

**Layer 2 (Hooks)** — Optional. Run `cltop install-hook` to add a Claude Code PostToolUse hook that writes rich status data. Gets you: exact task descriptions, current file, precise token counts, task progress.

## What It Monitors

- Claude Code CLI sessions
- Claude.app desktop sessions
- Cowork/background agents
- Distinguishes Max plan (rate tracking) from API (cost tracking)

## Keybindings

| Key | Action |
|-----|--------|
| `↑↓` | Navigate sessions |
| `k` | Kill selected session |
| `h` | Show hook status |
| `s` | Sort by activity/tokens/cost |
| `q` | Quit |

## Metrics

The tri-bar shows three critical dimensions:

- **Context**: Tokens used vs context window size
- **Progress**: Tasks completed vs total (when available from hooks or TodoList)
- **Rate/Cost**: Requests per hour (Max plan) or dollars spent vs budget (API)

## Status: Alpha

This is v0.1.0. It works but it's rough around the edges.

**What works:**
- Process discovery
- JSONL parsing from Claude session transcripts
- TUI display with real-time updates
- Hook system for rich session metadata

**Known limitations:**
- Token estimates are rough without hooks installed
- Claude.app session detail is limited (desktop app is more opaque)
- No Windows support yet (relies on `ps` and Unix process model)
- Polls filesystem instead of real-time watching (watchfiles integration coming)

**What's next:**
- Real-time filesystem watching (currently polls every 2s)
- Multi-machine fleet support (monitor remote Claude sessions)
- Improved token estimation heuristics
- Plugin support for custom metrics

## Tech Stack

Python, Textual, psutil, watchfiles. Three runtime dependencies.

## Install from Source

```bash
git clone https://github.com/yourusername/cltop.git
cd cltop
pip install -e ".[dev]"
```

## Contributing

Issues and PRs welcome. This project follows conventional commits.

## License

MIT
