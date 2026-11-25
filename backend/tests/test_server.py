"""Tests for murdoku.server.app (stage 3), independent of the stage-2
generator: /api/puzzle runs against a stub module injected into
``sys.modules["murdoku.generator"]`` (the deferred-import seam).
"""

import json
import re
import sys
import types
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from murdoku.clue_truth import unique_killer
from murdoku.generator import generate
from murdoku.model import Person, Puzzle, Room
from murdoku.server import tokens
from murdoku.server.app import app
from murdoku import solver


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _secret_env(monkeypatch):
    """Deterministic token env for every test (tests may override)."""
    monkeypatch.setenv(tokens.SECRET_ENV, "unit-test-secret")
    monkeypatch.delenv(tokens.DEV_ENV, raising=False)


def _build_puzzle() -> Puzzle:
    """3x3 board, two rooms, two suspects + victim (no objects, no clues).

    The murder-room rule is satisfiable (verified below), so the solver
    finds at least one placement; clues are not needed for API tests.
    """
    room1 = Room(1, frozenset({(0, 0), (0, 1), (1, 0)}))
    room2 = Room(
        2,
        frozenset({(0, 2), (1, 1), (1, 2), (2, 0), (2, 1), (2, 2)}),
    )
    people = (
        Person("suspect_1", "Подозреваемый_1", 1),
        Person("suspect_2", "Подозреваемый_2", 2),
        Person("victim", "Убитый", 3),
    )
    puzzle = Puzzle(3, 3, (room1, room2), (), people, ())
    puzzle.validate()
    return puzzle


@pytest.fixture(scope="module")
def puzzle() -> Puzzle:
    return _build_puzzle()


@pytest.fixture(scope="module")
def solution(puzzle) -> dict[str, tuple[int, int]]:
    (solution,) = list(solver.solutions(puzzle, 1))
    return solution


@pytest.fixture(scope="module")
def killer_id(puzzle, solution) -> str:
    """Independently recomputed: the only suspect in the victim's room."""
    victim_room = puzzle.room_of(solution["victim"])
    suspects = [
        pid
        for pid in puzzle.suspect_ids()
        if puzzle.room_of(solution[pid]) == victim_room
    ]
    assert len(suspects) == 1, "fixture puzzle must have a murder room"
    return suspects[0]


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def stub_generator(monkeypatch, puzzle, solution) -> list[dict]:
    """The stage-2 seam: a fake ``murdoku.generator`` module."""
    calls: list[dict] = []

    def fake_generate(seed, difficulty):
        calls.append({"seed": seed, "difficulty": difficulty})
        return SimpleNamespace(puzzle=puzzle, solution=solution)

    module = types.ModuleType("murdoku.generator")
    module.generate = fake_generate
    module.GenerationError = type("GenerationError", (RuntimeError,), {})
    monkeypatch.setitem(sys.modules, "murdoku.generator", module)
    return calls


def _token_for(solution: dict, killer_id: str) -> str:
    payload = {
        "game_id": "0" * 32,
        "difficulty": "medium",
        "solution": {pid: [r, c] for pid, (r, c) in solution.items()},
        "killer_id": killer_id,
    }
    return tokens.make_token(payload)


@pytest.fixture()
def token(solution, killer_id) -> str:
    return _token_for(solution, killer_id)


def _placements(solution: dict) -> list[dict]:
    return [
        {"person_id": pid, "r": r, "c": c}
        for pid, (r, c) in solution.items()
    ]


def _with_moved(solution: dict, *pids: str) -> list[dict]:
    """Placements with the given people shifted one row off their solution."""
    placements = _placements(solution)
    for placement in placements:
        if placement["person_id"] in pids:
            placement["r"] += 1
    return placements


# ----------------------------------------------------------------------
# GET /api/puzzle
# ----------------------------------------------------------------------


