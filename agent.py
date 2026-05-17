#!/usr/bin/env python3
"""Autonomous AI Ants Agent — uses Kiro CLI to improve a bot via the game server API."""
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

AGENT_DIR = Path(__file__).parent
WORKSPACE = Path(os.environ.get("AGENT_WORKSPACE", str(AGENT_DIR / "workspace")))
PROMPTS_DIR = AGENT_DIR / "prompts"

# Config (override via env vars)
SERVER_URL = os.environ.get("AGENT_SERVER_URL", "http://localhost:5000")
BOT_NAME = os.environ.get("AGENT_BOT_NAME", "KiroSonnet")
TEAM_TOKEN = os.environ.get("AGENT_TEAM_TOKEN", "")
MODEL = os.environ.get("AGENT_MODEL", "claude-sonnet-4.6")
CYCLE_INTERVAL = int(os.environ.get("AGENT_CYCLE_MINUTES", "30")) * 60
MATCHES_PER_CYCLE = int(os.environ.get("AGENT_MATCHES_PER_CYCLE", "10"))
ROLLBACK_THRESHOLD = float(os.environ.get("AGENT_ROLLBACK_ELO", "-30"))
LANGUAGE = os.environ.get("AGENT_LANGUAGE", "python")


def api_get(path, retries=3):
    """GET from game server API with retries."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(f"{SERVER_URL}{path}")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code != 404:
                print(f"[Agent] API error {e.code}: {path}")
            return None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
            else:
                print(f"[Agent] API unreachable after {retries} attempts: {path} ({e})")
                return None


def api_post(path, data=None, files=None, token=None):
    """POST to game server API (form data)."""
    import io
    boundary = "----AgentBoundary"
    body = b""
    if data:
        for k, v in data.items():
            body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    if files:
        for k, (filename, content) in files.items():
            body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode()
            body += content + b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(f"{SERVER_URL}{path}", data=body, headers=headers, method="POST")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            err = e.read().decode()[:300]
            print(f"[Agent] API POST error {e.code}: {path} — {err}")
            return None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < 2:
                print(f"[Agent] API POST timeout, retrying ({attempt+1}/3)...")
                time.sleep(10)
            else:
                print(f"[Agent] API POST failed after 3 attempts: {path} ({e})")
                return None


def register_team_if_needed():
    """Register a team and get token if not already set."""
    global TEAM_TOKEN
    if TEAM_TOKEN:
        return
    result = api_post("/api/register", data={"name": f"Agent-{BOT_NAME}"})
    if result and "token" in result:
        TEAM_TOKEN = result["token"]
        print(f"[Agent] Registered team, token: {TEAM_TOKEN}")
    else:
        print("[Agent] Failed to register team")
        sys.exit(1)


def get_bot_info():
    """Get current bot info from leaderboard."""
    bots = api_get("/api/leaderboard")
    if not bots:
        return None
    for b in bots:
        if b["name"] == BOT_NAME:
            return b
    return None


def get_recent_matches():
    """Get recent matches involving our bot."""
    matches = api_get("/api/matches")
    if not matches:
        return []
    # Filter to matches involving our bot
    # The matches endpoint doesn't include player names, so use elo_history as proxy
    return matches[:20]


def get_elo_history():
    """Get ELO history for our bot."""
    return api_get(f"/api/elo_history/{BOT_NAME}") or []


def get_head_to_head(opponent):
    """Get head-to-head stats."""
    return api_get(f"/api/head_to_head/{BOT_NAME}/{opponent}")


def write_context_file(bot_info, elo_history, leaderboard):
    """Write observation context for Kiro to read."""
    # Track which matches we've already reviewed
    state_path = WORKSPACE / ".agent_state.json"
    last_match_id = 0
    if state_path.exists():
        try:
            last_match_id = json.loads(state_path.read_text()).get("last_match_id", 0)
        except Exception:
            pass

    # Get recent matches and replay analysis via API
    match_analysis = []
    behaviour_report = ""
    new_last_match_id = last_match_id
    matches = api_get("/api/matches") or []
    for match in matches:
        if match["id"] <= last_match_id:
            continue
        new_last_match_id = max(new_last_match_id, match["id"])
        # Get replay data if available
        if match.get("replay_file"):
            replay = api_get(f"/replay_data/{match['id']}")
            if replay and BOT_NAME in replay.get("playernames", []):
                analysis = _analyse_replay_data(replay, BOT_NAME)
                if analysis:
                    analysis["match_id"] = match["id"]
                    match_analysis.append(analysis)
                # Generate behaviour report for the most recent loss (or any game)
                if not behaviour_report and analysis and analysis.get("result") == "lost":
                    try:
                        from behaviour_analyser import extract_behaviour_report
                        behaviour_report = extract_behaviour_report(replay, BOT_NAME) or ""
                    except Exception as e:
                        print(f"[Agent] Behaviour report failed: {e}")

    # Save state for next cycle
    state_path.write_text(json.dumps({"last_match_id": new_last_match_id}))

    # Get head-to-head vs top bots
    h2h = {}
    if leaderboard:
        for bot in leaderboard[:5]:
            if bot["name"] != BOT_NAME:
                result = get_head_to_head(bot["name"])
                if result and result.get("matches", 0) > 0:
                    h2h[bot["name"]] = result

    # Read changelog for history awareness
    changelog = ""
    changelog_path = WORKSPACE / "CHANGELOG.md"
    if changelog_path.exists():
        changelog = changelog_path.read_text()[-3000:]  # Last 3000 chars to avoid bloat

    # Per-version win rate from match analysis
    version_stats = {}
    for m in match_analysis:
        # We don't have version in replay data, but we can infer from match order
        pass
    # Get version stats from leaderboard API (bot profile has version info)
    bot_versions_url = f"/api/elo_history/{BOT_NAME}"
    # Compute win/loss summary from the matches we reviewed
    wins = sum(1 for m in match_analysis if m.get("result") == "won")
    losses = sum(1 for m in match_analysis if m.get("result") == "lost")
    timeouts = sum(1 for m in match_analysis if m.get("status") == "timeout")
    avg_score = sum(m.get("final_score", 0) for m in match_analysis) / len(match_analysis) if match_analysis else 0

    performance_summary = {
        "matches_reviewed": len(match_analysis),
        "wins": wins,
        "losses": losses,
        "timeouts": timeouts,
        "win_rate_pct": round(wins / len(match_analysis) * 100, 1) if match_analysis else 0,
        "avg_score": round(avg_score, 1),
        "avg_peak_ants": round(sum(m.get("peak_ants", 0) for m in match_analysis) / len(match_analysis), 1) if match_analysis else 0,
        "army_collapsed_count": sum(1 for m in match_analysis if m.get("army_collapsed")),
        "avg_food_efficiency": round(sum(m.get("food_efficiency", 0) for m in match_analysis) / len(match_analysis), 2) if match_analysis else 0,
        "hills_lost": sum(1 for m in match_analysis if m.get("own_hill_lost_turn") is not None),
        "hills_razed": sum(1 for m in match_analysis if m.get("hill_razed_turn") is not None),
    }

    context = {
        "bot_name": BOT_NAME,
        "language": LANGUAGE,
        "server_url": SERVER_URL,
        "current_state": bot_info,
        "elo_history": elo_history[-20:],
        "leaderboard": leaderboard[:10],
        "head_to_head": h2h,
        "performance_summary": performance_summary,
        "recent_match_analysis": match_analysis[-5:],
        "matches_reviewed": len(match_analysis),
        "changelog_recent": changelog,
        "behaviour_report": behaviour_report,
        "timestamp": datetime.now().isoformat(),
    }
    context_path = WORKSPACE / "context.json"
    context_path.write_text(json.dumps(context, indent=2))
    return context_path


def _analyse_replay_data(replay, bot_name):
    """Analyse replay JSON data — extracts comprehensive per-bot metrics."""
    names = replay.get("playernames", [])
    if bot_name not in names:
        return None

    idx = names.index(bot_name)
    rd = replay.get("replaydata", {})
    game_length = replay.get("game_length", 0)
    if game_length == 0:
        return None

    scores = replay.get("score", [0]*4)
    final_score = scores[idx]
    num_players = rd.get("players", 4)

    # --- Compute live ant counts per turn from ants data ---
    # Each ant entry: [row, col, spawn_turn, death_turn, owner, moves...]
    # Ant is alive on turns [spawn_turn, death_turn)
    ants_data = rd.get("ants", [])
    # Use delta array for O(ants + game_length) instead of O(ants * game_length)
    gl = game_length + 1
    all_ant_counts = {i: [0] * (gl + 1) for i in range(num_players)}
    for ant_entry in ants_data:
        if len(ant_entry) < 5:
            continue
        owner = ant_entry[4]
        spawn = ant_entry[2]
        death = min(ant_entry[3], gl)
        if owner in all_ant_counts:
            all_ant_counts[owner][spawn] += 1
            if death < gl:
                all_ant_counts[owner][death] -= 1
    # Convert deltas to cumulative counts
    for p in range(num_players):
        for t in range(1, gl):
            all_ant_counts[p][t] += all_ant_counts[p][t - 1]
        all_ant_counts[p] = all_ant_counts[p][:gl]
    ant_counts = all_ant_counts[idx]

    peak_ants = max(ant_counts) if ant_counts else 0
    avg_ants = sum(ant_counts) / len(ant_counts) if ant_counts else 0

    def at_pct(lst, pct):
        i = min(int(len(lst) * pct), len(lst) - 1)
        return lst[i] if lst else 0

    # Army curve sampled every 50 turns
    army_curve = []
    if ant_counts:
        step = max(1, len(ant_counts) // 20)
        army_curve = ant_counts[::step][:20]

    army_at = [at_pct(ant_counts, p) for p in [0.25, 0.5, 0.75, 1.0]]

    # --- Score progression ---
    # scores is a list per player, each being per-turn cumulative scores
    score_data = rd.get("scores", [])
    player_scores = []
    if score_data and idx < len(score_data):
        player_scores = score_data[idx]
    score_at = [at_pct(player_scores, p) for p in [0.25, 0.5, 0.75, 1.0]] if player_scores else []
    early_food = player_scores[99] - player_scores[0] if len(player_scores) > 100 else 0

    # --- Death analysis (from ants data) ---
    # Format: [row, col, spawn_turn, death_turn, owner, moves...]
    deaths_combat = 0
    total_ants_spawned = 0
    for ant_entry in ants_data:
        if len(ant_entry) < 5:
            continue
        if ant_entry[4] == idx:
            total_ants_spawned += 1
            if ant_entry[3] <= game_length:
                deaths_combat += 1

    # --- Hills ---
    hills = rd.get("hills", [])
    hill_razed_turn = None
    own_hill_lost_turn = None
    for h in hills:
        if len(h) >= 4:
            owner = h[2]
            end_turn = h[3] if len(h) == 4 else h[-1]
            if owner == idx and end_turn < game_length:
                own_hill_lost_turn = end_turn
            elif owner != idx and end_turn < game_length:
                if hill_razed_turn is None or end_turn < hill_razed_turn:
                    hill_razed_turn = end_turn

    # --- Territory control (from hive as proxy: our ants / total ants) ---
    territory_curve = []
    if ant_counts and any(ant_counts):
        step = max(1, len(ant_counts) // 10)
        for i in range(0, len(ant_counts), step):
            total = sum(all_ant_counts[p][i] for p in range(num_players) if i < len(all_ant_counts[p]))
            ours = ant_counts[i] if i < len(ant_counts) else 0
            territory_curve.append(round(ours / total * 100, 1) if total > 0 else 0)
        territory_curve = territory_curve[:10]

    # --- Food efficiency (score gained / food that spawned nearby — approximate) ---
    food_data = rd.get("food", [])
    total_food_spawned = len(food_data) if food_data else 0
    food_efficiency = round(final_score / (total_food_spawned / num_players), 2) if total_food_spawned > 0 else 0

    # --- Per-opponent breakdown ---
    opponent_details = []
    for i, name in enumerate(names):
        if i == idx:
            continue
        opp_ants = all_ant_counts.get(i, [])
        opponent_details.append({
            "name": name,
            "score": scores[i],
            "peak_ants": max(opp_ants) if opp_ants else 0,
            "beat_us": scores[i] > final_score,
        })

    # --- Status ---
    status = replay.get("status", [])[idx] if idx < len(replay.get("status", [])) else "unknown"

    # --- Army collapse detection ---
    army_collapsed = False
    collapse_turn = None
    if len(ant_counts) > 20:
        mid = len(ant_counts) // 2
        first_half_avg = sum(ant_counts[:mid]) / mid if mid > 0 else 0
        second_half_avg = sum(ant_counts[mid:]) / (len(ant_counts) - mid) if len(ant_counts) > mid else 0
        if first_half_avg > 3 and second_half_avg < first_half_avg * 0.5:
            army_collapsed = True
            # Find the turn where collapse started
            for t in range(mid, len(ant_counts)):
                if ant_counts[t] < first_half_avg * 0.5:
                    collapse_turn = t
                    break

    # --- Spatial movement metrics ---
    DIR_DELTA = {'n': (-1, 0), 's': (1, 0), 'e': (0, 1), 'w': (0, -1)}
    rows = rd.get("map", {}).get("rows", 100)
    cols = rd.get("map", {}).get("cols", 100)

    my_ants_data = [a for a in ants_data if len(a) > 5 and a[4] == idx]
    cells_visited = set()
    oscillating_ants = 0
    total_moves = 0
    stationary_moves = 0
    # Per-turn position sets for clumping
    clump_scores = []
    CLUMP_SAMPLE_STEP = max(1, game_length // 10)

    for ant in my_ants_data:
        r, c = ant[0], ant[1]
        moves = ant[5] if len(ant) > 5 else ""
        path = [(r, c)]
        cells_visited.add((r, c))
        for ch in moves:
            if ch in DIR_DELTA:
                dr, dc = DIR_DELTA[ch]
                r = (r + dr) % rows
                c = (c + dc) % cols
                total_moves += 1
            else:
                stationary_moves += 1
                total_moves += 1
            path.append((r, c))
            cells_visited.add((r, c))
        # Oscillation: check if ant revisits same cell within 4 moves frequently
        if len(path) >= 10:
            revisits = 0
            for i in range(4, len(path)):
                if path[i] in path[max(0, i-4):i]:
                    revisits += 1
            if revisits > len(path) * 0.4:
                oscillating_ants += 1

    # Clumping: at sampled turns, measure avg pairwise distance between our ants
    # Lower = more clumped (bad for exploration)
    for t in range(0, game_length, CLUMP_SAMPLE_STEP):
        positions = []
        for ant in my_ants_data:
            spawn, death = ant[2], ant[3]
            if spawn <= t < death:
                r, c = ant[0], ant[1]
                moves = ant[5] if len(ant) > 5 else ""
                steps = min(t - spawn, len(moves))
                for ch in moves[:steps]:
                    if ch in DIR_DELTA:
                        dr, dc = DIR_DELTA[ch]
                        r = (r + dr) % rows
                        c = (c + dc) % cols
                positions.append((r, c))
        if len(positions) >= 2:
            # Average min-distance between ants (toroidal)
            total_d = 0
            for i in range(len(positions)):
                min_d = 999
                for j in range(len(positions)):
                    if i == j:
                        continue
                    dr = min(abs(positions[i][0] - positions[j][0]), rows - abs(positions[i][0] - positions[j][0]))
                    dc = min(abs(positions[i][1] - positions[j][1]), cols - abs(positions[i][1] - positions[j][1]))
                    min_d = min(min_d, dr + dc)
                total_d += min_d
            clump_scores.append(round(total_d / len(positions), 1))

    exploration_coverage = len(cells_visited)
    map_cells = rows * cols
    exploration_pct = round(exploration_coverage / map_cells * 100, 1)
    stationary_pct = round(stationary_moves / total_moves * 100, 1) if total_moves > 0 else 0
    oscillation_pct = round(oscillating_ants / len(my_ants_data) * 100, 1) if my_ants_data else 0
    avg_spread = round(sum(clump_scores) / len(clump_scores), 1) if clump_scores else 0

    spatial_metrics = {
        "cells_visited": exploration_coverage,
        "exploration_pct": exploration_pct,
        "stationary_pct": stationary_pct,
        "oscillating_ants_pct": oscillation_pct,
        "avg_spread_distance": avg_spread,
        "spread_curve": clump_scores[:10],
    }

    return {
        "result": "won" if final_score == max(scores) else "lost",
        "final_score": final_score,
        "status": status,
        "game_length": game_length,
        # Army
        "peak_ants": peak_ants,
        "avg_ants": round(avg_ants, 1),
        "army_progression": army_at,
        "army_curve": army_curve,
        "army_collapsed": army_collapsed,
        "collapse_turn": collapse_turn,
        # Scoring
        "score_progression": score_at,
        "early_food_rate": early_food,
        "food_efficiency": food_efficiency,
        # Combat
        "deaths_combat": deaths_combat,
        "total_ants_spawned": total_ants_spawned,
        "survival_rate": round((total_ants_spawned - deaths_combat) / total_ants_spawned * 100, 1) if total_ants_spawned > 0 else 0,
        # Territory
        "territory_curve_pct": territory_curve,
        # Spatial
        "spatial": spatial_metrics,
        # Hills
        "hill_razed_turn": hill_razed_turn,
        "own_hill_lost_turn": own_hill_lost_turn,
        # Opponents
        "opponents": opponent_details,
    }


def run_kiro_cycle(context_path):
    """Invoke Kiro CLI to analyse and improve the bot."""
    # Load all prompt files from prompts/ directory
    prompt_files = sorted(PROMPTS_DIR.glob("*.md"))
    prompt = "\n\n".join(f.read_text() for f in prompt_files)

    # Substitute variables
    prompt = prompt.replace("{{BOT_NAME}}", BOT_NAME)
    prompt = prompt.replace("{{LANGUAGE}}", LANGUAGE)
    prompt = prompt.replace("{{SERVER_URL}}", SERVER_URL)
    prompt = prompt.replace("{{TEAM_TOKEN}}", TEAM_TOKEN)
    prompt = prompt.replace("{{CONTEXT_FILE}}", str(context_path))
    prompt = prompt.replace("{{WORKSPACE}}", str(WORKSPACE))

    print(f"[Agent] Running Kiro with model={MODEL}...")
    result = subprocess.run(
        ["kiro-cli", "chat", "--no-interactive", "--trust-all-tools", "--model", MODEL, prompt],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(WORKSPACE),
    )

    if result.returncode != 0:
        print(f"[Agent] Kiro failed (exit {result.returncode})")
        if result.stderr:
            print(f"[Agent] stderr: {result.stderr[:500]}")
        return False

    print(f"[Agent] Kiro completed successfully")
    if result.stdout:
        # Save output for review
        log_path = WORKSPACE / f"cycle_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        log_path.write_text(result.stdout)
        print(f"[Agent] Output saved to {log_path.name}")
    return True


def check_elo_regression(elo_before):
    """Wait for MATCHES_PER_CYCLE matches and check if ELO regressed."""
    print(f"[Agent] Waiting for {MATCHES_PER_CYCLE} evaluation matches...")
    games_before = 0
    bot_info = get_bot_info()
    if bot_info:
        games_before = bot_info["games_played"]

    # Poll until N new matches are played (check every 30s, timeout after 10 min)
    for _ in range(20):
        time.sleep(30)
        bot_info = get_bot_info()
        if not bot_info:
            break
        new_games = bot_info["games_played"] - games_before
        if new_games >= MATCHES_PER_CYCLE:
            break

    if not bot_info:
        return False

    elo_after = bot_info["elo"]
    delta = elo_after - elo_before
    games_played = bot_info["games_played"] - games_before
    print(f"[Agent] ELO: {elo_before:.0f} → {elo_after:.0f} (Δ{delta:+.1f}) after {games_played} games")

    if delta < ROLLBACK_THRESHOLD:
        # Read previous version from state file
        state_path = WORKSPACE / ".agent_state.json"
        prev_version = 1
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text())
                prev_version = state.get("prev_version", 1)
            except Exception:
                pass
        print(f"[Agent] ELO dropped below threshold ({ROLLBACK_THRESHOLD}), rolling back to v{prev_version}...")
        headers = {"Authorization": f"Bearer {TEAM_TOKEN}"}
        req = urllib.request.Request(
            f"{SERVER_URL}/api/bot/{BOT_NAME}/rollback/{prev_version}",
            method="POST",
            headers=headers
        )
        try:
            urllib.request.urlopen(req, timeout=10)
            print(f"[Agent] Rolled back to v{prev_version} successfully")
        except Exception as e:
            print(f"[Agent] Rollback failed: {e}")
        return True
    return False


def run_cycle():
    """Run one full observe-analyse-improve cycle."""
    print(f"\n{'='*60}")
    print(f"[Agent] Starting cycle at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    # Observe
    leaderboard = api_get("/api/leaderboard") or []
    bot_info = get_bot_info()
    elo_history = get_elo_history()

    if bot_info:
        print(f"[Agent] Current ELO: {bot_info['elo']:.0f}, Games: {bot_info['games_played']}, Wins: {bot_info['wins']}")
    else:
        print(f"[Agent] Bot '{BOT_NAME}' not found — will create on first upload")

    elo_before = bot_info["elo"] if bot_info else 1200

    # Write context
    context_path = write_context_file(bot_info, elo_history, leaderboard)

    # Save current version for potential rollback
    state_path = WORKSPACE / ".agent_state.json"
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except Exception:
            pass
    # Get current active version from bot profile page (parse from leaderboard isn't enough)
    # Use games_played as a proxy — if bot exists, it has a version
    if bot_info:
        # Store current version as prev_version before we upload a new one
        current_ver = state.get("current_version", 1)
        state["prev_version"] = current_ver
    state_path.write_text(json.dumps(state))

    # Run Kiro to analyse + improve + upload
    success = run_kiro_cycle(context_path)
    if not success:
        print("[Agent] Cycle failed, will retry next interval")
        return

    print(f"[Agent] Cycle complete")


def main():
    print(f"[Agent] AI Ants Agent starting")
    print(f"[Agent] Bot: {BOT_NAME} | Model: {MODEL} | Server: {SERVER_URL}")
    print(f"[Agent] Cycle interval: {CYCLE_INTERVAL // 60} minutes")

    WORKSPACE.mkdir(exist_ok=True)
    register_team_if_needed()

    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"[Agent] Cycle error: {e}")
            print(f"[Agent] Sleeping 30s before retry...")
            time.sleep(30)
            continue
        if CYCLE_INTERVAL == 0:
            print("[Agent] Single cycle mode, exiting.")
            break
        print(f"[Agent] Sleeping {CYCLE_INTERVAL // 60} minutes until next cycle...")
        time.sleep(CYCLE_INTERVAL)


if __name__ == "__main__":
    main()
