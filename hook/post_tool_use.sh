#!/bin/bash
# PostToolUse hook for cltop — writes rich status data to ~/.claude/fleet/
#
# Called by Claude Code after every tool invocation. Receives tool call JSON on stdin.
# Writes/updates status file at ~/.claude/fleet/{session_id}.json
#
# Installation: cltop install-hook
# Requirements: jq

set -euo pipefail

FLEET_DIR="$HOME/.claude/fleet"
mkdir -p "$FLEET_DIR"

# Read tool call JSON from stdin
TOOL_DATA=$(cat)

# Extract session ID (prefer env var, fallback to PID)
SESSION_ID="${CLAUDE_SESSION_ID:-$$}"

# Extract fields with jq (with defaults for missing fields)
TOOL_NAME=$(echo "$TOOL_DATA" | jq -r '.tool // "unknown"')
CURRENT_TASK=$(echo "$TOOL_DATA" | jq -r '.context.current_task // ""')
CURRENT_FILE=$(echo "$TOOL_DATA" | jq -r '.context.current_file // ""')
PROJECT_DIR=$(echo "$TOOL_DATA" | jq -r '.context.project_dir // ""')
TOKENS=$(echo "$TOOL_DATA" | jq -r '.context.tokens_estimate // 0')
TASKS_COMPLETED=$(echo "$TOOL_DATA" | jq -r '.context.tasks_completed // 0')
TASKS_TOTAL=$(echo "$TOOL_DATA" | jq -r '.context.tasks_total // 0')

# Build tool args summary
TOOL_ARGS_SUMMARY=""
if [ "$TOOL_NAME" = "Edit" ] || [ "$TOOL_NAME" = "Read" ] || [ "$TOOL_NAME" = "Write" ]; then
    TOOL_ARGS_SUMMARY=$(echo "$TOOL_DATA" | jq -r '.args.file_path // ""' | xargs basename 2>/dev/null || true)
fi

# Write status file using jq for proper JSON escaping
STATUS_FILE="$FLEET_DIR/$SESSION_ID.json"
jq -n \
  --arg session_id "$SESSION_ID" \
  --argjson pid "$$" \
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
  }' > "$STATUS_FILE"
