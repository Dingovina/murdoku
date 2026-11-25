"""Tests for murdoku.clue_truth: the canonical placement evaluator.

Cross-checked against the independent direct-semantics evaluator in
test_clues on generated puzzles (kept clues AND mutated placements), plus
unit coverage of the SPEC §3 rule checks and the alternative-win helpers.
"""

from murdoku.clue_truth import (
    TruthContext,
    placement_satisfies,
    unique_killer,
)
from murdoku.generator import generate
from murdoku.model import Puzzle
from murdoku.solver import solutions
from test_clues import clue_is_true, scenario_puzzle


def _tuples(solution: dict) -> dict:
    """Placement with tuple cells (the clue_truth input convention)."""
    return {pid: tuple(cell) for pid, cell in solution.items()}


def _cross_check_clue_holds(difficulty, seed, placements):
    """clue_holds must agree with the independent evaluator everywhere."""
    result = generate(seed, difficulty)
    puzzle = result.puzzle
    ctx = TruthContext(puzzle)
    for clue in puzzle.clues:
        for name, placement in placements.items():
            got = ctx.clue_holds(clue, placement)
            want = clue_is_true(puzzle, placement, clue)
            assert got == want, (
                f"{difficulty} seed={seed} [{name}] clue={clue}: "
                f"clue_truth={got}, independent={want}")


def _swapped(solution, pid_a, pid_b):
    """Placement with two people's cells exchanged (always stays on valid
    room cells, unlike blind shifts that can land in voids)."""
    out = dict(solution)
    out[pid_a], out[pid_b] = solution[pid_b], solution[pid_a]
    return out


def test_clue_holds_agrees_with_independent_evaluator():
    result = generate(3, "easy")
    solution = _tuples(result.solution)
    _cross_check_clue_holds("easy", 3, {
        "solution": solution,
        "swapped s1/s2": _swapped(solution, "suspect_1", "suspect_2"),
        "swapped s1/victim": _swapped(solution, "suspect_1", "victim"),
    })


def test_clue_holds_agrees_on_hard_puzzle():
    result = generate(1, "hard")
    solution = _tuples(result.solution)
    _cross_check_clue_holds("hard", 1, {
        "solution": solution,
        "swapped s2/s3": _swapped(solution, "suspect_2", "suspect_3"),
        "swapped s1/victim": _swapped(solution, "suspect_1", "victim"),
    })


def test_rules_ok_rejects_bad_placements():
    result = generate(3, "easy")
    puzzle = result.puzzle
    ctx = TruthContext(puzzle)
    good = _tuples(result.solution)
    assert ctx.rules_ok(good)

    # off-field coords: "not ok", never an exception
    off_field = dict(good)
    off_field["suspect_1"] = (-1, 0)
    assert not ctx.rules_ok(off_field)

    # duplicate row (target cell is allowed, so the row rule is the breaker)
    victim_row = good["victim"][0]
    for cell in sorted(puzzle.allowed_cells()):
        if cell[0] == victim_row and cell != good["victim"] \
                and all(cell != good[pid] for pid in puzzle.people_ids()):
            dup_row = dict(good)
            dup_row["suspect_1"] = cell
            assert not ctx.rules_ok(dup_row)
            break
    else:
        raise AssertionError("no duplicate-row probe cell found")


def test_unique_killer_and_placement_satisfies():
    result = generate(3, "easy")
    puzzle = result.puzzle
    solution = _tuples(result.solution)
    killer = unique_killer(puzzle, solution)
    assert killer in puzzle.suspect_ids()
    assert placement_satisfies(puzzle, solution)
    # every solver solution satisfies rules and clues
    for sol in solutions(puzzle, 5):
        assert placement_satisfies(puzzle, _tuples(sol))


def test_unique_killer_requires_exactly_one_suspect_with_victim():
    """Synthetic 3x3 scenario: 0 or 2 suspects in the victim's room -> None."""
    puzzle = scenario_puzzle()  # room 1: (0,0),(0,1),(1,0),(1,1); room 3: row 2
    # victim in room 1, both suspects in room 3 -> nobody with the victim
    alone = {"suspect_1": (2, 0), "suspect_2": (2, 2), "victim": (0, 0)}
    assert unique_killer(puzzle, alone) is None
    # victim in room 1 with BOTH suspects -> ambiguous
    crowded = {"suspect_1": (1, 1), "suspect_2": (0, 1), "victim": (0, 0)}
    assert unique_killer(puzzle, crowded) is None
    # victim in room 1 with exactly suspect_1 -> suspect_1
    clean = {"suspect_1": (1, 1), "suspect_2": (2, 2), "victim": (0, 0)}
    assert unique_killer(puzzle, clean) == "suspect_1"


def test_from_dict_roundtrip_matches_evaluation():
    """The token-embedded puzzle dict evaluates identically after from_dict."""
    result = generate(3, "easy")
    restored = Puzzle.from_dict(result.puzzle.to_dict())
    solution = _tuples(result.solution)
    assert placement_satisfies(restored, solution)
    assert unique_killer(restored, solution) == unique_killer(result.puzzle, solution)
