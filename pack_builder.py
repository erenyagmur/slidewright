"""Build a level pack with a deliberate difficulty curve.

Curve design: 5 chapters x 4 levels. Each chapter introduces one mechanic on
an *easier* first level (the breather after the previous chapter's peak),
then ramps to a new peak. The result is a rising sawtooth: overall
progression, with regular relief so players don't churn on a wall of hard
levels.
"""
from __future__ import annotations

import datetime as dt
import json
import random
from dataclasses import dataclass
from pathlib import Path

from ai_generator import (AIUnavailable, GeneratedLevel, _client, ai_generate,
                          template_note, write_notes)
from generator import Constraints, generate
from metrics import WEIGHTS
from playtest import PlaytestConfig, playtest
from solver import solve


@dataclass
class Chapter:
    name: str
    mechanic: str
    targets: list[float]
    trucks: tuple[int, int]
    vehicles: tuple[int, int]
    exit_truck: bool = False
    min_blockers: int = 0


CHAPTERS = [
    Chapter("Rush Hour Basics", "Cars only: read the exit lane and clear it.",
            [1.5, 2.3, 3.0, 3.7], (0, 0), (3, 7)),
    Chapter("Heavy Load", "Trucks appear: they need 3 free cells to clear a lane.",
            [2.6, 3.5, 4.3, 5.1], (1, 1), (5, 9)),
    Chapter("Blocked Exit", "A vertical truck crosses the exit row and must be routed out.",
            [3.9, 4.8, 5.6, 6.4], (1, 2), (7, 11), exit_truck=True),
    Chapter("Gridlock", "Chains: the blockers are themselves blocked, often by trucks.",
            [5.0, 6.0, 6.8, 7.6], (2, 3), (9, 12), min_blockers=6),
    Chapter("Rush Hour Master", "Everything combined on jammed boards.",
            [6.2, 7.2, 8.0, 8.8], (2, 4), (10, 13), exit_truck=True, min_blockers=8),
]

ROLES = ["intro", "build", "build", "peak"]

# observed relation difficulty -> optimal moves (from calibration), used to aim the generator
_MOVES_AT = [(1, 1), (2.5, 3), (4, 7), (5, 10), (6.5, 14), (7.5, 19), (8.5, 25), (9.5, 31)]


def moves_for(d: float) -> int:
    for (d0, m0), (d1, m1) in zip(_MOVES_AT, _MOVES_AT[1:]):
        if d <= d1:
            return round(m0 + (m1 - m0) * (d - d0) / (d1 - d0))
    return _MOVES_AT[-1][1]


def schedule(count: int = 20) -> list[dict]:
    """Flatten chapters into per-level targets; stretches/trims to `count`."""
    flat = [(ch, i, t) for ch in CHAPTERS for i, t in enumerate(ch.targets)]
    if count != len(flat):
        idx = [round(k * (len(flat) - 1) / max(1, count - 1)) for k in range(count)]
        flat = [flat[i] for i in idx]
    out = []
    prev = None
    for n, (ch, i, t) in enumerate(flat, 1):
        role = ROLES[i] if i < len(ROLES) else "build"
        if prev is not None and t < prev:
            role = "breather"
        out.append({"index": n, "chapter": ch, "role": role, "target": t})
        prev = t
    return out


def constraints_for(slot: dict, tol: float = 0.45) -> Constraints:
    ch: Chapter = slot["chapter"]
    t = slot["target"]
    m = moves_for(t)
    return Constraints(
        difficulty=(round(t - tol, 2), round(t + tol, 2)),
        min_moves=max(1, int(m * 0.6)), max_moves=int(m * 1.5) + 2,
        trucks=ch.trucks, vehicles=ch.vehicles, exit_truck=ch.exit_truck,
        min_blockers=min(ch.min_blockers, max(0, m - 2)),
    )


def brief_for(slot: dict) -> str:
    ch: Chapter = slot["chapter"]
    return (f"Level {slot['index']} ({slot['role']} level of chapter '{ch.name}'). Mechanic: {ch.mechanic} "
            f"Target difficulty {slot['target']} on a 1-10 scale, about {moves_for(slot['target'])} moves, "
            f"{ch.trucks[0]}-{ch.trucks[1]} trucks.")


