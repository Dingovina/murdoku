"""Stage-5 end-to-end tests: REAL generator -> API -> solver-simulated client.

Unlike ``test_server.py`` (which drives ``GET /api/puzzle`` through the
stubbed ``murdoku.generator`` seam), these tests exercise the whole pipeline:
the production generator builds the puzzle, the token payload is decoded and
cross-checked against the solver's own solution (derived from the clues
alone), and ``POST /api/check`` is driven the way the frontend drives it.

``MURDOKU_SECRET`` is set before the server module import: tokens here must
be deterministic, ``MURDOKU_DEV`` is deliberately not used.
"""

import os
import sys
import types

os.environ["MURDOKU_SECRET"] = "e2e-suite-secret"  # must precede app import

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from murdoku import solver  # noqa: E402
from murdoku.model import Puzzle  # noqa: E402
from murdoku.server import tokens  # noqa: E402
from murdoku.server.app import app  # noqa: E402

# SPEC §6 difficulty table with small deterministic seed sets (expert takes
# seconds, so a single seed keeps the whole suite well under a minute).
E2E_MATRIX = [
    ("easy", 1),
    ("easy", 2),
    ("easy", 3),
    ("easy", 4),
    ("easy", 5),
    ("medium", 1),
    ("medium", 2),
    ("medium", 3),
    ("hard", 1),
    ("hard", 2),
    ("expert", 1),
]


def _first_misplaced(order: list[str], placed: dict, solution: dict) -> str:
    """First wrong person in contract order (suspects by number, victim last)."""
    return next(pid for pid in order if placed[pid] != solution[pid])


@pytest.mark.parametrize("difficulty,seed", E2E_MATRIX)
def test_full_stack_pipeline(difficulty: str, seed: int):
    """generator -> /api/puzzle -> solver cross-check -> /api/check outcomes."""
    client = TestClient(app)
    resp = client.get(
        "/api/puzzle", params={"difficulty": difficulty, "seed": seed})
    assert resp.status_code == 200
    body = resp.json()

    # The served puzzle JSON parses strictly and is a valid SPEC §4 puzzle.
    puzzle = Puzzle.from_dict(body["puzzle"])
    puzzle.validate()

    payload = tokens.read_token(body["token"])
    solution = payload["solution"]  # person_id -> [r, c]
    assert payload["difficulty"] == difficulty

    # The clue set is exactly unique, and the hidden solution in the token
    # is THE placement the solver derives from the clues alone.
    assert solver.count_solutions(puzzle, 2) == 1
    (solver_solution,) = solver.solutions(puzzle, 1)
    assert solver_solution == {
        pid: (cell[0], cell[1]) for pid, cell in solution.items()
    }

    # killer_id is the unique suspect in the victim's room (SPEC §3 rule 4).
    victim_room = puzzle.room_of(solver_solution["victim"])
    in_room = [pid for pid in puzzle.suspect_ids()
               if puzzle.room_of(solver_solution[pid]) == victim_room]
    assert len(in_room) == 1, "exactly one suspect shares the victim's room"
    killer_id = in_room[0]
    assert payload["killer_id"] == killer_id

    placements = [
        {"person_id": pid, "r": cell[0], "c": cell[1]}
        for pid, cell in solver_solution.items()
    ]

    # Correct placement + correct accusation -> win with the full solution.
    won = client.post("/api/check", json={
        "token": body["token"],
        "placements": placements,
        "accusation": killer_id,
    })
    assert won.status_code == 200
    assert won.json() == {"won": True, "solution": solution}

    # Swap suspect_1/suspect_2 cells -> exactly one misplaced id, the first
    # wrong person in suspect order, computed here independently.
    swapped = {p["person_id"]: dict(p) for p in placements}
    first, second = swapped["suspect_1"], swapped["suspect_2"]
    first["r"], first["c"], second["r"], second["c"] = \
        second["r"], second["c"], first["r"], first["c"]
    placed = {pid: [p["r"], p["c"]] for pid, p in swapped.items()}
    expected = _first_misplaced(puzzle.people_ids(), placed, solution)
    resp_swapped = client.post("/api/check", json={
        "token": body["token"],
        "placements": list(swapped.values()),
        "accusation": killer_id,
    })
    assert resp_swapped.status_code == 200
    assert resp_swapped.json() == {
        "won": False, "misplaced_person_id": expected}

    # All placements correct + wrong accusation -> explicit no-win branch.
    wrong_accusation = next(
        pid for pid in puzzle.suspect_ids() if pid != killer_id)
    resp_accusation = client.post("/api/check", json={
        "token": body["token"],
        "placements": placements,
        "accusation": wrong_accusation,
    })
    assert resp_accusation.status_code == 200
    assert resp_accusation.json() == {
        "won": False, "correct_accusation": False}

    # Tampered token -> 400, not a game outcome.
    resp_tampered = client.post("/api/check", json={
        "token": body["token"][:-8] + "AAAAAAAA",
        "placements": placements,
        "accusation": killer_id,
    })
    assert resp_tampered.status_code == 400
    assert "error" in resp_tampered.json()


def test_random_seed_with_real_generator():
    """No seed -> a fresh random seed still yields a valid, unique easy puzzle."""
    client = TestClient(app)
    resp = client.get("/api/puzzle", params={"difficulty": "easy"})
    assert resp.status_code == 200
    puzzle = Puzzle.from_dict(resp.json()["puzzle"])
    puzzle.validate()
    payload = tokens.read_token(resp.json()["token"])
    assert payload["difficulty"] == "easy"
    assert solver.count_solutions(puzzle, 2) == 1


def test_generation_error_is_503_json(monkeypatch):
    """The real app seam patched to always raise: retryable 503 with the
    same JSON ``{"error"}`` shape as the 400 paths (not a bare 500)."""
    class Exhausted(RuntimeError):
        pass

    def fail(seed, difficulty):
        raise Exhausted("all outer attempts failed")

    module = types.ModuleType("murdoku.generator")
    module.generate = fail
    module.GenerationError = Exhausted
    monkeypatch.setitem(sys.modules, "murdoku.generator", module)

    client = TestClient(app)
    resp = client.get(
        "/api/puzzle", params={"difficulty": "easy", "seed": 1})
    assert resp.status_code == 503
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert set(body) == {"error"}
    assert isinstance(body["error"], str) and body["error"]
