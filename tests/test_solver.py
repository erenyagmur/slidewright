import pytest

from solver import Board, Level, Vehicle, explore, solve


def lvl(*vs):
    return Level([Vehicle(*v) for v in vs])


RED0 = ("R", 0, 2, 2, "H")


# ---------------- validation ----------------

def test_valid_level_has_no_errors():
    assert lvl(RED0, ("A", 3, 0, 3, "V")).validate() == []


@pytest.mark.parametrize("vehicles, fragment", [
    ([("R", 0, 1, 2, "H")], "exit row"),
    ([("R", 0, 2, 2, "V")], "horizontal"),
    ([("A", 0, 0, 2, "H")], "exactly one red"),
    ([RED0, ("A", 1, 1, 2, "V")], "overlaps"),
    ([RED0, ("A", 5, 4, 3, "V")], "off the board"),
    ([RED0, ("A", 0, 0, 4, "H")], "length"),
])
def test_illegal_levels_are_reported(vehicles, fragment):
    errors = lvl(*vehicles).validate()
    assert any(fragment in e for e in errors), errors


def test_board_refuses_illegal_level():
    with pytest.raises(ValueError):
        Board(lvl(RED0, ("A", 1, 2, 2, "H")))


# ---------------- move rules ----------------

def moves_of(board, vid):
    i = board.ids.index(vid)
    return sorted(p for j, p, _ in board.moves(board.start) if j == i)


def test_vehicle_slides_only_along_its_axis_until_wall():
    b = Board(lvl(RED0))
    assert moves_of(b, "R") == [1, 2, 3, 4]  # x positions only, y never changes


def test_vertical_vehicle_moves_in_y():
    b = Board(lvl(RED0, ("A", 5, 0, 2, "V")))
    assert moves_of(b, "A") == [1, 2, 3, 4]


def test_vehicles_cannot_pass_through_each_other():
    # A blocks R at x=3; R can reach x=1 only (cells 1,2), never jump past A.
    b = Board(lvl(RED0, ("A", 3, 1, 3, "V")))
    assert moves_of(b, "R") == [1]


def test_blocked_vehicle_has_no_moves():
    # two vertical trucks fill the whole right column: neither can move
    b = Board(lvl(RED0, ("A", 5, 0, 3, "V"), ("C", 5, 3, 3, "V")))
    assert moves_of(b, "A") == []
    assert moves_of(b, "C") == []


def test_one_slide_can_cover_several_cells_as_one_move():
    r = solve(lvl(RED0))
    assert r.min_moves == 1
    assert r.path == [{"id": "R", "from": 0, "to": 4, "dir": "right", "steps": 4}]


# ---------------- solver ----------------

def test_already_solved():
    r = solve(lvl(("R", 4, 2, 2, "H")))
    assert r.solvable and r.min_moves == 0 and r.path == []


def test_single_blocker():
    r = solve(lvl(RED0, ("A", 3, 1, 2, "V")))
    assert r.solvable and r.min_moves == 2
    assert r.path[0]["id"] == "A" and r.path[-1]["id"] == "R"


def test_chained_blockers():
    # truck A blocks the exit row and can only clear it by moving down,
    # which needs car B (bottom row) to slide two cells left first.
    r = solve(lvl(RED0, ("A", 4, 0, 3, "V"), ("B", 4, 5, 2, "H")))
    assert r.min_moves == 3
    assert [m["id"] for m in r.path] == ["B", "A", "R"]


def test_unsolvable_when_horizontal_car_sits_in_exit_lane():
    r = solve(lvl(RED0, ("X", 4, 2, 2, "H")))
    assert not r.solvable and r.min_moves is None and r.path == []


def replay(level, path):
    """Apply a solution path through the public move generator."""
    board = Board(level)
    state = board.start
    for m in path:
        i = board.ids.index(m["id"])
        assert state[i] == m["from"]
        legal = {(j, p): n for j, p, n in board.moves(state)}
        assert (i, m["to"]) in legal, f"illegal move {m}"
        state = legal[(i, m["to"])]
    return board.is_goal(state)


def test_solution_path_is_legal_and_reaches_goal():
    level = lvl(RED0, ("A", 2, 0, 3, "V"), ("B", 3, 3, 3, "V"), ("C", 4, 1, 2, "V"),
                ("D", 0, 5, 2, "H"), ("E", 4, 5, 2, "H"), ("F", 3, 0, 3, "H"))
    r = solve(level)
    assert r.solvable
    assert replay(level, r.path)


def test_bfs_is_optimal_against_full_graph():
    level = lvl(RED0, ("A", 2, 0, 3, "V"), ("B", 3, 3, 3, "V"), ("C", 4, 1, 2, "V"),
                ("D", 0, 5, 2, "H"), ("E", 4, 5, 2, "H"), ("F", 3, 0, 3, "H"))
    g = explore(Board(level))
    assert g.solvable
    assert solve(level).min_moves == g.min_moves


def test_json_roundtrip():
    level = lvl(RED0, ("A", 3, 0, 3, "V"))
    again = Level.from_dict(level.to_dict())
    assert again.vehicles == level.vehicles and again.exit_row == 2
