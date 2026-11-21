"""AI-assisted level generation with Claude, verified by the solver.

Pipeline
  brief --(Claude)--> spec --(Claude)--> N layout variants
        --> solver + metrics validate each variant
        --> rejected variants go back to Claude with concrete solver feedback
        --> (last resort) solver "retarget": keep Claude's layout, pick a start
            state in the same state space that hits the target
        --> Claude writes a designer's note for every accepted level

Without ANTHROPIC_API_KEY the same entry point falls back to a local brief
parser + the procedural generator + template notes, so the tool always runs.
"""
from __future__ import annotations

import json
import os
import random
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from generator import Constraints, _has_exit_truck, generate
from metrics import analyze_graph
from solver import Board, Level, Vehicle, explore, solve

MODEL = "claude-opus-5-5"


# ---------------------------------------------------------------- schemas
class BriefSpec(BaseModel):
    level_number: int | None = Field(description="level index if the brief names one")
    difficulty_min: float = Field(description="lower bound of target difficulty on the 1-10 scale")
    difficulty_max: float = Field(description="upper bound of target difficulty on the 1-10 scale")
    target_moves: int = Field(description="target optimal solution length in slide moves")
    moves_tolerance: int = Field(description="accepted +/- around target_moves, usually 2-4")
    trucks_min: int
    trucks_max: int
    exit_truck: bool = Field(description="must a vertical truck cross the exit row ahead of the red car?")
    mechanic: str = Field(description="one sentence: the mechanic or idea this level should focus on")


class VehicleSpec(BaseModel):
    id: str
    x: int
    y: int
    length: Literal[2, 3]
    orientation: Literal["H", "V"]


class LayoutVariant(BaseModel):
    name: str
    idea: str = Field(description="one sentence on the intended solving insight")
    vehicles: list[VehicleSpec]


class Variants(BaseModel):
    variants: list[LayoutVariant]


class DesignerNote(BaseModel):
    name: str
    why_it_works: str
    what_it_teaches: str


class Notes(BaseModel):
    notes: list[DesignerNote]


# ---------------------------------------------------------------- prompts
RULES = """You are a senior level designer for a mobile car-escape sliding puzzle.

Board rules (follow them exactly):
- 6x6 grid, zero-based coordinates: x = column 0..5 left to right, y = row 0..5 top to bottom.
- A vehicle is {id, x, y, length, orientation}. (x, y) is its top-left cell.
  "H" vehicles occupy (x..x+length-1, y); "V" vehicles occupy (x, y..y+length-1).
- length 2 = car, length 3 = truck. Every cell must be on the board; vehicles must not overlap.
- Vehicles slide only along their own axis and cannot pass through each other.
- The red car has id "R": horizontal, length 2, on row y=2. The exit is the right edge of row 2.
  A level is solved when R reaches x=4.
- Never put another horizontal vehicle on row 2 to the right of R: it could never leave and
  the level would be unsolvable.
- Use single capital letters (not R) as ids for the other vehicles.
- One move = sliding one vehicle any number of free cells. Difficulty comes from long chains of
  dependencies: the red car's lane is blocked by vehicles that are themselves blocked, and the
  right first move is not the obvious one. Jammed boards (10-13 vehicles) are needed for 15+ moves.

Example (ASCII, '.' empty, R = red car):
..AFFF
..A.C.
RRA.C.   <- exit
...B..
...B..
DD.BEE
as JSON: R(0,2,2,H) A(2,0,3,V) F(3,0,3,H) C(4,1,2,V) B(3,3,3,V) D(0,5,2,H) E(4,5,2,H). Optimal: 3 moves."""


def _ascii(level: Level) -> str:
    return level.ascii()


# ---------------------------------------------------------------- spec parsing (local fallback)
DIFFICULTY_WORDS = [
    (r"\bvery hard|expert|brutal\b", (7.5, 9.5)),
    (r"\bmedium[- ]hard|hard[- ]ish\b", (5.5, 7.0)),
    (r"\bmedium[- ]easy|easy[- ]medium\b", (2.5, 4.0)),
    (r"\bhard\b", (6.5, 8.5)),
    (r"\bmedium\b", (4.0, 5.5)),
    (r"\b(easy|tutorial|intro)\b", (1.0, 3.0)),
]


