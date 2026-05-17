"""Extract a turn-by-turn behaviour narrative from replay data for AI agent analysis."""

DIR_MAP = {'n': (-1, 0), 's': (1, 0), 'e': (0, 1), 'w': (0, -1)}


def extract_behaviour_report(replay, bot_name, max_turns=150):
    """Generate a text narrative of what happened in a game.
    
    Focuses on: food collection patterns, army growth, combat events,
    and comparison with the winning bot's behaviour.
    """
    names = replay.get("playernames", [])
    if bot_name not in names:
        return None

    idx = names.index(bot_name)
    rd = replay.get("replaydata", {})
    game_length = replay.get("game_length", 0)
    rows = rd.get("map", {}).get("rows", 100)
    cols = rd.get("map", {}).get("cols", 100)
    ants_data = rd.get("ants", [])
    food_data = rd.get("food", [])
    scores = replay.get("score", [0]*4)

    # Find the winner
    winner_idx = scores.index(max(scores))
    winner_name = names[winner_idx]

    # Group ants by owner
    my_ants = [a for a in ants_data if a[4] == idx]
    winner_ants = [a for a in ants_data if a[4] == winner_idx] if winner_idx != idx else []

    # Group food by collector
    my_food = [f for f in food_data if len(f) >= 5 and f[4] == idx]
    winner_food = [f for f in food_data if len(f) >= 5 and f[4] == winner_idx] if winner_idx != idx else []

    report = []
    report.append(f"# Game Behaviour Report")
    report.append(f"**Result:** {'WON' if idx == winner_idx else 'LOST'} | Score: {scores[idx]} | Winner: {winner_name} (score {scores[winner_idx]})")
    report.append(f"**Game length:** {game_length} turns | **Map:** {rows}x{cols}")
    report.append("")

    # Army growth comparison
    report.append("## Army Growth Timeline")
    checkpoints = [10, 25, 50, 100, 150, 200, 300, 500]
    for t in checkpoints:
        if t > min(game_length, max_turns):
            break
        my_alive = sum(1 for a in my_ants if a[2] <= t < a[3])
        if winner_ants:
            win_alive = sum(1 for a in winner_ants if a[2] <= t < a[3])
            report.append(f"- Turn {t}: You={my_alive} ants, {winner_name}={win_alive} ants")
        else:
            report.append(f"- Turn {t}: You={my_alive} ants")
    report.append("")

    # Food collection timeline
    report.append("## Food Collection")
    my_food_sorted = sorted(my_food, key=lambda f: f[3])
    win_food_sorted = sorted(winner_food, key=lambda f: f[3]) if winner_food else []
    
    my_food_by_50 = {}
    for f in my_food_sorted:
        bucket = (f[3] // 50) * 50
        my_food_by_50[bucket] = my_food_by_50.get(bucket, 0) + 1
    
    win_food_by_50 = {}
    for f in win_food_sorted:
        bucket = (f[3] // 50) * 50
        win_food_by_50[bucket] = win_food_by_50.get(bucket, 0) + 1

    all_buckets = sorted(set(list(my_food_by_50.keys()) + list(win_food_by_50.keys())))
    for b in all_buckets[:6]:
        mine = my_food_by_50.get(b, 0)
        theirs = win_food_by_50.get(b, 0)
        if winner_ants:
            report.append(f"- Turns {b}-{b+49}: You collected {mine} food, {winner_name} collected {theirs}")
        else:
            report.append(f"- Turns {b}-{b+49}: You collected {mine} food")
    
    if not my_food_sorted:
        report.append("- You collected NO food the entire game!")
    elif my_food_sorted:
        report.append(f"- First food collected at turn {my_food_sorted[0][3]}")
        if win_food_sorted:
            report.append(f"- {winner_name}'s first food at turn {win_food_sorted[0][3]}")
    report.append("")

    # Early game movement analysis (first ant, first 30 turns)
    report.append("## Early Game (Your first ant, first 30 moves)")
    if my_ants:
        first_ant = min(my_ants, key=lambda a: a[2])
        moves = first_ant[5] if len(first_ant) > 5 else ""
        start_r, start_c = first_ant[0], first_ant[1]
        
        # Track position
        r, c = start_r, start_c
        positions = [(r, c)]
        for m in moves[:30]:
            if m in DIR_MAP:
                dr, dc = DIR_MAP[m]
                r = (r + dr) % rows
                c = (c + dc) % cols
                positions.append((r, c))
        
        # Find nearby food at game start
        early_food = [(f[0], f[1]) for f in food_data if f[2] <= 5]
        
        report.append(f"- Spawned at ({start_r}, {start_c})")
        report.append(f"- Moves: {''.join(moves[:30])}")
        report.append(f"- Position after 30 turns: ({r}, {c})")
        
        # Did it move toward food?
        if early_food:
            nearest_food = min(early_food, key=lambda f: abs(f[0]-start_r) + abs(f[1]-start_c))
            dist_start = abs(nearest_food[0]-start_r) + abs(nearest_food[1]-start_c)
            dist_end = abs(nearest_food[0]-r) + abs(nearest_food[1]-c)
            report.append(f"- Nearest food at game start: ({nearest_food[0]}, {nearest_food[1]}), distance={dist_start}")
            report.append(f"- After 30 moves, distance to that food: {dist_end} ({'closer' if dist_end < dist_start else 'FARTHER'})")
    report.append("")

    # Winner's early game for comparison
    if winner_ants:
        report.append(f"## Early Game ({winner_name}'s first ant, first 30 moves)")
        first_win_ant = min(winner_ants, key=lambda a: a[2])
        moves = first_win_ant[5] if len(first_win_ant) > 5 else ""
        start_r, start_c = first_win_ant[0], first_win_ant[1]
        r, c = start_r, start_c
        for m in moves[:30]:
            if m in DIR_MAP:
                dr, dc = DIR_MAP[m]
                r = (r + dr) % rows
                c = (c + dc) % cols
        report.append(f"- Spawned at ({start_r}, {start_c})")
        report.append(f"- Moves: {''.join(moves[:30])}")
        report.append(f"- Position after 30 turns: ({r}, {c})")
        report.append("")

    # Combat events
    report.append("## Combat Deaths")
    my_deaths = [(a[3], a[0], a[1]) for a in my_ants if a[3] < game_length]
    win_deaths = [(a[3], a[0], a[1]) for a in winner_ants if a[3] < game_length]
    report.append(f"- Your ants killed: {len(my_deaths)} (of {len(my_ants)} total spawned)")
    if winner_ants:
        report.append(f"- {winner_name}'s ants killed: {len(win_deaths)} (of {len(winner_ants)} total spawned)")
    if my_deaths:
        early_deaths = [d for d in my_deaths if d[0] < 100]
        report.append(f"- Deaths in first 100 turns: {len(early_deaths)}")
    report.append("")

    # Key insight
    report.append("## Key Observations")
    if not my_food_sorted:
        report.append("- CRITICAL: You never collected any food. Your army never grew beyond starting ants.")
    if winner_food and my_food_sorted:
        if win_food_sorted[0][3] < my_food_sorted[0][3]:
            report.append(f"- {winner_name} collected first food {my_food_sorted[0][3] - win_food_sorted[0][3]} turns before you")
    if winner_ants:
        my_peak = len(my_ants)
        win_peak = len(winner_ants)
        report.append(f"- Total ants spawned: You={my_peak}, {winner_name}={win_peak}")
    if my_deaths and len(my_deaths) > len(my_ants) * 0.5:
        report.append("- Over 50% of your ants died in combat — too aggressive or poor positioning")

    return "\n".join(report)
