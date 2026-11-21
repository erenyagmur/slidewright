"""Procedural level generator.

Strategy ("place, explore, pick the start"):
1. Randomly place vehicles (respecting truck count / mechanic constraints).
2. Explore the whole reachable state component with the solver.
3. Every state in that component is a candidate start position, and we know
   its exact distance to the exit. Pick a state whose distance and difficulty
   score hit the target. This is far more efficient than rejection sampling
   random boards, and it reaches hard (25+ move) levels quickly.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from metrics import analyze_graph
from solver import H, RED, V, Board, Level, Vehicle, explore

LETTERS = "ABCDEFGHIJKLMNOPQSTUVWXYZ"  # no R


@dataclass
class Constraints:
    difficulty: tuple[float, float] = (1.0, 10.0)
    min_moves: int = 1
    max_moves: int = 60
    trucks: tuple[int, int] = (0, 2)
    vehicles: tuple[int, int] = (5, 10)        # including the red car
    exit_truck: bool = False                    # a vertical truck must cross the exit row ahead of the red car
    min_blockers: int = 0
    tags: list[str] = field(default_factory=list)

    def describe(self) -> str:
        return (f"difficulty {self.difficulty[0]}-{self.difficulty[1]}, moves {self.min_moves}-{self.max_moves}, "
                f"trucks {self.trucks[0]}-{self.trucks[1]}, vehicles {self.vehicles[0]}-{self.vehicles[1]}"
                + (", exit-row truck" if self.exit_truck else ""))


def _free(occ: set, cells) -> bool:
    return all(c not in occ for c in cells)


def random_layout(rng: random.Random, n_vehicles: int, n_trucks: int, exit_truck: bool,
                  width: int = 6, height: int = 6, exit_row: int = 2) -> Level | None:
    occ: set = set()
    vehicles: list[Vehicle] = []
    red = Vehicle(RED, rng.randint(0, width - 4), exit_row, 2, H)
    vehicles.append(red)
    occ.update(red.cells())
    names = iter(LETTERS)
    lengths = [3] * n_trucks + [2] * (n_vehicles - 1 - n_trucks)
    if exit_truck:
        # vertical truck in a column ahead of the red car, covering the exit row
        x = rng.randint(red.x + 2, width - 1)
        y = rng.randint(max(0, exit_row - 2), min(exit_row, height - 3))
        t = Vehicle(next(names), x, y, 3, V)
        vehicles.append(t)
        occ.update(t.cells())
        lengths.remove(3)
    rng.shuffle(lengths)
    for L in lengths:
        for _ in range(60):
            o = rng.choice((H, V))
            if o == H:
                y = rng.randrange(height)
                if y == exit_row:          # a horizontal car in the exit lane can never leave it
                    continue
                v = Vehicle("?", rng.randint(0, width - L), y, L, H)
            else:
                v = Vehicle("?", rng.randrange(width), rng.randint(0, height - L), L, V)
            if _free(occ, v.cells()):
                v = Vehicle(next(names), v.x, v.y, v.length, v.orientation)
                vehicles.append(v)
                occ.update(v.cells())
                break
        else:
            return None
    return Level(vehicles, width, height, exit_row)


def _has_exit_truck(level: Level) -> bool:
    red = next(v for v in level.vehicles if v.id == RED)
    return any(v.length == 3 and v.orientation == V and v.x >= red.x + 2
               and v.y <= level.exit_row < v.y + 3 for v in level.vehicles)


def generate(c: Constraints, rng: random.Random | None = None, max_tries: int = 3000,
             name: str = "") -> tuple[Level, dict] | None:
    """Return (level, metrics) meeting the constraints, or None."""
    rng = rng or random.Random()
    lo_d, hi_d = c.difficulty
    best = None  # closest miss, used only to report progress
    for _ in range(max_tries):
        n_v = rng.randint(*c.vehicles)
        n_t = min(rng.randint(*c.trucks), n_v - 1)
        if c.exit_truck:
            n_t = max(n_t, 1)
        layout = random_layout(rng, n_v, n_t, c.exit_truck)
        if layout is None:
            continue
        board = Board(layout)
        try:
            g = explore(board, cap=60_000)
        except RuntimeError:
            continue
        cands = [k for k, d in enumerate(g.dist_to_goal) if c.min_moves <= d <= c.max_moves]
        if not cands:
            continue
        # prefer the hardest positions: sample from the top of the distance range
        cands.sort(key=lambda k: -g.dist_to_goal[k])
        pool = cands[: max(8, len(cands) // 4)]
        for k in rng.sample(pool, min(6, len(pool))):
            m = analyze_graph(g, k)
            if m["blockers"] < c.min_blockers:
                continue
            level = board.state_to_level(g.states[k], name)
            if c.exit_truck and not _has_exit_truck(level):
                continue
            gap = 0 if lo_d <= m["difficulty"] <= hi_d else min(abs(m["difficulty"] - lo_d), abs(m["difficulty"] - hi_d))
            if gap == 0:
                level.meta = {"source": "procedural", "constraints": c.describe()}
                return level, m
            if best is None or gap < best[0]:
                best = (gap, level, m)
    return None
