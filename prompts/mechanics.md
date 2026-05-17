## Game Mechanics

**Map:** Toroidal grid (wraps in both dimensions). Cells: LAND, WATER (impassable), FOOD, ants, hills.

**Turns:** Each turn you see all cells within viewradius2 of your ants. Issue one move per ant (n/e/s/w) or leave stationary. All moves resolve simultaneously. Game ends at 1000 turns or when ranks stabilize (cutoff).

**Food collection:** Food is collected when ALL ants within spawnradius2=1 of the food belong to the same player. The food is removed and added to that player's "hive" (spawn queue). If ants from multiple players are near the same food, it is destroyed with no one collecting it. If no ants are near it, it stays.

**Ant spawning:** Each turn, for each player with food in their hive, a new ant spawns at their least-recently-touched unoccupied hill. If a hill is occupied (ant standing on it), it cannot spawn. Food is the ONLY way to grow your army.

**Fog of War:** Each ant sees cells within viewradius2=77 (squared Euclidean distance, ~8.7 cell radius). Unseen cells show as -5 in `ants.map`. You only see food, enemies, and hills when your ants are close enough.

**Combat (focus mode):** After all moves resolve:
- For each ant, count its nearby enemies within attackradius2=5 (~2.2 cells). This count is its "weakness".
- An ant dies if its weakness >= the minimum weakness among its nearby enemies.
- Intuition: you die if any one of your enemies is at least as "safe" as you (has fewer or equal threats).
- Outcomes:
  - 1v1 = both die (each has weakness 1, enemy's weakness is 1, 1>=1)
  - 2v1 = lone ant dies, pair survives (lone has weakness 2, pair each have weakness 1; lone: min_enemy=1, 1<=2 → dies; pair: min_enemy=2, 2<=1 is false → survives)
  - 3v2 = the pair dies, trio survives
  - Equal groups in range = all die
- Key insight: NEVER fight equal or outnumbered. Only engage when you have numerical advantage.

**Scoring:**
- Starting score = number of hills per player (typically 2)
- Razing an enemy hill: killer gets +2 points, hill owner gets -1 point
- Food does NOT score directly — it spawns ants
- Highest score wins

**Key parameters (defaults):**
- viewradius2 = 77
- attackradius2 = 5
- spawnradius2 = 1
- turntime = 1000ms
- turns = 1000

## Data Available Each Turn

**`ants.map[row][col]`** — 2D grid of integers representing the current known state:
- `0` = YOUR ant (MY_ANT)
- `1, 2, 3...` = enemy ant (owner ID)
- `-1` (DEAD) = location where an ant died this turn
- `-2` (LAND) = empty passable ground
- `-3` (FOOD) = food on this cell
- `-4` (WATER) = impassable wall (permanent, never changes)
- `-5` = UNSEEN (never been in vision range — NOT exported as a constant, use -5 literal)

The map persists between turns. WATER is revealed permanently. LAND/FOOD/ANTS are only accurate within your current vision — cells outside vision retain their last-known state (stale). Cells never seen remain -5.

**`ants.my_ants()`** — list of `(row, col)` tuples for all your living ants this turn.

**`ants.enemy_ants()`** — list of `((row, col), owner)` for all visible enemy ants. `owner` is an int (1-9). Only includes enemies currently within your vision.

**`ants.food()`** — list of `(row, col)` for all visible food. Only food within vision range of at least one of your ants.

**`ants.my_hills()`** — list of `(row, col)` for your hills that are visible and not razed. Hills only appear when in vision.

**`ants.enemy_hills()`** — list of `((row, col), owner)` for visible enemy hills. Once you see a hill, you must remember its location yourself — it disappears from this list when out of vision.

**`ants.passable(loc)`** — True if `map[row][col] > WATER` (i.e., anything except water). This includes cells with ants on them, food, dead, and land. Does NOT guarantee you can move there (another ant may be occupying it).

**`ants.unoccupied(loc)`** — True only if cell is LAND or DEAD. Returns False for food, water, and cells with ants.

**`ants.destination(loc, direction)`** — returns the `(row, col)` you'd arrive at after moving in the given direction. Handles toroidal wrapping.

**`ants.direction(loc1, loc2)`** — returns a list of 1-2 directions (e.g., `['n', 'e']`) representing the shortest path directions from loc1 toward loc2 on the toroidal map. Does NOT account for walls.

**`ants.distance(loc1, loc2)`** — Manhattan distance between two locations, accounting for toroidal wrapping.

**`ants.visible(loc)`** — True if the given location is within viewradius2 of any of your ants this turn. Lazily computed and cached per turn.

**`ants.time_remaining()`** — milliseconds remaining in this turn. If < 10, stop immediately.

## Constants Available via `from ants import *`

```python
MY_ANT = 0      # your ant marker in the map
ANTS = 0        # same as MY_ANT
DEAD = -1       # dead ant marker
LAND = -2       # empty ground
FOOD = -3       # food cell
WATER = -4      # impassable

AIM = {'n': (-1, 0), 'e': (0, 1), 's': (1, 0), 'w': (0, -1)}
RIGHT = {'n': 'e', 'e': 's', 's': 'w', 'w': 'n'}
LEFT = {'n': 'w', 'e': 'n', 's': 'e', 'w': 's'}
BEHIND = {'n': 's', 's': 'n', 'e': 'w', 'w': 'e'}
```

**NOT exported (do not import):** UNSEEN. Use `ants.map[row][col] == -5` directly.

## Turn Lifecycle

1. Engine sends visible state (water, food, ants, hills, dead ants)
2. `ants.update()` parses it, updates `ants.map`, resets ant/food/hill lists
3. Your `do_turn(ants)` is called — issue orders via `ants.issue_order((loc, direction))`
4. If you exceed turntime, you are eliminated (timeout = instant loss)

## What You Do NOT Know

- Locations of food/enemies/hills outside your vision
- Which player collected a food (you only see it disappear)
- Enemy ant movements or intentions
- The full map on turn 1 (only cells near your starting ants are visible)
