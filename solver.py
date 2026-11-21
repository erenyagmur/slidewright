"""Board model, move rules and BFS solver for the car-escape puzzle.

Coordinates are zero-based: x grows to the right, y grows downwards. The exit
sits on the right edge of row ``exit_row`` (row 2 zero-based = "row 3" for a
human). A *move* is sliding one vehicle any number of free cells along its axis
(the standard Rush Hour "slide" metric), so ``min_moves`` matches what a player
counts on screen.
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path

H, V = "H", "V"
RED = "R"
MAX_STATES = 250_000  # safety cap for pathological (near-empty) boards


@dataclass(frozen=True)
class Vehicle:
    id: str
    x: int
    y: int
    length: int
    orientation: str  # "H" or "V"

    def cells(self) -> list[tuple[int, int]]:
        if self.orientation == H:
            return [(self.x + i, self.y) for i in range(self.length)]
        return [(self.x, self.y + i) for i in range(self.length)]


@dataclass
class Level:
    vehicles: list[Vehicle]
    width: int = 6
    height: int = 6
    exit_row: int = 2
    name: str = ""
    meta: dict = field(default_factory=dict)

    # ---------- (de)serialisation ----------
    @classmethod
    def from_dict(cls, d: dict) -> "Level":
        grid = d.get("grid", {})
        vehicles = [
            Vehicle(str(v["id"]), int(v["x"]), int(v["y"]), int(v["length"]),
                    str(v["orientation"]).upper()[0])
            for v in d["vehicles"]
        ]
        return cls(
            vehicles=vehicles,
            width=int(grid.get("width", d.get("width", 6))),
            height=int(grid.get("height", d.get("height", 6))),
            exit_row=int(d.get("exit", {}).get("row", 2)),
            name=d.get("name", ""),
            meta=d.get("meta", {}),
        )

    @classmethod
    def load(cls, path: str | Path) -> "Level":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def to_dict(self) -> dict:
        out = {
            "name": self.name,
            "grid": {"width": self.width, "height": self.height},
            "exit": {"row": self.exit_row, "side": "right"},
            "vehicles": [asdict(v) for v in self.vehicles],
        }
        if self.meta:
            out["meta"] = self.meta
        return out

    # ---------- validation ----------
    def validate(self) -> list[str]:
        """Return a list of human-readable rule violations (empty == legal)."""
        errors: list[str] = []
        ids = [v.id for v in self.vehicles]
        if len(set(ids)) != len(ids):
            errors.append("duplicate vehicle ids")
        reds = [v for v in self.vehicles if v.id == RED]
        if len(reds) != 1:
            errors.append(f"need exactly one red car with id '{RED}'")
        else:
            r = reds[0]
            if r.orientation != H or r.length != 2:
                errors.append("red car must be a horizontal 2-cell car")
            if r.y != self.exit_row:
                errors.append(f"red car must be on the exit row (y={self.exit_row})")
        seen: dict[tuple[int, int], str] = {}
        for v in self.vehicles:
            if v.orientation not in (H, V):
                errors.append(f"{v.id}: orientation must be H or V")
                continue
            if v.length not in (2, 3):
                errors.append(f"{v.id}: length must be 2 (car) or 3 (truck)")
            for cx, cy in v.cells():
                if not (0 <= cx < self.width and 0 <= cy < self.height):
                    errors.append(f"{v.id}: cell ({cx},{cy}) is off the board")
                elif (cx, cy) in seen:
                    errors.append(f"{v.id} overlaps {seen[(cx, cy)]} at ({cx},{cy})")
                else:
                    seen[(cx, cy)] = v.id
        return errors

    def ascii(self) -> str:
        grid = [["." for _ in range(self.width)] for _ in range(self.height)]
        for v in self.vehicles:
            for cx, cy in v.cells():
                if 0 <= cx < self.width and 0 <= cy < self.height:
                    grid[cy][cx] = v.id[0]
        rows = ["".join(r) + ("  <- exit" if y == self.exit_row else "") for y, r in enumerate(grid)]
        return "\n".join(rows)


class Board:
    """Compiled, bitmask-based view of a level for fast search.

    A state is a tuple with one int per vehicle: its x (horizontal) or y
    (vertical). The other coordinate never changes.
    """

    def __init__(self, level: Level):
        errs = level.validate()
        if errs:
            raise ValueError("illegal level: " + "; ".join(errs))
        self.level = level
        self.vehicles = level.vehicles
        self.ids = [v.id for v in self.vehicles]
        self.red = self.ids.index(RED)
        W, Hh = level.width, level.height
        self.masks: list[list[int]] = []
        self.max_pos: list[int] = []
        for v in self.vehicles:
            if v.orientation == H:
                mp = W - v.length
                m = [sum(1 << (v.y * W + p + k) for k in range(v.length)) for p in range(mp + 1)]
            else:
                mp = Hh - v.length
                m = [sum(1 << ((p + k) * W + v.x) for k in range(v.length)) for p in range(mp + 1)]
            self.masks.append(m)
            self.max_pos.append(mp)
        self.start = tuple(v.x if v.orientation == H else v.y for v in self.vehicles)
        self.goal_pos = W - self.vehicles[self.red].length

    def occupancy(self, state: tuple[int, ...]) -> int:
        occ = 0
        for i, p in enumerate(state):
            occ |= self.masks[i][p]
        return occ

    def is_goal(self, state: tuple[int, ...]) -> bool:
        return state[self.red] == self.goal_pos

    def moves(self, state: tuple[int, ...]):
        """Yield (vehicle_index, new_pos, new_state) for every legal slide."""
        occ = self.occupancy(state)
        for i, p in enumerate(state):
            masks = self.masks[i]
            others = occ & ~masks[p]
            q = p - 1
            while q >= 0 and not (masks[q] & others):
                yield i, q, state[:i] + (q,) + state[i + 1:]
                q -= 1
            q = p + 1
            mp = self.max_pos[i]
            while q <= mp and not (masks[q] & others):
                yield i, q, state[:i] + (q,) + state[i + 1:]
                q += 1

    def state_to_level(self, state: tuple[int, ...], name: str = "") -> Level:
        vs = []
        for v, p in zip(self.vehicles, state):
            vs.append(Vehicle(v.id, p, v.y, v.length, v.orientation) if v.orientation == H
                      else Vehicle(v.id, v.x, p, v.length, v.orientation))
        return Level(vs, self.level.width, self.level.height, self.level.exit_row, name or self.level.name)

    def describe_move(self, frm: tuple[int, ...], to: tuple[int, ...]) -> dict:
        for i, (a, b) in enumerate(zip(frm, to)):
            if a != b:
                v = self.vehicles[i]
                if v.orientation == H:
                    d = "right" if b > a else "left"
                else:
                    d = "down" if b > a else "up"
                return {"id": v.id, "from": a, "to": b, "dir": d, "steps": abs(b - a)}
        raise ValueError("states are identical")


@dataclass
class SolveResult:
    solvable: bool
    min_moves: int | None
    path: list[dict]
    states_explored: int

    def to_dict(self) -> dict:
        return asdict(self)


def solve(level: Level) -> SolveResult:
    """Breadth-first search; returns the optimal (fewest-slides) solution."""
    board = Board(level)
    start = board.start
    if board.is_goal(start):
        return SolveResult(True, 0, [], 1)
    parent: dict[tuple, tuple | None] = {start: None}
    q = deque([start])
    while q:
        s = q.popleft()
        for _, _, n in board.moves(s):
            if n in parent:
                continue
            parent[n] = s
            if board.is_goal(n):
                path_states = [n]
                while parent[path_states[-1]] is not None:
                    path_states.append(parent[path_states[-1]])
                path_states.reverse()
                path = [board.describe_move(a, b) for a, b in zip(path_states, path_states[1:])]
                return SolveResult(True, len(path), path, len(parent))
            if len(parent) > MAX_STATES:
                return SolveResult(False, None, [], len(parent))
            q.append(n)
    return SolveResult(False, None, [], len(parent))


@dataclass
class StateGraph:
    """The full component of states reachable from the start position."""
    board: Board
    states: list[tuple]
    index: dict[tuple, int]
    adj: list[list[int]]
    dist_to_goal: list[int]  # -1 when the goal is unreachable

    @property
    def solvable(self) -> bool:
        return self.dist_to_goal[0] >= 0

    @property
    def min_moves(self) -> int | None:
        return self.dist_to_goal[0] if self.solvable else None


def explore(board: Board, cap: int = MAX_STATES) -> StateGraph:
    """Enumerate the whole reachable component, then BFS backwards from all goal
    states. Moves are reversible, so the graph is undirected."""
    states = [board.start]
    index = {board.start: 0}
    adj: list[list[int]] = []
    i = 0
    while i < len(states):
        nbrs = []
        for _, _, n in board.moves(states[i]):
            j = index.get(n)
            if j is None:
                if len(states) >= cap:
                    raise RuntimeError("state space too large")
                j = len(states)
                index[n] = j
                states.append(n)
            nbrs.append(j)
        adj.append(nbrs)
        i += 1
    dist = [-1] * len(states)
    q = deque()
    for k, s in enumerate(states):
        if board.is_goal(s):
            dist[k] = 0
            q.append(k)
    while q:
        k = q.popleft()
        for j in adj[k]:
            if dist[j] < 0:
                dist[j] = dist[k] + 1
                q.append(j)
    return StateGraph(board, states, index, adj, dist)
