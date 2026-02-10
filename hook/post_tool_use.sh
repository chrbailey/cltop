#!/bin/bash
# PostToolUse hook for cltop — writes rich status data to ~/.claude/fleet/
#
# Called by Claude Code after every tool invocation. Receives tool call JSON on stdin.
# Writes/updates status file at ~/.claude/fleet/{session_id}.json
#
# Installation: cltop install-hook
# Requirements: jq

set -euo pipefail

umask 077  # Status files contain work context — owner-only

# Verify jq is available — exit silently if missing
command -v jq >/dev/null 2>&1 || exit 0

FLEET_DIR="$HOME/.claude/fleet"
mkdir -p "$FLEET_DIR"

# Read tool call JSON from stdin
TOOL_DATA=$(cat)

# Extract session ID (prefer env var, fallback to parent PID which is Claude Code)
SESSION_ID="${CLAUDE_SESSION_ID:-$PPID}"

# Extract fields with jq (with defaults for missing fields)
TOOL_NAME=$(echo "$TOOL_DATA" | jq -r '.tool // "unknown"')
CURRENT_TASK=$(echo "$TOOL_DATA" | jq -r '.context.current_task // ""')
CURRENT_FILE=$(echo "$TOOL_DATA" | jq -r '.context.current_file // ""')
PROJECT_DIR=$(echo "$TOOL_DATA" | jq -r '.context.project_dir // ""')
TOKENS=$(echo "$TOOL_DATA" | jq -r '.context.tokens_estimate // 0')
TASKS_COMPLETED=$(echo "$TOOL_DATA" | jq -r '.context.tasks_completed // 0')
TASKS_TOTAL=$(echo "$TOOL_DATA" | jq -r '.context.tasks_total // 0')

# Build tool args summary (extract basename via jq to avoid shell quoting issues)
TOOL_ARGS_SUMMARY=""
if [ "$TOOL_NAME" = "Edit" ] || [ "$TOOL_NAME" = "Read" ] || [ "$TOOL_NAME" = "Write" ]; then
    TOOL_ARGS_SUMMARY=$(echo "$TOOL_DATA" | jq -r '.args.file_path // "" | split("/") | last')
fi

# Write status file atomically (temp + mv prevents partial reads)
STATUS_FILE="$FLEET_DIR/$SESSION_ID.json"
TEMP_FILE=$(mktemp "$FLEET_DIR/.tmp.XXXXXX")
jq -n \
  --arg session_id "$SESSION_ID" \
  --argjson pid "$PPID" \
  --arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg project_dir "$PROJECT_DIR" \
  --arg current_task "$CURRENT_TASK" \
  --arg current_file "$CURRENT_FILE" \
  --arg tool_name "$TOOL_NAME" \
  --arg tool_args_summary "$TOOL_ARGS_SUMMARY" \
  --argjson tokens_estimate "${TOKENS:-0}" \
  --argjson tasks_completed "${TASKS_COMPLETED:-0}" \
  --argjson tasks_total "${TASKS_TOTAL:-0}" \
  '{
    session_id: $session_id,
    pid: $pid,
    timestamp: $timestamp,
    project_dir: $project_dir,
    current_task: $current_task,
    current_file: $current_file,
    tool_name: $tool_name,
    tool_args_summary: $tool_args_summary,
    tokens_estimate: $tokens_estimate,
    tasks_completed: $tasks_completed,
    tasks_total: $tasks_total
  }' > "$TEMP_FILE" && mv "$TEMP_FILE" "$STATUS_FILE"
