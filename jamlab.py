"""Jam Lab command-line interface.

  python jamlab.py solve levels/example.json
  python jamlab.py analyze levels/example.json --playtest
  python jamlab.py random --difficulty 5-7 --trucks 1-2 --min-moves 10 --count 3
  python jamlab.py generate --brief "level 12, medium-hard, introduce trucks blocking the exit row, about 15 moves"
  python jamlab.py pack --count 20
  python jamlab.py view
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _range(s: str, cast=float):
    a, _, b = s.partition("-")
    return cast(a), cast(b or a)


def _fmt_path(path: list[dict]) -> str:
    return " ".join(f"{m['id']}{'→' if m['dir'] == 'right' else '←' if m['dir'] == 'left' else '↓' if m['dir'] == 'down' else '↑'}{m['steps']}"
                    for m in path)


def cmd_solve(a):
    from solver import Level, solve
    lv = Level.load(a.level)
    print(lv.ascii(), "\n")
    t = time.perf_counter()
    r = solve(lv)
    if not r.solvable:
        print(f"UNSOLVABLE ({r.states_explored} states explored)")
        return 1
    print(f"solvable: {r.min_moves} moves  ({r.states_explored} states explored, {1000 * (time.perf_counter() - t):.0f} ms)")
    print("solution:", _fmt_path(r.path))
    if a.json:
        print(json.dumps(r.to_dict(), indent=2))


def cmd_analyze(a):
    from metrics import compute_metrics, normalise, WEIGHTS
    from playtest import PlaytestConfig, playtest
    from solver import Level
    lv = Level.load(a.level)
    print(lv.ascii(), "\n")
    m = compute_metrics(lv)
    if not m["solvable"]:
        print("UNSOLVABLE")
        return 1
    n = normalise(m)
    for k, v in m.items():
        print(f"  {k:<18} {v}")
    print("\n  score breakdown: " + ", ".join(f"{k} {n[k]:.2f}×{w}" for k, w in WEIGHTS.items()))
    if a.playtest:
        p = playtest(lv, PlaytestConfig(players=a.players))
        print(f"\n  playtest ({p['players']} simulated players, move limit {p['move_limit']}):")
        for k in ("win_rate", "first_try_win_rate", "clear_rate", "avg_attempts", "churn_risk", "avg_moves_when_won"):
            print(f"  {k:<18} {p[k]}")


def cmd_random(a):
    from generator import Constraints, generate
    c = Constraints(difficulty=_range(a.difficulty), min_moves=a.min_moves, max_moves=a.max_moves,
                    trucks=_range(a.trucks, int), vehicles=_range(a.vehicles, int), exit_truck=a.exit_truck)
    rng = random.Random(a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for i in range(a.count):
        r = generate(c, rng, name=f"random_{i + 1}")
        if not r:
            print("no level met the constraints; try a wider range")
            return 1
        lv, m = r
        p = out / f"random_{i + 1}.json"
        lv.meta["metrics"] = m
        p.write_text(json.dumps(lv.to_dict(), indent=2))
        print(f"{p}: {m['min_moves']} moves, difficulty {m['difficulty']}, trucks {m['trucks']}\n{lv.ascii()}\n")


def cmd_generate(a):
    from ai_generator import ai_generate
    levels, report = ai_generate(a.brief, count=a.count, variants=a.variants, rounds=a.rounds, seed=a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pack = {"name": "Generated from brief", "brief": a.brief, "report": report, "levels": []}
    for i, gl in enumerate(levels, 1):
        print(f"\n=== {gl.level.name}  [{gl.source}]  {gl.metrics['min_moves']} moves, difficulty {gl.metrics['difficulty']}")
        print(gl.level.ascii())
        print("solution:", _fmt_path(gl.solution))
        print("why it works:   ", gl.note.get("why_it_works"))
        print("what it teaches:", gl.note.get("what_it_teaches"))
        pack["levels"].append({"index": i, "name": gl.level.name or f"Level {i}", "source": gl.source,
                               "level": gl.level.to_dict(), "metrics": gl.metrics, "solution": gl.solution,
                               "note": gl.note, "target_difficulty": None})
    p = out / "generated.json"
    p.write_text(json.dumps(pack, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nsaved {len(levels)} level(s) to {p} (open it in viewer.html)")


def cmd_pack(a):
    from pack_builder import build_pack, plot_curve, save_pack
    t = time.time()
    pack = build_pack(count=a.count, seed=a.seed, mode=a.mode, players=a.players)
    save_pack(pack, a.out)
    plot_curve(pack, a.chart)
    print(f"\nwrote {a.out} and {a.chart} in {time.time() - t:.0f}s")


def cmd_check(a):
    from designer_session import check_round
    text, verdicts = check_round(a.session, a.variants)
    print(text)
    print(f"\n{sum(v.ok for v in verdicts)}/{len(verdicts)} accepted; report saved next to {a.variants}")


def cmd_finalize(a):
    from designer_session import finalize
    out = finalize(a.session, players=a.players)
    print(f"wrote {out} and {Path(a.session) / 'session_log.md'} (open the pack in viewer.html?pack={out.as_posix()})")


def cmd_view(a):
    import http.server
    import functools
    import webbrowser
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), handler)
    url = f"http://127.0.0.1:{a.port}/viewer.html"
    print(f"serving {ROOT} at {url}  (Ctrl+C to stop)")
    webbrowser.open(url)
    srv.serve_forever()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jamlab", description="AI-assisted level design for car-escape puzzles")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("solve", help="solve a level JSON")
    s.add_argument("level")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_solve)

    s = sub.add_parser("analyze", help="difficulty metrics (and optional playtest) for a level")
    s.add_argument("level")
    s.add_argument("--playtest", action="store_true")
    s.add_argument("--players", type=int, default=200)
    s.set_defaults(fn=cmd_analyze)

    s = sub.add_parser("random", help="procedural generation with constraints")
    s.add_argument("--difficulty", default="3-6", help="e.g. 4.5-6")
    s.add_argument("--trucks", default="0-2")
    s.add_argument("--vehicles", default="6-11")
    s.add_argument("--min-moves", type=int, default=1)
    s.add_argument("--max-moves", type=int, default=60)
    s.add_argument("--exit-truck", action="store_true", help="a vertical truck must block the exit row")
    s.add_argument("--count", type=int, default=1)
    s.add_argument("--seed", type=int)
    s.add_argument("--out", default="output/random")
    s.set_defaults(fn=cmd_random)

    s = sub.add_parser("generate", help="AI generation from a natural-language brief")
    s.add_argument("--brief", required=True)
    s.add_argument("--count", type=int, default=2)
    s.add_argument("--variants", type=int, default=4)
    s.add_argument("--rounds", type=int, default=3)
    s.add_argument("--seed", type=int)
    s.add_argument("--out", default="output")
    s.set_defaults(fn=cmd_generate)

    s = sub.add_parser("pack", help="build a level pack with a difficulty curve")
    s.add_argument("--count", type=int, default=20)
    s.add_argument("--seed", type=int, default=2026)
    s.add_argument("--players", type=int, default=200)
    s.add_argument("--mode", choices=["auto", "ai", "procedural"], default="auto",
                   help="auto = Claude if ANTHROPIC_API_KEY is set, else procedural")
    s.add_argument("--out", default="output/pack.json")
    s.add_argument("--chart", default="output/difficulty_curve.png")
    s.set_defaults(fn=cmd_pack)

    s = sub.add_parser("check", help="validate a round of proposed layouts (file-based designer loop, no API key)")
    s.add_argument("--session", required=True, help="folder holding spec.json")
    s.add_argument("--variants", required=True, help="round file with proposed layouts")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("finalize", help="playtest accepted layouts, attach notes.json, write pack.json + log")
    s.add_argument("--session", required=True)
    s.add_argument("--players", type=int, default=200)
    s.set_defaults(fn=cmd_finalize)

    s = sub.add_parser("view", help="serve viewer.html locally")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(fn=cmd_view)

    a = ap.parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
