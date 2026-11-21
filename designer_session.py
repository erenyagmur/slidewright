"""File-based designer loop: the "AI proposes, solver verifies" pipeline without an API key.

A session folder holds the same artefacts the API path exchanges with Claude:

  spec.json             BriefSpec  (brief -> target spec)
  round1.json ...       Variants   (proposed layouts)
  round1_feedback.txt   solver report, identical to what ai_generator sends back to the model
  accepted.json         levels that passed, accumulated across rounds
  notes.json            Notes      (designer's note per accepted level)
  pack.json             final levels with metrics, playtests and notes (open in viewer.html)
  session_log.md        human-readable record of every round

Whoever writes the round files (a designer, or Claude in a chat session) plays
the model's role; the validation is the exact code used by ai_generator.
"""
from __future__ import annotations

import json
from pathlib import Path

from ai_generator import BriefSpec, Notes, Variants, check_variant, feedback_text
from playtest import PlaytestConfig, playtest
from solver import Level


def _load(path: Path, model):
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def check_round(session: str | Path, round_file: str | Path) -> tuple[str, list]:
    session = Path(session)
    round_file = Path(round_file)
    spec = _load(session / "spec.json", BriefSpec)
    variants = _load(round_file, Variants)
    verdicts = [check_variant(v, spec) for v in variants.variants]
    text = feedback_text(variants.variants, verdicts)
    (session / f"{round_file.stem}_feedback.txt").write_text(text, encoding="utf-8")

    acc_path = session / "accepted.json"
    accepted = json.loads(acc_path.read_text(encoding="utf-8")) if acc_path.exists() else []
    names = {a["level"]["name"] for a in accepted}
    for v, vd in zip(variants.variants, verdicts):
        if vd.ok and v.name not in names:
            accepted.append({"round": round_file.stem, "idea": v.idea, "level": vd.level.to_dict(),
                             "metrics": vd.metrics, "solution": vd.solution})
    acc_path.write_text(json.dumps(accepted, indent=2, ensure_ascii=False), encoding="utf-8")
    return text, verdicts


def finalize(session: str | Path, players: int = 200) -> Path:
    session = Path(session)
    spec = _load(session / "spec.json", BriefSpec)
    accepted = json.loads((session / "accepted.json").read_text(encoding="utf-8"))
    notes = {n.name: n.model_dump() for n in _load(session / "notes.json", Notes).notes}
    brief = json.loads((session / "spec.json").read_text(encoding="utf-8")).get("brief", spec.mechanic)
    levels = []
    for i, a in enumerate(accepted, 1):
        lv = Level.from_dict(a["level"])
        lv.meta = {"source": "claude (in-session)", "brief": brief}
        pt = playtest(lv, PlaytestConfig(players=players, seed=100 + i))
        pt.pop("config", None)
        levels.append({
            "index": i, "name": lv.name, "source": "claude (in-session)", "role": a["round"],
            "mechanic": a["idea"], "target_difficulty": round((spec.difficulty_min + spec.difficulty_max) / 2, 2),
            "level": lv.to_dict(), "metrics": a["metrics"], "playtest": pt, "solution": a["solution"],
            "note": notes.get(lv.name, {}),
        })
    pack = {"name": "Claude design session", "brief": brief, "spec": spec.model_dump(), "levels": levels}
    out = session / "pack.json"
    out.write_text(json.dumps(pack, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_log(session, brief, spec, levels)
    return out


def _write_log(session: Path, brief: str, spec: BriefSpec, levels: list) -> None:
    lines = [f"# Design session\n\n**Brief:** {brief}\n", "**Spec:**", "```json",
             spec.model_dump_json(indent=2), "```\n"]
    for rf in sorted(session.glob("round*.json"), key=lambda p: int(p.stem[5:])):
        if rf.stem.endswith("_feedback"):
            continue
        variants = _load(rf, Variants)
        lines.append(f"## {rf.stem}: proposals\n")
        for v in variants.variants:
            lines.append(f"- **{v.name}**: {v.idea}")
        fb = session / f"{rf.stem}_feedback.txt"
        if fb.exists():
            lines += ["", "Solver feedback:", "```", fb.read_text(encoding="utf-8").strip(), "```", ""]
    lines.append("## Accepted levels\n")
    for e in levels:
        m, p, n = e["metrics"], e["playtest"], e["note"]
        lines += [f"### {e['name']}", "```", Level.from_dict(e["level"]).ascii(), "```",
                  f"{m['min_moves']} moves · difficulty {m['difficulty']} · {m['blockers']} blockers · "
                  f"win rate {p['win_rate']:.0%} · churn risk {p['churn_risk']:.0%}", "",
                  f"*Why it works:* {n.get('why_it_works', '')}", "",
                  f"*What it teaches:* {n.get('what_it_teaches', '')}", ""]
    (session / "session_log.md").write_text("\n".join(lines), encoding="utf-8")
