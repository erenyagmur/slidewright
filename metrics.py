"""Structural difficulty metrics computed from the full state graph.

See README.md -> "How difficulty is scored" for the reasoning behind each
term and the weights.
"""
from __future__ import annotations

import math

from solver import RED, Board, Level, StateGraph, explore

# weights of the normalised features (they sum to 1.0)
WEIGHTS = {
    "min_moves": 0.40,
    "blockers": 0.20,
    "dead_end_ratio": 0.20,
    "reachable_states": 0.10,
    "congestion": 0.10,
}


def _clip(v: float) -> float:
    return max(0.0, min(1.0, v))


def normalise(m: dict) -> dict:
    """Map each raw metric onto 0..1 (0 = trivial, 1 = as hard as 6x6 gets)."""
    return {
        # 30+ slide moves is expert territory on a 6x6 board
        "min_moves": _clip((m["min_moves"] - 1) / 29),
        # distinct vehicles that have to move before the red car can leave
        "blockers": _clip(m["blockers"] / 10),
        # share of moves on the optimal line that make the solution longer (0 .. ~0.6)
        "dead_end_ratio": _clip(m["dead_end_ratio"] / 0.5),
        # size of the space you can get lost in, log scale (~30 .. ~30k states)
        "reachable_states": _clip((math.log10(max(m["reachable_states"], 1)) - 1.5) / 3.0),
        # a jammed board offers few slides per position (open boards: ~14, jammed: ~6)
        "congestion": _clip((14 - m["avg_branching"]) / 8),
    }


def difficulty_score(m: dict) -> float:
    n = normalise(m)
    raw = sum(WEIGHTS[k] * n[k] for k in WEIGHTS)
    return round(1 + 9 * raw, 2)


def optimal_path(g: StateGraph, start: int) -> list[int]:
    """Greedy descent along dist_to_goal = one shortest solution."""
    path = [start]
    k = start
    while g.dist_to_goal[k] > 0:
        k = min(g.adj[k], key=lambda j: (g.dist_to_goal[j], j))
        path.append(k)
    return path


def analyze_graph(g: StateGraph, start: int = 0) -> dict:
    """Metrics for the level whose start state is ``g.states[start]``.

    The reachable component is the same for every state in it, so the
    generator can score many candidate start states from one exploration.
    """
    board = g.board
    d0 = g.dist_to_goal[start]
    if d0 < 0:
        return {"solvable": False}
    n_states = len(g.states)
    avg_branch = sum(len(a) for a in g.adj) / n_states

    # dead-end ratio: at each position along the optimal solution, the share of
    # legal moves that make the remaining solution strictly longer (a "trap").
    path = optimal_path(g, start)
    dist = g.dist_to_goal
    traps = [sum(1 for j in g.adj[k] if dist[j] > dist[k]) / len(g.adj[k]) for k in path[:-1]]
    dead_end_ratio = sum(traps) / len(traps) if traps else 0.0

    moved = set()
    for a, b in zip(path, path[1:]):
        mv = board.describe_move(g.states[a], g.states[b])
        if mv["id"] != RED:
            moved.add(mv["id"])

    # vehicles physically sitting between the red car and the exit at the start
    s = g.states[start]
    red_end = s[board.red] + board.vehicles[board.red].length
    W = board.level.width
    lane = sum(1 << (board.level.exit_row * W + x) for x in range(red_end, W))
    direct = sum(1 for i, p in enumerate(s) if i != board.red and board.masks[i][p] & lane)

    m = {
        "solvable": True,
        "min_moves": d0,
        "reachable_states": n_states,
        "avg_branching": round(avg_branch, 2),
        "dead_end_ratio": round(dead_end_ratio, 3),
        "blockers": len(moved),
        "direct_blockers": direct,
        "vehicles": len(board.vehicles),
        "trucks": sum(1 for v in board.vehicles if v.length == 3),
    }
    m["difficulty"] = difficulty_score(m)
    return m


def compute_metrics(level: Level) -> dict:
    return analyze_graph(explore(Board(level)), 0)