def test_puzzle_happy_path(client, stub_generator, puzzle, solution,
                           killer_id):
    response = client.get(
        "/api/puzzle", params={"difficulty": "easy", "seed": 42})
    assert response.status_code == 200
    assert stub_generator == [{"seed": 42, "difficulty": "easy"}]

    body = response.json()
    assert body["puzzle"] == puzzle.to_dict()

    payload = tokens.read_token(body["token"])
    assert re.fullmatch(r"[0-9a-f]{32}", payload["game_id"])
    assert payload["difficulty"] == "easy"
    assert payload["solution"] == {
        pid: [r, c] for pid, (r, c) in solution.items()
    }
    assert payload["killer_id"] == killer_id


def test_puzzle_default_difficulty_and_random_seed(client, stub_generator):
    response = client.get("/api/puzzle")
    assert response.status_code == 200
    assert len(stub_generator) == 1
    assert stub_generator[0]["difficulty"] == "medium"
    assert isinstance(stub_generator[0]["seed"], int)
    payload = tokens.read_token(response.json()["token"])
    assert payload["difficulty"] == "medium"


def test_puzzle_unknown_difficulty(client, stub_generator):
    response = client.get("/api/puzzle", params={"difficulty": "impossible"})
    assert response.status_code == 400
    assert "error" in response.json()
    assert stub_generator == []


@pytest.mark.parametrize("seed", ["abc", "1.5", "", "42x"])
def test_puzzle_malformed_seed(client, stub_generator, seed):
    response = client.get(
        "/api/puzzle", params={"difficulty": "easy", "seed": seed})
    assert response.status_code == 400
    assert "error" in response.json()
    assert stub_generator == []


def test_puzzle_seed_zero_is_valid(client, stub_generator):
    response = client.get("/api/puzzle", params={"seed": 0})
    assert response.status_code == 200
    assert stub_generator[0]["seed"] == 0


def test_puzzle_generation_error_is_503_json(client, monkeypatch):
    """A seed exhausting the generator's outer attempts (SPEC §6) is a
    retryable server-side failure: 503 with the JSON error shape, not a
    bare 500."""
    generation_error = type("GenerationError", (RuntimeError,), {})
    calls: list[tuple] = []

    def exhausted_generate(seed, difficulty):
        calls.append((seed, difficulty))
        raise generation_error("all outer attempts failed")

    module = types.ModuleType("murdoku.generator")
    module.generate = exhausted_generate
    module.GenerationError = generation_error
    monkeypatch.setitem(sys.modules, "murdoku.generator", module)

    response = client.get(
        "/api/puzzle", params={"difficulty": "hard", "seed": 1})
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"error"}
    assert isinstance(body["error"], str) and body["error"]
    assert calls == [(1, "hard")]


@pytest.fixture()
def failing_generator(monkeypatch):
    """A stub ``murdoku.generator`` whose ``generate`` always raises."""
    generation_error = type("GenerationError", (RuntimeError,), {})
    calls: list[tuple] = []

    def exhausted_generate(seed, difficulty):
        calls.append((seed, difficulty))
        raise generation_error("all outer attempts failed")

    module = types.ModuleType("murdoku.generator")
    module.generate = exhausted_generate
    module.GenerationError = generation_error
    monkeypatch.setitem(sys.modules, "murdoku.generator", module)
    return calls


def test_puzzle_unseeded_retries_then_503(client, failing_generator):
    """Without an explicit seed the server silently re-seeds up to
    GENERATION_RETRIES times; only a full streak of failures is a 503."""
    from murdoku.server.app import GENERATION_RETRIES

    response = client.get("/api/puzzle", params={"difficulty": "hard"})
    assert response.status_code == 503
    assert set(response.json()) == {"error"}
    assert len(failing_generator) == GENERATION_RETRIES
    assert all(difficulty == "hard" for _, difficulty in failing_generator)
    # every retry drew a fresh random seed
    seeds = [seed for seed, _ in failing_generator]
    assert len(set(seeds)) == GENERATION_RETRIES


