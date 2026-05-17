#!/bin/bash
# Launch all configured agents
cd "$(dirname "$0")"

trap "kill 0; exit" INT TERM

./run-agent.sh KiroSonnet claude-sonnet-4.6 10 &
./run-agent.sh KiroOpus claude-opus-4.6 10 &

echo "[Runner] All agents started. Ctrl+C to stop."
wait
