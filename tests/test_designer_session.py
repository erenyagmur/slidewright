import json

from designer_session import check_round, finalize

SPEC = {"brief": "tiny test", "level_number": 1, "difficulty_min": 1.0, "difficulty_max": 10.0,
        "target_moves": 3, "moves_tolerance": 1, "trucks_min": 0, "trucks_max": 3,
        "exit_truck": False, "mechanic": "test"}
GOOD = [{"id": "R", "x": 0, "y": 2, "length": 2, "orientation": "H"},
        {"id": "A", "x": 4, "y": 0, "length": 3, "orientation": "V"},
        {"id": "B", "x": 4, "y": 5, "length": 2, "orientation": "H"}]
SHORT = [{"id": "R", "x": 0, "y": 2, "length": 2, "orientation": "H"}]


def test_check_round_and_finalize(tmp_path):
    (tmp_path / "spec.json").write_text(json.dumps(SPEC))
    (tmp_path / "round1.json").write_text(json.dumps({"variants": [
        {"name": "Short", "idea": "i", "vehicles": SHORT},
        {"name": "Chain", "idea": "B then A then R", "vehicles": GOOD}]}))
    text, verdicts = check_round(tmp_path, tmp_path / "round1.json")
    assert [v.ok for v in verdicts] == [False, True]
    assert "optimal solution is 1 moves" in text and "optimal line: B left 2" in text
    assert (tmp_path / "round1_feedback.txt").exists()

    (tmp_path / "notes.json").write_text(json.dumps({"notes": [
        {"name": "Chain", "why_it_works": "w", "what_it_teaches": "t"}]}))
    pack = json.loads(finalize(tmp_path, players=10).read_text(encoding="utf-8"))
    assert len(pack["levels"]) == 1
    e = pack["levels"][0]
    assert e["note"]["why_it_works"] == "w" and e["metrics"]["min_moves"] == 3 and "win_rate" in e["playtest"]
    assert "Solver feedback" in (tmp_path / "session_log.md").read_text(encoding="utf-8")