def test_puzzle_unseeded_succeeds_after_failures(
        client, monkeypatch, puzzle, solution):
    """Unseeded generation succeeds on the attempt after k failures."""
    generation_error = type("GenerationError", (RuntimeError,), {})
    calls: list[tuple] = []
    state = {"failures_left": 2}

    def flaky_generate(seed, difficulty):
        calls.append((seed, difficulty))
        if state["failures_left"] > 0:
            state["failures_left"] -= 1
            raise generation_error("outer attempts failed")
        return SimpleNamespace(puzzle=puzzle, solution=solution)

    module = types.ModuleType("murdoku.generator")
    module.generate = flaky_generate
    module.GenerationError = generation_error
    monkeypatch.setitem(sys.modules, "murdoku.generator", module)

    response = client.get("/api/puzzle", params={"difficulty": "easy"})
    assert response.status_code == 200
    assert len(calls) == 3
    assert len({seed for seed, _ in calls}) == 3
    payload = tokens.read_token(response.json()["token"])
    assert payload["difficulty"] == "easy"


# ----------------------------------------------------------------------
# POST /api/check — 200 outcomes
# ----------------------------------------------------------------------


def test_check_win(client, token, solution, killer_id):
    response = client.post("/api/check", json={
        "token": token,
        "placements": _placements(solution),
        "accusation": killer_id,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["won"] is True
    assert body["solution"] == {
        pid: [r, c] for pid, (r, c) in solution.items()
    }
    assert "misplaced_person_id" not in body
    assert "correct_accusation" not in body


def test_check_extra_fields_ignored(client, token, solution, killer_id):
    response = client.post("/api/check", json={
        "token": token,
        "placements": _placements(solution),
        "accusation": killer_id,
        "extra": "ignored",
    })
    assert response.status_code == 200
    assert response.json()["won"] is True


@pytest.mark.parametrize("pids,expected", [
    (["suspect_1"], "suspect_1"),
    (["suspect_2"], "suspect_2"),
    (["victim"], "victim"),
    (["suspect_2", "victim"], "suspect_2"),        # first in suspect order
    (["suspect_1", "suspect_2"], "suspect_1"),
    (["suspect_1", "victim"], "suspect_1"),
])
def test_check_misplaced_first_in_suspect_order(
        client, token, solution, pids, expected):
    response = client.post("/api/check", json={
        "token": token,
        "placements": _with_moved(solution, *pids),
        "accusation": "suspect_1",  # accusation alone decides nothing here
    })
    assert response.status_code == 200
    assert response.json() == {"won": False, "misplaced_person_id": expected}


def test_check_out_of_field_coords_are_misplaced_not_error(
        client, token, solution):
    placements = _placements(solution)
    placements[0]["r"] = 99
    placements[0]["c"] = 99
    response = client.post("/api/check", json={
        "token": token,
        "placements": placements,
        "accusation": "suspect_1",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["won"] is False
    assert body["misplaced_person_id"] == placements[0]["person_id"]


def test_check_all_correct_but_wrong_accusation(
        client, token, solution, killer_id, puzzle):
    other = [pid for pid in puzzle.suspect_ids() if pid != killer_id][0]
    response = client.post("/api/check", json={
        "token": token,
        "placements": _placements(solution),
        "accusation": other,
    })
    assert response.status_code == 200
    assert response.json() == {"won": False, "correct_accusation": False}


# ----------------------------------------------------------------------
# GET /api/solution — reveal (the player gives up)
# ----------------------------------------------------------------------


def test_solution_reveal(client, token, solution, killer_id):
    response = client.get("/api/solution", params={"token": token})
    assert response.status_code == 200
    body = response.json()
    assert body["solution"] == {
        pid: [r, c] for pid, (r, c) in solution.items()
    }
    assert body["killer_id"] == killer_id


def test_solution_reveal_missing_token(client):
    response = client.get("/api/solution")
    assert response.status_code == 400
    assert "error" in response.json()


def test_solution_reveal_invalid_token(client):
    response = client.get("/api/solution", params={"token": "garbage"})
    assert response.status_code == 400
    assert "error" in response.json()


def test_solution_reveal_token_without_payload_fields(client):
    """A structurally valid token lacking solution/killer_id is rejected."""
    stripped = tokens.make_token({"game_id": "0" * 32})
    response = client.get("/api/solution", params={"token": stripped})
    assert response.status_code == 400
    assert "solution/killer_id" in response.json()["error"]


def test_solution_reveal_token_with_malformed_solution(client):
    """Garbage solution entries in a signed token are rejected, not echoed."""
    malformed = tokens.make_token({
        "game_id": "0" * 32,
        "solution": {"victim": "abc"},
        "killer_id": "suspect_1",
    })
    response = client.get("/api/solution", params={"token": malformed})
    assert response.status_code == 400
    assert "solution/killer_id" in response.json()["error"]


# ----------------------------------------------------------------------
# Alternative-solution validation (ideas.md): a different-but-valid
# placement wins and is logged for generator-bug hunting.
# ----------------------------------------------------------------------


def _alt_scenario():
    """A real generated puzzle, a kept clue whose removal yields exactly
    two solutions, the alternative placement, and a hand-built token whose
    embedded puzzle deliberately lacks that clue (non-unique)."""
    result = generate(2, "easy")
    puzzle, solution = result.puzzle, result.solution
    killer = next(pid for pid in puzzle.suspect_ids()
                  if puzzle.room_of(solution[pid])
                  is puzzle.room_of(solution["victim"]))
    weakened = None
    for clue in puzzle.clues:
        rest = tuple(c for c in puzzle.clues if c != clue)
        probe = Puzzle(puzzle.width, puzzle.height, puzzle.rooms,
                       puzzle.objects, puzzle.people, rest)
        if solver.count_solutions(probe, 3) == 2:
            weakened = probe
            break
    assert weakened is not None, "no kept clue gives exactly two solutions"
    alts = [s for s in solver.solutions(weakened, 2) if s != solution]
    assert len(alts) == 1
    alt = alts[0]

    def token_with(puzzle_to_embed):
        return tokens.make_token({
            "game_id": "0" * 32,
            "difficulty": "easy",
            "seed": 2,
            "solution": {pid: [r, c] for pid, (r, c) in solution.items()},
            "killer_id": killer,
            "puzzle": puzzle_to_embed.to_dict(),
        })

    return solution, killer, alt, weakened, token_with


def _placements_of(placement: dict) -> list[dict]:
    return [{"person_id": pid, "r": r, "c": c}
            for pid, (r, c) in placement.items()]


def test_check_alternative_solution_wins_and_is_logged(client, monkeypatch,
                                                       tmp_path):
    monkeypatch.setenv("MURDOKU_DATA_DIR", str(tmp_path))
    solution, killer, alt, weakened, token_with = _alt_scenario()
    user_killer = unique_killer(weakened, alt)
    assert user_killer is not None

    response = client.post("/api/check", json={
        "token": token_with(weakened),
        "placements": _placements_of(alt),
        "accusation": user_killer,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["won"] is True
    assert body["alternative"] is True
    assert body["solution"] == {pid: [r, c]
                                for pid, (r, c) in solution.items()}

    lines = (tmp_path / "alt_wins.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["seed"] == 2
    assert record["difficulty"] == "easy"
    assert record["clues"] == [dict(c) for c in weakened.clues]
    assert record["user_solution"] == {pid: [r, c]
                                       for pid, (r, c) in alt.items()}
    assert record["server_solution"] == {pid: [r, c]
                                         for pid, (r, c) in solution.items()}
    assert record["accusation"] == user_killer
    assert record["inferred_killer"] == user_killer


def test_check_alternative_valid_but_wrong_accusation(client):
    """A valid alternative arrangement with an accusation that is NOT the
    inferred killer of that arrangement is not a win."""
    solution, killer, alt, weakened, token_with = _alt_scenario()
    user_killer = unique_killer(weakened, alt)
    other = next(pid for pid in weakened.suspect_ids() if pid != user_killer)
    response = client.post("/api/check", json={
        "token": token_with(weakened),
        "placements": _placements_of(alt),
        "accusation": other,
    })
    assert response.status_code == 200
    assert response.json() == {"won": False, "correct_accusation": False}


def test_check_same_alternative_against_full_set_is_misplaced(client):
    """The alternative violates the dropped clue, so against the FULL kept
    set it is just an invalid arrangement -> legacy misplaced response."""
    result = generate(2, "easy")
    puzzle, solution = result.puzzle, result.solution
    killer = next(pid for pid in puzzle.suspect_ids()
                  if puzzle.room_of(solution[pid])
                  is puzzle.room_of(solution["victim"]))
    _, _, alt, _, token_with = _alt_scenario()
    response = client.post("/api/check", json={
        "token": token_with(puzzle),
        "placements": _placements_of(alt),
        "accusation": killer,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["won"] is False
    assert set(body) == {"won", "misplaced_person_id"}


def test_check_token_without_puzzle_keeps_legacy_behavior(client):
    """Old tokens (no embedded puzzle) fall back to exact-match only: the
    alternative arrangement is a plain misplaced response."""
    solution, killer, alt, _, token_with = _alt_scenario()
    legacy = tokens.make_token({
        "game_id": "0" * 32,
        "difficulty": "easy",
        "seed": 2,
        "solution": {pid: [r, c] for pid, (r, c) in solution.items()},
        "killer_id": killer,
    })
    response = client.post("/api/check", json={
        "token": legacy,
        "placements": _placements_of(alt),
        "accusation": "suspect_1",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["won"] is False
    assert set(body) == {"won", "misplaced_person_id"}


# ----------------------------------------------------------------------
# POST /api/check — 400 branches
# ----------------------------------------------------------------------


def test_check_bad_json(client):
    response = client.post(
        "/api/check",
        content=b"{this is not json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    assert "error" in response.json()


@pytest.mark.parametrize("content", [b"[1, 2]", b'"a string"', b"null"])
def test_check_body_not_an_object(client, content):
    response = client.post("/api/check", content=content,
                           headers={"content-type": "application/json"})
    assert response.status_code == 400


@pytest.mark.parametrize("field", ["token", "placements", "accusation"])
def test_check_missing_field(client, token, solution, field):
    body = {
        "token": token,
        "placements": _placements(solution),
        "accusation": "suspect_1",
    }
    del body[field]
    response = client.post("/api/check", json=body)
    assert response.status_code == 400
    assert field in response.json()["error"]


def test_check_invalid_token(client, token, solution):
    response = client.post("/api/check", json={
        "token": token[:-8] + "AAAAAAAA",
        "placements": _placements(solution),
        "accusation": "suspect_1",
    })
    assert response.status_code == 400


def test_check_token_not_a_string(client, solution):
    response = client.post("/api/check", json={
        "token": 12345,
        "placements": _placements(solution),
        "accusation": "suspect_1",
    })
    assert response.status_code == 400


@pytest.mark.parametrize("placements", [
    "not-a-list",
    {},
    [["suspect_1", 0, 0]],
    [{"person_id": "suspect_1", "r": 0}],           # missing c
])
def test_check_malformed_placements(client, token, solution, placements):
    response = client.post("/api/check", json={
        "token": token,
        "placements": placements,
        "accusation": "suspect_1",
    })
    assert response.status_code == 400


@pytest.mark.parametrize("bad_field", ["r", "c"])
@pytest.mark.parametrize("bad_value", ["0", 1.5, True, None])
def test_check_non_integer_coords(client, token, solution, bad_field,
                                  bad_value):
    placements = _placements(solution)
    placements[0][bad_field] = bad_value
    response = client.post("/api/check", json={
        "token": token,
        "placements": placements,
        "accusation": "suspect_1",
    })
    assert response.status_code == 400


def test_check_placements_missing_person(client, token, solution):
    placements = _placements(solution)
    placements = [p for p in placements if p["person_id"] != "victim"]
    response = client.post("/api/check", json={
        "token": token,
        "placements": placements,
        "accusation": "suspect_1",
    })
    assert response.status_code == 400
    assert "victim" in response.json()["error"]


def test_check_placements_duplicate_person(client, token, solution):
    placements = _placements(solution)
    placements = [p for p in placements if p["person_id"] != "suspect_2"]
    placements.append({"person_id": "suspect_1", "r": 0, "c": 0})
    response = client.post("/api/check", json={
        "token": token,
        "placements": placements,
        "accusation": "suspect_1",
    })
    assert response.status_code == 400


def test_check_placements_unknown_person(client, token, solution):
    placements = _placements(solution)
    placements[0] = {"person_id": "suspect_99", "r": 0, "c": 0}
    response = client.post("/api/check", json={
        "token": token,
        "placements": placements,
        "accusation": "suspect_1",
    })
    assert response.status_code == 400


@pytest.mark.parametrize("accusation", [
    "victim",          # the victim can never be the killer
    "suspect_99",      # unknown id
    "",                # empty
    42,                # not a string
    None,              # not a string
])
def test_check_bad_accusation(client, token, solution, accusation):
    response = client.post("/api/check", json={
        "token": token,
        "placements": _placements(solution),
        "accusation": accusation,
    })
    assert response.status_code == 400


# ----------------------------------------------------------------------
# Static frontend
# ----------------------------------------------------------------------


def test_static_index_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_static_js_served(client):
    response = client.get("/js/clues.js")
    assert response.status_code == 200


# ----------------------------------------------------------------------
# __main__ entry point
# ----------------------------------------------------------------------


def _patch_uvicorn_run(monkeypatch):
    import murdoku.server.__main__ as entry

    seen: dict = {}

    def fake_run(app_, host, port):
        seen["app"] = app_
        seen["host"] = host
        seen["port"] = port

    monkeypatch.setattr(entry.uvicorn, "run", fake_run)
    return entry, seen


def test_main_host_port_defaults(monkeypatch):
    entry, seen = _patch_uvicorn_run(monkeypatch)
    monkeypatch.delenv("MURDOKU_HOST", raising=False)
    monkeypatch.delenv("MURDOKU_PORT", raising=False)
    entry.main()
    assert seen["app"] is app
    assert seen["host"] == "127.0.0.1"
    assert seen["port"] == 8000


def test_main_host_port_from_env(monkeypatch):
    entry, seen = _patch_uvicorn_run(monkeypatch)
    monkeypatch.setenv("MURDOKU_HOST", "0.0.0.0")
    monkeypatch.setenv("MURDOKU_PORT", "9999")
    entry.main()
    assert seen["host"] == "0.0.0.0"
    assert seen["port"] == 9999


def test_main_refuses_to_start_without_secret(monkeypatch):
    entry, seen = _patch_uvicorn_run(monkeypatch)
    monkeypatch.delenv(tokens.SECRET_ENV, raising=False)
    monkeypatch.delenv(tokens.DEV_ENV, raising=False)
    with pytest.raises(tokens.MissingSecretError):
        entry.main()
    assert seen == {}  # uvicorn.run never reached


def test_main_starts_in_dev_mode_without_secret(monkeypatch):
    entry, seen = _patch_uvicorn_run(monkeypatch)
    monkeypatch.delenv(tokens.SECRET_ENV, raising=False)
    monkeypatch.setenv(tokens.DEV_ENV, "1")
    monkeypatch.setattr(tokens, "_dev_key", None)
    entry.main()  # must not raise
    assert seen["port"] == 8000
