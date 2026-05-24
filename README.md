# AI Challenge Agents

An autonomous AI agent system that competes in the [Google AI Ants Challenge](http://ants.aichallenge.org/) by using Kiro CLI to iteratively develop, test, and deploy bot strategies.

## Overview

This project implements a self-improving loop: an orchestrator agent observes game results from a central server, invokes Kiro CLI to analyse performance and write improved bot code, runs local tournaments to validate changes, and uploads winning bots — all without human intervention.

## Architecture

```
┌─────────────┐       ┌──────────────┐       ┌─────────────┐
│  Game Server │◄─────►│   agent.py   │──────►│  Kiro CLI   │
│  (matches +  │       │ (orchestrator)│       │ (code gen)  │
│  leaderboard)│       └──────────────┘       └─────────────┘
└─────────────┘              │
                             ▼
                    ┌──────────────────┐
                    │ Local Tournament │
                    │ (tournament.py)  │
                    └──────────────────┘
```

### Components

| File | Purpose |
|------|---------|
| `agent.py` | Main orchestrator — runs observe/analyse/improve cycles on a timer |
| `tournament.py` | Local round-robin tournament runner for validating bots before upload |
| `behaviour_analyser.py` | Extracts turn-by-turn narrative reports from game replays |
| `engine/ants.py` | Official game client library (DO NOT MODIFY) |
| `prompts/mechanics.md` | Game rules and API reference injected into Kiro's context |
| `prompts/improve.md` | Strategy/implementation instructions for Kiro |
| `sample-bot/myBot.py` | Minimal starter bot template |
| `run.sh` | Launches all configured agents in parallel |
| `run-agent.sh` | Launches a single agent instance with configurable model/name |

## How It Works

### The Improvement Cycle

Each agent runs a continuous loop:

1. **Observe** — Fetch leaderboard, ELO history, head-to-head stats, and replay data from the game server.
2. **Analyse** — Parse replays to extract spatial metrics (exploration %, army spread, oscillation), combat stats, and food efficiency. Generate behaviour reports comparing the bot to winners.
3. **Improve** — Invoke Kiro CLI with full context. Kiro creates/modifies bot strategies (named after historical war generals), implements variants, and runs local tournaments.
4. **Deploy** — Upload the best-performing bots to the game server.
5. **Evaluate** — Monitor ELO after deployment. Auto-rollback if ELO drops below a threshold.

### Strategy System

Bots are organised into named strategies inspired by historical generals (e.g., Hannibal for flanking maneuvers, Napoleon for overwhelming force). Each strategy has:
- A `strategy.md` describing the philosophy
- Multiple implementation variants (`v1/MyBot.py`, `v2/MyBot.py`, etc.)

This encourages diversity — the agent maintains 2-4 fundamentally different approaches and evolves winners while retiring losers.

## Setup

### Prerequisites

- Python 3.8+
- [Kiro CLI](https://kiro.dev) installed and configured
- Access to an AI Ants game server
- (Optional) Local copy of the [aichallenge](https://github.com/aichallenge/aichallenge) engine for local tournaments

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_SERVER_URL` | `http://localhost:5000` | Game server URL |
| `AGENT_TEAM_TOKEN` | (required) | Auth token for bot uploads |
| `AGENT_BOT_NAME` | `KiroSonnet` | Bot name on the leaderboard |
| `AGENT_MODEL` | `claude-sonnet-4.6` | LLM model for Kiro CLI |
| `AGENT_CYCLE_MINUTES` | `30` | Minutes between improvement cycles |
| `AGENT_MATCHES_PER_CYCLE` | `10` | Matches to wait for before evaluating |
| `AGENT_ROLLBACK_ELO` | `-30` | ELO drop threshold triggering rollback |
| `AGENT_LANGUAGE` | `python` | Bot language |
| `AGENT_WORKSPACE` | `./workspace` | Working directory for generated code |
| `ANTS_DIR` | `../aichallenge/ants` | Path to ants engine (for local tournaments) |

## Usage

### Run all agents

```bash
export AGENT_TEAM_TOKEN="your-token"
export AGENT_SERVER_URL="http://your-server:5000"
./run.sh
```

This starts two agents in parallel (KiroSonnet using Claude Sonnet, KiroOpus using Claude Opus).

### Run a single agent

```bash
./run-agent.sh <bot_name> <model> [cycle_minutes]

# Example:
./run-agent.sh MyBot claude-sonnet-4.6 15
```

### Run a single cycle (no loop)

```bash
export AGENT_CYCLE_MINUTES=0
python3 agent.py
```

### Run a local tournament

```python
from tournament import run_tournament
from pathlib import Path

bots = [
    {"name": "strategy_a", "dir": Path("workspace/strategies/Hannibal/v1")},
    {"name": "strategy_b", "dir": Path("workspace/strategies/Napoleon/v1")},
]
results = run_tournament(bots, num_maps=5, games_per_pair=3)
for r in results:
    print(f"{r['name']}: {r['wins']}W/{r['losses']}L avg_score={r['avg_score']}")
```

## Game Rules (Summary)

- **Map**: Toroidal grid with water (impassable), food, ants, and hills
- **Objective**: Raze enemy hills (+2 points) while protecting your own
- **Growth**: Collect food to spawn new ants at your hills
- **Combat**: Numerical advantage wins — 2v1 kills the lone ant, 1v1 both die
- **Vision**: Fog of war; each ant sees ~8.7 cells radius
- **Time limit**: 1 second per turn (timeout = elimination)

See `prompts/mechanics.md` for the full specification.

## Workspace Output

After running, the agent workspace contains:

```
workspace_kirosonnet/
├── context.json              # Latest observation data
├── strategies/
│   ├── Hannibal/
│   │   ├── strategy.md
│   │   ├── v1/MyBot.py
│   │   └── v2/MyBot.py
│   └── Napoleon/
│       ├── strategy.md
│       └── v1/MyBot.py
├── tournament_results.md
├── CHANGELOG.md
└── cycle_*.log               # Kiro output logs
```

## License

This project is for educational and competition purposes.