def build_pack(count: int = 20, seed: int = 2026, mode: str = "auto", players: int = 200,
               log=print) -> dict:
    rng = random.Random(seed)
    client = None
    if mode in ("auto", "ai"):
        try:
            client = _client()
        except AIUnavailable as e:
            if mode == "ai":
                raise
            log(f"[pack] {e}: procedural levels + template notes")
    entries = []
    generated: list[GeneratedLevel] = []
    for slot in schedule(count):
        ch: Chapter = slot["chapter"]
        name = f"{slot['index']:02d} · {ch.name}"
        gl = None
        if client is not None:
            levels, _ = ai_generate(brief_for(slot), count=1, client=client, log=log, seed=rng.randint(0, 10**9))
            if levels:
                gl = levels[0]
                gl.level.name = name
        if gl is None:
            c = constraints_for(slot)
            r = None
            for widen in (0, 0.3, 0.7, 1.2):
                c.difficulty = (round(slot["target"] - 0.45 - widen, 2), round(slot["target"] + 0.45 + widen, 2))
                r = generate(c, rng, max_tries=1500, name=name)
                if r:
                    break
            if r is None:
                raise RuntimeError(f"could not generate level {slot['index']} ({c.describe()})")
            lv, m = r
            sol = solve(lv).path
            gl = GeneratedLevel(lv, m, sol, template_note(lv, m, sol), "procedural")
        pt = playtest(gl.level, PlaytestConfig(players=players, seed=seed + slot["index"]))
        pt.pop("config", None)
        generated.append(gl)
        entries.append({
            "index": slot["index"], "name": name, "chapter": ch.name, "mechanic": ch.mechanic,
            "role": slot["role"], "target_difficulty": slot["target"], "source": gl.source,
            "level": gl.level.to_dict(), "metrics": gl.metrics, "playtest": pt,
            "solution": gl.solution,
        })
        log(f"[pack] {name:<28} {slot['role']:<8} target {slot['target']:>4}  got {gl.metrics['difficulty']:>5}"
            f"  moves {gl.metrics['min_moves']:>2}  win {pt['win_rate']:.0%}  churn {pt['churn_risk']:.0%}")
    if client is not None:
        try:
            write_notes(client, "A 20-level pack with a sawtooth difficulty curve.", generated)
        except AIUnavailable as e:
            log(f"[pack] notes fell back to templates: {e}")
    for e, gl in zip(entries, generated):
        e["note"] = gl.note
    return {
        "name": "Jam Lab Pack",
        "created": dt.date.today().isoformat(),
        "seed": seed,
        "difficulty_weights": WEIGHTS,
        "playtest": {"players": players, "max_attempts": PlaytestConfig().max_attempts},
        "levels": entries,
    }


def plot_curve(pack: dict, path: str | Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    lv = pack["levels"]
    x = [e["index"] for e in lv]
    target = [e["target_difficulty"] for e in lv]
    actual = [e["metrics"]["difficulty"] for e in lv]
    win = [e["playtest"]["win_rate"] * 100 for e in lv]
    churn = [e["playtest"]["churn_risk"] * 100 for e in lv]

    ink, ink2, grid, surface = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    blue, orange = "#2a78d6", "#eb6834"
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": grid,
                         "axes.labelcolor": ink2, "xtick.color": ink2, "ytick.color": ink2})
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True,
                                   gridspec_kw={"height_ratios": [3, 2], "hspace": 0.12})
    fig.patch.set_facecolor(surface)

    chapters: list[tuple[str, int, int]] = []
    for e in lv:
        if chapters and chapters[-1][0] == e["chapter"]:
            chapters[-1] = (e["chapter"], chapters[-1][1], e["index"])
        else:
            chapters.append((e["chapter"], e["index"], e["index"]))
    for ax in (ax1, ax2):
        ax.set_facecolor(surface)
        for k, (_, a, b) in enumerate(chapters):
            if k % 2 == 0:
                ax.axvspan(a - 0.5, b + 0.5, color="#f1f0ec", zorder=0, lw=0)
        ax.grid(axis="y", color=grid, lw=0.8, zorder=1)
        ax.spines[["top", "right"]].set_visible(False)

    ax1.plot(x, target, ls="--", lw=1.5, color="#8b8a85", zorder=2, label="Target curve")
    ax1.plot(x, actual, lw=2, color=blue, marker="o", ms=7, mec=surface, mew=2, zorder=3,
             label="Measured difficulty")
    for e in lv:
        if e["role"] == "breather":
            ax1.annotate("breather", (e["index"], e["metrics"]["difficulty"]), xytext=(0, -18),
                         textcoords="offset points", ha="center", fontsize=8, color=ink2)
    for name, a, b in chapters:
        ax1.text((a + b) / 2, 10.3, name, ha="center", va="bottom", fontsize=9, color=ink2)
    ax1.set_ylim(0, 10)
    ax1.set_ylabel("Difficulty score (1-10)")
    ax1.legend(loc="upper left", frameon=False, bbox_to_anchor=(0, 0.98))
    fig.suptitle("Jam Lab pack: difficulty curve and simulated player outcomes", x=0.07, ha="left",
                 fontsize=13, color=ink, y=0.98)

    w = 0.38
    ax2.bar([i - w / 2 for i in x], win, width=w, color=blue, zorder=2, label="Win rate per attempt")
    ax2.bar([i + w / 2 for i in x], churn, width=w, color=orange, zorder=2, label="Churn risk (failed all 5 attempts)")
    ax2.set_ylim(0, 100)
    ax2.set_ylabel("% of simulated players")
    ax2.set_xlabel("Level")
    ax2.set_xticks(x)
    ax2.legend(loc="upper right", frameon=False, ncols=2, bbox_to_anchor=(1, 1.12))
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=surface)
    plt.close(fig)


def save_pack(pack: dict, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(pack, indent=2, ensure_ascii=False), encoding="utf-8")
