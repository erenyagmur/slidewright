import random

from generator import Constraints, generate
from metrics import compute_metrics
from playtest import PlaytestConfig, playtest
from solver import Level, Vehicle, solve


def lvl(*vs):
    return Level([Vehicle(*v) for v in vs])


EASY = lvl(("R", 0, 2, 2, "H"), ("A", 3, 1, 2, "V"))
CHAIN = lvl(("R", 0, 2, 2, "H"), ("A", 4, 0, 3, "V"), ("B", 4, 5, 2, "H"))


def test_metrics_basic_fields():
    m = compute_metrics(CHAIN)
    assert m["solvable"] and m["min_moves"] == 3
    assert m["blockers"] == 2           # B and A move before R
    assert m["direct_blockers"] == 1    # only A sits in the lane
    assert 1 <= m["difficulty"] <= 10
    assert 0 <= m["dead_end_ratio"] <= 1


def test_unsolvable_metrics():
    assert compute_metrics(lvl(("R", 0, 2, 2, "H"), ("X", 4, 2, 2, "H"))) == {"solvable": False}


def test_harder_level_scores_higher():
    hard = generate(Constraints(min_moves=14, max_moves=30, vehicles=(9, 12), trucks=(1, 3)),
                    random.Random(5))
    assert hard is not None
    assert hard[1]["difficulty"] > compute_metrics(EASY)["difficulty"] + 3


def test_playtest_trivial_level_always_won():
    p = playtest(EASY, PlaytestConfig(players=30))
    assert p["win_rate"] == 1.0 and p["churn_risk"] == 0.0 and p["avg_attempts"] == 1.0


def test_playtest_is_deterministic_with_seed():
    a = playtest(CHAIN, PlaytestConfig(players=20, seed=3))
    b = playtest(CHAIN, PlaytestConfig(players=20, seed=3))
    assert a == b


def test_generator_respects_constraints():
    c = Constraints(difficulty=(3, 6), min_moves=5, max_moves=12, trucks=(1, 2),
                    vehicles=(6, 9), exit_truck=True)
    out = generate(c, random.Random(11))
    assert out is not None
    level, m = out
    assert level.validate() == []
    assert 3 <= m["difficulty"] <= 6 and 5 <= m["min_moves"] <= 12
    assert 1 <= m["trucks"] <= 2
    assert solve(level).min_moves == m["min_moves"]