def parse_brief_local(brief: str) -> BriefSpec:
    b = brief.lower()
    lo, hi = 3.5, 6.0
    for pat, rng in DIFFICULTY_WORDS:
        if re.search(pat, b):
            lo, hi = rng
            break
    m = re.search(r"(\d+)\s*(?:slide\s*)?moves?", b)
    target = int(m.group(1)) if m else int(round((lo + hi) / 2 * 2.6))
    lv = re.search(r"level\s*(\d+)", b)
    trucks = "truck" in b
    exit_truck = trucks and bool(re.search(r"exit|lane|row", b))
    return BriefSpec(
        level_number=int(lv.group(1)) if lv else None,
        difficulty_min=lo, difficulty_max=hi, target_moves=target, moves_tolerance=3,
        trucks_min=1 if trucks else 0, trucks_max=3 if trucks else 1, exit_truck=exit_truck,
        mechanic=brief.strip(),
    )


def spec_to_constraints(spec: BriefSpec) -> Constraints:
    moves_lo = max(1, spec.target_moves - spec.moves_tolerance)
    moves_hi = spec.target_moves + spec.moves_tolerance
    veh_lo = 4 + min(8, moves_lo // 3)
    return Constraints(
        difficulty=(spec.difficulty_min, spec.difficulty_max),
        min_moves=moves_lo, max_moves=moves_hi,
        trucks=(spec.trucks_min, max(spec.trucks_min, spec.trucks_max)),
        vehicles=(min(veh_lo, 11), min(veh_lo + 4, 13)),
        exit_truck=spec.exit_truck,
    )


# ---------------------------------------------------------------- validation
@dataclass
class Verdict:
    ok: bool
    reasons: list[str]
    level: Level | None = None
    metrics: dict = field(default_factory=dict)
    solution: list = field(default_factory=list)


def check_variant(v: LayoutVariant, spec: BriefSpec) -> Verdict:
    level = Level([Vehicle(s.id, s.x, s.y, s.length, s.orientation) for s in v.vehicles], name=v.name)
    errs = level.validate()
    if errs:
        return Verdict(False, ["illegal layout: " + "; ".join(errs[:6])], level)
    g = explore(Board(level))
    if not g.solvable:
        return Verdict(False, ["unsolvable: the red car can never reach the exit"], level)
    m = analyze_graph(g, 0)
    reasons = []
    lo_m, hi_m = spec.target_moves - spec.moves_tolerance, spec.target_moves + spec.moves_tolerance
    if not lo_m <= m["min_moves"] <= hi_m:
        reasons.append(f"optimal solution is {m['min_moves']} moves, target is {lo_m}-{hi_m}")
    if not spec.difficulty_min <= m["difficulty"] <= spec.difficulty_max:
        reasons.append(f"difficulty score {m['difficulty']} outside {spec.difficulty_min}-{spec.difficulty_max}")
    if not spec.trucks_min <= m["trucks"] <= max(spec.trucks_min, spec.trucks_max):
        reasons.append(f"{m['trucks']} trucks, brief wants {spec.trucks_min}-{spec.trucks_max}")
    if spec.exit_truck and not _has_exit_truck(level):
        reasons.append("no vertical truck crosses the exit row ahead of the red car")
    sol = solve(level).path
    return Verdict(not reasons, reasons, level, m, sol)


def feedback_text(variants: list[LayoutVariant], verdicts: list[Verdict]) -> str:
    parts = ["Solver report on your variants:"]
    for v, vd in zip(variants, verdicts):
        status = "ACCEPTED" if vd.ok else "REJECTED"
        parts.append(f"\n## {v.name}: {status}")
        if vd.level is not None:
            parts.append(_ascii(vd.level))
        if vd.metrics:
            m = vd.metrics
            parts.append(f"min_moves={m['min_moves']} difficulty={m['difficulty']} blockers={m['blockers']} "
                         f"dead_end_ratio={m['dead_end_ratio']} states={m['reachable_states']}")
        if vd.solution:
            parts.append("optimal line: " + " ".join(f"{s['id']} {s['dir']} {s['steps']}" for s in vd.solution))
        for r in vd.reasons:
            parts.append(f"- {r}")
    parts.append("\nReturn corrected or replacement layouts ONLY for the rejected variants. If a level was "
                 "too short, add a dependency chain (block the blockers); if too long, free one vehicle.")
    return "\n".join(parts)


# ---------------------------------------------------------------- Claude calls
class AIUnavailable(RuntimeError):
    pass


def _client():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise AIUnavailable("ANTHROPIC_API_KEY is not set")
    import anthropic
    return anthropic.Anthropic()


def _ask(client, messages: list, schema, effort: str = "high"):
    """One structured call. Returns (assistant_content, parsed)."""
    resp = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=RULES,
        messages=messages,
        output_format=schema,
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        # if a safety classifier declines, the API retries on a fallback model in the same call
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise AIUnavailable(f"model returned no usable output (stop_reason={resp.stop_reason})")
    return resp.content, resp.parsed_output


def retarget(level: Level, spec: BriefSpec) -> tuple[Level, dict] | None:
    """Keep the AI's vehicle layout but choose the start state (same pieces,
    slid along their axes) whose distance/difficulty is closest to target."""
    board = Board(level)
    g = explore(board)
    if not g.solvable:
        return None
    best = None
    for k, d in enumerate(g.dist_to_goal):
        if d < 1 or abs(d - spec.target_moves) > spec.moves_tolerance:
            continue
        m = analyze_graph(g, k)
        mid = (spec.difficulty_min + spec.difficulty_max) / 2
        gap = abs(m["difficulty"] - mid) + abs(d - spec.target_moves) * 0.2
        if best is None or gap < best[0]:
            best = (gap, k, m)
    if best is None:
        return None
    _, k, m = best
    lv = board.state_to_level(g.states[k], level.name)
    return lv, m


@dataclass
class GeneratedLevel:
    level: Level
    metrics: dict
    solution: list
    note: dict
    source: str


def ai_generate(brief: str, count: int = 3, variants: int = 4, rounds: int = 3,
                client=None, log=print, seed: int | None = None) -> tuple[list[GeneratedLevel], dict]:
    """Main entry point. Returns (levels, report)."""
    try:
        client = client or _client()
    except AIUnavailable as e:
        log(f"[ai] {e} -> falling back to the procedural generator")
        return procedural_from_brief(brief, count, log, seed)

    report: dict = {"mode": "ai", "model": MODEL, "rounds": []}
    _, spec = _ask(client, [{"role": "user", "content":
                   "Turn this level brief into a target spec for our 1-10 difficulty scale "
                   "(1-3 easy, 3-5 medium, 5-7 medium-hard, 7-10 hard/expert; ~2.6 slide moves per "
                   f"difficulty point is typical).\n\nBrief: {brief}"}], BriefSpec, effort="low")
    report["spec"] = spec.model_dump()
    log(f"[ai] spec: {spec.model_dump()}")

    messages = [{"role": "user", "content":
                 f"Brief: {brief}\nTarget spec: {spec.model_dump_json()}\n\n"
                 f"Propose {variants} different layout variants that meet the spec. Give each a short "
                 "evocative name and a one-sentence idea."}]
    accepted: list[tuple[Verdict, str]] = []
    near_misses: list[Verdict] = []
    for rnd in range(1, rounds + 1):
        content, out = _ask(client, messages, Variants)
        verdicts = [check_variant(v, spec) for v in out.variants]
        report["rounds"].append([{"name": v.name, "ok": vd.ok, "reasons": vd.reasons,
                                  "min_moves": vd.metrics.get("min_moves")}
                                 for v, vd in zip(out.variants, verdicts)])
        for v, vd in zip(out.variants, verdicts):
            log(f"[ai] round {rnd} {v.name!r}: {'accepted' if vd.ok else 'rejected - ' + '; '.join(vd.reasons)}")
            if vd.ok:
                accepted.append((vd, v.idea))
            elif vd.metrics:
                near_misses.append(vd)
        if len(accepted) >= count:
            break
        messages += [{"role": "assistant", "content": content},
                     {"role": "user", "content": feedback_text(out.variants, verdicts)}]

    results: list[GeneratedLevel] = [GeneratedLevel(vd.level, vd.metrics, vd.solution, {}, "ai")
                                     for vd, _ in accepted[:count]]
    # last resort: solver-assisted repair of solvable near misses
    for vd in near_misses:
        if len(results) >= count:
            break
        r = retarget(vd.level, spec)
        if r:
            lv, m = r
            if not spec.exit_truck or _has_exit_truck(lv):
                results.append(GeneratedLevel(lv, m, solve(lv).path, {}, "ai+solver-retarget"))
                log(f"[ai] retargeted {lv.name!r} to {m['min_moves']} moves / difficulty {m['difficulty']}")
    if len(results) < count:
        log(f"[ai] only {len(results)} AI levels passed; topping up procedurally")
        extra, _ = procedural_from_brief(brief, count - len(results), log, seed, spec=spec, with_notes=False)
        results += extra

    write_notes(client, brief, results)
    for gl in results:
        gl.level.meta = {"source": gl.source, "brief": brief}
    report["accepted"] = len(results)
    return results, report


def write_notes(client, brief: str, results: list[GeneratedLevel]) -> None:
    """One Claude call writes a designer's note for every level (in place)."""
    payload = []
    for gl in results:
        payload.append(f"## {gl.level.name}\n{_ascii(gl.level)}\nmetrics: {json.dumps(gl.metrics)}\n"
                       f"optimal solution: {' '.join(m['id'] + m['dir'][0].upper() + str(m['steps']) for m in gl.solution)}")
    _, notes = _ask(client, [{"role": "user", "content":
                    f"Brief: {brief}\n\nThese levels passed the solver. For each, write a short designer's "
                    "note (2-3 sentences each field): why it works, and what it teaches the player. Refer "
                    "to concrete vehicles and the key insight of the optimal solution. Use the level names "
                    "exactly as given.\n\n" + "\n\n".join(payload)}],
                    Notes, effort="medium")
    by_name = {n.name: n for n in notes.notes}
    for i, gl in enumerate(results):
        n = by_name.get(gl.level.name) or (notes.notes[i] if i < len(notes.notes) else None)
        gl.note = n.model_dump() if n else template_note(gl.level, gl.metrics, gl.solution)


# ---------------------------------------------------------------- fallback path
def template_note(level: Level, m: dict, solution: list) -> dict:
    first = solution[0] if solution else None
    red_moves = sum(1 for s in solution if s["id"] == "R")
    why = (f"{m['min_moves']} moves with {m['blockers']} vehicles that must move before the red car; "
           f"{m['direct_blockers']} sit directly in the exit lane. About {round(m['dead_end_ratio'] * 100)}% "
           "of the moves along the solution make it longer, so it rewards thinking before sliding.")
    teach = ("Clear the blockers of the blockers first: " if m["blockers"] > m["direct_blockers"] else
             "Read the exit lane and clear it directly: ")
    if first:
        teach += f"the opening move is {first['id']} {first['dir']}"
    teach += (", and the red car repositions mid-solution." if red_moves > 1 else ".")
    if m["trucks"]:
        teach += f" Features {m['trucks']} truck(s), which need 3 free cells to clear a lane."
    return {"name": level.name, "why_it_works": why, "what_it_teaches": teach}


def procedural_from_brief(brief: str, count: int, log=print, seed: int | None = None,
                          spec: BriefSpec | None = None, with_notes: bool = True):
    spec = spec or parse_brief_local(brief)
    c = spec_to_constraints(spec)
    log(f"[procedural] constraints: {c.describe()}")
    rng = random.Random(seed)
    out: list[GeneratedLevel] = []
    base = f"Level {spec.level_number}" if spec.level_number else "Generated"
    for i in range(count):
        r = generate(c, rng, name=f"{base}{'' if count == 1 else chr(ord('a') + i)}")
        if r is None:
            log("[procedural] no level met the constraints, widening difficulty band")
            c.difficulty = (c.difficulty[0] - 1, c.difficulty[1] + 1)
            r = generate(c, rng, name=f"{base}{chr(ord('a') + i)}")
            if r is None:
                continue
        lv, m = r
        sol = solve(lv).path
        out.append(GeneratedLevel(lv, m, sol, template_note(lv, m, sol) if with_notes else {}, "procedural"))
        log(f"[procedural] {lv.name}: {m['min_moves']} moves, difficulty {m['difficulty']}")
    return out, {"mode": "procedural", "spec": spec.model_dump()}
