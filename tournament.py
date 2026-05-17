"""Local tournament runner — pits bot candidates against each other to find the best."""
import json
import os
import random
import subprocess
import tempfile
from pathlib import Path
from itertools import combinations

AGENT_DIR = Path(__file__).parent
ANTS_DIR = Path(os.environ.get("ANTS_DIR", str(AGENT_DIR.parent / "aichallenge" / "ants")))
ANTS_PY = ANTS_DIR / "dist" / "starter_bots" / "python" / "ants.py"
ANTS_PY_LOCAL = AGENT_DIR / "engine" / "ants.py"
ANTS_PY_SHA256 = "af144ce63faabc338d040ae9211c97b2169878a091e7db5e749578975e8fc7f6"
SAMPLE_BOTS_DIR = AGENT_DIR / "sample-bot"


def verify_ants_py():
    """Verify ants.py hasn't been tampered with."""
    import hashlib
    src = ANTS_PY_LOCAL if ANTS_PY_LOCAL.exists() else ANTS_PY
    if not src.exists():
        return
    actual = hashlib.sha256(src.read_bytes()).hexdigest()
    if actual != ANTS_PY_SHA256:
        print(f"[Tournament] WARNING: ants.py checksum mismatch!\n  Expected: {ANTS_PY_SHA256}\n  Got:      {actual}")


def find_maps(n=5, players=None):
    """Pick n random maps for the tournament, optionally filtered by player count."""
    maps_dir = ANTS_DIR / "maps"
    all_maps = list(maps_dir.rglob("*.map"))
    if players:
        all_maps = [m for m in all_maps if f"p{players:02d}" in m.name]
    if not all_maps:
        all_maps = list(maps_dir.rglob("*.map"))
    return random.sample(all_maps, min(n, len(all_maps)))


def run_game(bot_dirs, map_file):
    """Run a single game between bots. Each bot_dir must contain MyBot.py and ants.py.
    
    Args:
        bot_dirs: list of Path objects pointing to bot directories
        map_file: Path to the map file
        
    Returns:
        dict with scores, status, game_length or None on failure
    """
    # Create run scripts for each bot
    bot_cmds = []
    for bot_dir in bot_dirs:
        # Ensure ants.py is available (patched Python 3 version from engine dist)
        ants_dst = bot_dir / "ants.py"
        if not ants_dst.exists():
            src = ANTS_PY_LOCAL if ANTS_PY_LOCAL.exists() else ANTS_PY
            if src.exists():
                ants_dst.write_text(src.read_text())
        
        run_sh = bot_dir / "run.sh"
        run_sh.write_text(f"#!/bin/sh\ncd {bot_dir}\npython3 MyBot.py\n")
        run_sh.chmod(0o755)
        bot_cmds.append(str(run_sh))

    with tempfile.TemporaryDirectory(dir=str(AGENT_DIR)) as log_dir:
        cmd = [
            "python3", str(ANTS_DIR / "playgame.py"),
            "--player_seed", str(random.randint(0, 99999)),
            "--end_wait=0.25",
            "--nolaunch",
            "--turns", "500",
            "--turntime", "1000",
            "--loadtime", "3000",
            "--map_file", str(map_file),
            "--log_dir", log_dir,
            "-R",
        ] + bot_cmds

        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, cwd=str(ANTS_DIR), preexec_fn=os.setsid
            )
            stdout, stderr = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            return None
        finally:
            # Kill the entire process group and any orphan bots
            try:
                os.killpg(os.getpgid(proc.pid), 9)
            except (ProcessLookupError, OSError):
                pass
            subprocess.run(["pkill", "-9", "-f", "MyBot.py"], capture_output=True)
            try:
                proc.wait(timeout=5)
            except Exception:
                pass

        replay_files = list(Path(log_dir).glob("*.replay"))
        if not replay_files:
            return None

        try:
            replay_data = json.loads(replay_files[0].read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            return None

        if "error" in replay_data:
            return None

        return {
            "scores": replay_data["score"],
            "status": replay_data["status"],
            "game_length": replay_data.get("game_length", 0),
        }


def run_tournament(bot_entries, num_maps=5, games_per_pair=2):
    """Run a round-robin tournament between bot candidates.
    
    Args:
        bot_entries: list of dicts with keys: name, dir (Path to bot directory)
        num_maps: number of maps to play on
        games_per_pair: games per map per matchup
        
    Returns:
        list of dicts sorted by wins: [{name, wins, losses, avg_score, status}]
    """
    maps = find_maps(num_maps, players=2)
    if not maps:
        print("[Tournament] No maps found!")
        return []

    verify_ants_py()

    # Need at least 2 bots
    if len(bot_entries) < 2:
        print("[Tournament] Need at least 2 bots")
        return []

    results = {e["name"]: {"wins": 0, "losses": 0, "total_score": 0, "games": 0, "crashes": 0}
               for e in bot_entries}

    # Run pairwise matchups on 2-player maps
    for bot_a, bot_b in combinations(bot_entries, 2):
        for map_file in maps:
            for _ in range(games_per_pair):
                game = run_game([bot_a["dir"], bot_b["dir"]], map_file)
                if not game:
                    continue

                scores = game["scores"]
                statuses = game["status"]
                players = [bot_a, bot_b]

                for i, entry in enumerate(players):
                    name = entry["name"]
                    results[name]["games"] += 1
                    results[name]["total_score"] += scores[i]
                    if scores[i] > scores[1 - i]:
                        results[name]["wins"] += 1
                    elif scores[i] < scores[1 - i]:
                        results[name]["losses"] += 1
                    if statuses[i] in ("crashed", "timeout"):
                        results[name]["crashes"] += 1

    # Sort by wins descending, then avg score
    standings = []
    for name, r in results.items():
        avg = r["total_score"] / r["games"] if r["games"] > 0 else 0
        standings.append({
            "name": name,
            "wins": r["wins"],
            "losses": r["losses"],
            "avg_score": round(avg, 2),
            "games": r["games"],
            "crashes": r["crashes"],
        })
    standings.sort(key=lambda x: (-x["wins"], -x["avg_score"]))
    return standings
