"""Simulated playtests: a population of imperfect "player agents".

Each simulated player has a skill profile (how far they look ahead, how often
they make a random/impulsive move). They play a level up to ``max_attempts``
times, each attempt capped at a move limit. Aggregated over 200 players this
gives the KPIs a live game tracks per level: win rate, attempts-to-clear and
churn risk (share of players who fail every attempt and would likely quit).
"""
from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass

from solver import Board, Level, explore


@dataclass
class PlaytestConfig:
    players: int = 200
    max_attempts: int = 5
    move_limit_factor: float = 2.0  # limit = max(factor * optimal, optimal + extra)
    move_limit_extra: int = 10
    seed: int = 7


class PlayerModel:
    """Greedy-with-lookahead heuristic player. Memoises per level."""

    def __init__(self, board: Board):
        self.board = board
        W = board.level.width
        self.row_bits = board.level.exit_row * W
        self.W = W
        self._h: dict = {}
        self._v: dict = {}

    def heuristic(self, s: tuple) -> float:
        """What a human 'sees': cars in the red car's lane, and whether those
        cars are themselves stuck."""
        h = self._h.get(s)
        if h is not None:
            return h
        b = self.board
        if b.is_goal(s):
            self._h[s] = 0.0
            return 0.0
        red_end = s[b.red] + b.vehicles[b.red].length
        lane = sum(1 << (self.row_bits + x) for x in range(red_end, self.W))
        occ = b.occupancy(s)
        h = 1.0
        for i, p in enumerate(s):
            if i == b.red or not (b.masks[i][p] & lane):
                continue
            h += 2.0
            # can this blocker get out of the lane in one slide?
            others = occ & ~b.masks[i][p]
            free = False
            for direction in (-1, 1):
                q = p + direction
                while 0 <= q <= b.max_pos[i] and not (b.masks[i][q] & others):
                    if not (b.masks[i][q] & lane):
                        free = True
                        break
                    q += direction
                if free:
                    break
            if not free:
                h += 1.5
        self._h[s] = h
        return h

    def value(self, s: tuple, depth: int) -> float:
        """Best heuristic value reachable within ``depth`` more moves."""
        key = (s, depth)
        v = self._v.get(key)
        if v is not None:
            return v
        v = self.heuristic(s)
        if depth > 0 and v > 0:
            for _, _, n in self.board.moves(s):
                v = min(v, self.value(n, depth - 1) + 0.05)
        self._v[key] = v
        return v


@dataclass
class Skill:
    lookahead: int      # plies of explicit search over the visible heuristic
    insight: float      # chance per move of "seeing" a genuinely correct move (planning)
    epsilon: float      # chance per move of an impulsive random move
    temperature: float  # softness of the choice between heuristic options


def sample_skill(rng: random.Random) -> Skill:
    return Skill(
        lookahead=rng.choices([1, 2, 3], weights=[0.35, 0.45, 0.20])[0],
        insight=rng.uniform(INSIGHT[0], INSIGHT[1]),
        epsilon=rng.uniform(EPSILON[0], EPSILON[1]),
        temperature=rng.uniform(0.3, 1.0),
    )


INSIGHT = (0.25, 0.75)
EPSILON = (0.02, 0.15)


def play_attempt(model: PlayerModel, rng: random.Random, sk: Skill, limit: int,
                 dist: dict) -> tuple[bool, int]:
    b = model.board
    s = b.start
    seen: dict[tuple, int] = {s: 1}
    prev = None
    lookahead, epsilon, temperature = sk.lookahead, sk.epsilon, sk.temperature
    for step in range(1, limit + 1):
        options = [n for _, _, n in b.moves(s)]
        if rng.random() < sk.insight:
            d = dist[s]
            nxt = rng.choice([n for n in options if dist[n] < d])
        elif rng.random() < epsilon:
            nxt = rng.choice(options)
        else:
            scores = []
            for n in options:
                sc = model.value(n, lookahead - 1)
                sc += 0.8 * seen.get(n, 0)        # players dislike going in circles
                if n == prev:
                    sc += 1.5                      # ...and rarely undo a move instantly
                scores.append(sc)
            best = min(scores)
            weights = [math.exp(-(sc - best) / temperature) for sc in scores]
            nxt = rng.choices(options, weights)[0]
        prev, s = s, nxt
        seen[s] = seen.get(s, 0) + 1
        if b.is_goal(s):
            return True, step
    return False, limit


def playtest(level: Level, cfg: PlaytestConfig | None = None, min_moves: int | None = None) -> dict:
    cfg = cfg or PlaytestConfig()
    board = Board(level)
    g = explore(board)
    min_moves = g.min_moves
    dist = {st: d for st, d in zip(g.states, g.dist_to_goal)}
    if min_moves is None:
        return {"solvable": False}
    limit = max(int(cfg.move_limit_factor * min_moves), min_moves + cfg.move_limit_extra)
    rng = random.Random(cfg.seed)
    model = PlayerModel(board)

    attempts_total = wins = first_try = cleared = 0
    attempts_to_clear: list[int] = []
    winning_moves: list[int] = []
    for _ in range(cfg.players):
        sk = sample_skill(rng)  # a population with mixed skill
        for attempt in range(1, cfg.max_attempts + 1):
            attempts_total += 1
            won, moves = play_attempt(model, rng, sk, limit, dist)
            if won:
                wins += 1
                cleared += 1
                attempts_to_clear.append(attempt)
                winning_moves.append(moves)
                if attempt == 1:
                    first_try += 1
                break

    n = cfg.players
    return {
        "players": n,
        "move_limit": limit,
        "win_rate": round(wins / attempts_total, 3),          # per attempt, like a live KPI
        "first_try_win_rate": round(first_try / n, 3),
        "clear_rate": round(cleared / n, 3),                    # within max_attempts
        "avg_attempts": round(sum(attempts_to_clear) / len(attempts_to_clear), 2) if attempts_to_clear else None,
        "churn_risk": round(1 - cleared / n, 3),               # failed every attempt
        "avg_moves_when_won": round(sum(winning_moves) / len(winning_moves), 1) if winning_moves else None,
        "config": asdict(cfg),
    }
