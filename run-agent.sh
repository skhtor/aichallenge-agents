#!/bin/bash
# Run a single agent instance
# Usage: ./run-agent.sh <bot_name> <model> [cycle_minutes]

set -e
cd "$(dirname "$0")"

BOT_NAME="${1:?Usage: $0 <bot_name> <model> [cycle_minutes]}"
MODEL="${2:?Usage: $0 <bot_name> <model> [cycle_minutes]}"
CYCLE="${3:-10}"

WORKSPACE="$(pwd)/workspace_$(echo "$BOT_NAME" | tr '[:upper:]' '[:lower:]')"
mkdir -p "$WORKSPACE"

export AGENT_SERVER_URL="${AGENT_SERVER_URL:-http://localhost:5000}"
export AGENT_TEAM_TOKEN="${AGENT_TEAM_TOKEN:?Set AGENT_TEAM_TOKEN env var}"
export AGENT_BOT_NAME="$BOT_NAME"
export AGENT_MODEL="$MODEL"
export AGENT_LANGUAGE="python"
export AGENT_CYCLE_MINUTES="$CYCLE"
export AGENT_MATCHES_PER_CYCLE="${AGENT_MATCHES_PER_CYCLE:-10}"
export AGENT_WORKSPACE="$WORKSPACE"

echo "[Agent] $BOT_NAME | model=$MODEL | cycle=${CYCLE}m | workspace=$WORKSPACE"
exec python3 -u agent.py >> "$WORKSPACE/agent.log" 2>&1
