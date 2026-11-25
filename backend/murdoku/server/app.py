"""Starlette application: puzzle/check API + static frontend (ARCHITECTURE §8).

- ``GET /api/puzzle`` — generate a puzzle (deferred import of
  ``murdoku.generator``, stage 2) and return it with a token carrying the
  solution and the killer id.
- ``POST /api/check`` — stateless check of placements + accusation against
  the token payload.
- ``/`` — the repo-root ``frontend/`` directory as static files.

Monkeypatch seam for tests (generator may not exist yet — stage 2 owns the
module): insert a stub module into ``sys.modules["murdoku.generator"]`` with
``generate(seed, difficulty)`` and ``GenerationError`` attributes, or (once
stage 2 exists) patch ``murdoku.generator.generate`` directly — the handler
re-imports on every request.
"""

import json
import secrets
import uuid
from collections.abc import Iterable
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import tokens

DIFFICULTIES = ("easy", "medium", "hard", "expert")
# Generation attempts for UNSEEDED /api/puzzle requests only; explicit seeds
# are deterministic (SPEC §6/§7) and get exactly one attempt.
GENERATION_RETRIES = 5

# backend/murdoku/server/app.py -> parents[3] == repo root (ARCHITECTURE §8).
FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
if not FRONTEND_DIR.is_dir():
    raise RuntimeError(
        f"frontend directory not found: {FRONTEND_DIR} — the app serves the "
        "repo-root frontend/ at '/', it must exist at startup"
    )


def _error(message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=400)


def _generation_failed(difficulty: str, seed: int | None) -> JSONResponse:
    """503 with the same JSON error shape as the 400 paths (SPEC §7)."""
    suffix = f" with seed {seed}" if seed is not None else ""
    return JSONResponse(
        {
            "error": f"puzzle generation failed for difficulty "
            f"{difficulty!r}{suffix}; try another seed"
        },
        status_code=503,
    )


def _is_int(value: object) -> bool:
    """True for real ints (bool excluded)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _people_order(ids: Iterable[str]) -> list[str]:
    """suspect_1..suspect_N in numeric order, then victim (SPEC §7)."""
    def key(pid: str) -> tuple[int, int]:
        if pid == "victim":
            return (1, 0)
        number = pid.removeprefix("suspect_")
        return (0, int(number) if number.isdigit() else 10**9)

    return sorted(ids, key=key)


def _killer_id(puzzle, solution: dict) -> str:
    """The only suspect in the victim's room (SPEC §3 rule 4)."""
    victim_room = puzzle.room_of(tuple(solution["victim"]))
    for pid in puzzle.suspect_ids():
        if puzzle.room_of(tuple(solution[pid])) == victim_room:
            return pid
    raise RuntimeError(
        "generated solution violates SPEC §3: no suspect in the victim's room"
    )


async def api_puzzle(request: Request) -> JSONResponse:
    """GET /api/puzzle?difficulty={easy|medium|hard|expert}[&seed=N]."""
    difficulty = request.query_params.get("difficulty", "medium")
    if difficulty not in DIFFICULTIES:
        return _error(
            f"unknown difficulty {difficulty!r}, "
            f"expected one of: {', '.join(DIFFICULTIES)}"
        )
    raw_seed = request.query_params.get("seed")
    seeded = raw_seed is not None
    if seeded:
        try:
            seed = int(raw_seed)
        except ValueError:
            return _error(f"bad seed {raw_seed!r}: must be an integer")

    from murdoku.generator import (  # deferred: stage 2 owns the module
        GenerationError,
        generate,
    )

    result = None
    if seeded:
        # Explicit seed: a deterministic contract (SPEC §6/§7) — exactly one
        # attempt, never re-seeded.  A seed can legitimately exhaust the
        # generator's outer attempts (SPEC §6); the client did nothing
        # wrong, so answer 503 (retryable server-side failure) with the same
        # JSON error shape as the 400 paths instead of a bare 500.
        try:
            result = generate(seed, difficulty)
        except GenerationError:
            return _generation_failed(difficulty, seed=seed)
    else:
        # No explicit seed: silently retry with fresh random seeds; only a
        # full streak of failures becomes a 503.
        for _ in range(GENERATION_RETRIES):
            try:
                result = generate(secrets.randbelow(2**32), difficulty)
                break
            except GenerationError:
                continue
        if result is None:
            return _generation_failed(difficulty, seed=None)
    payload = {
        "game_id": uuid.uuid4().hex,
        "difficulty": difficulty,
        "solution": {pid: [r, c] for pid, (r, c) in result.solution.items()},
        "killer_id": _killer_id(result.puzzle, result.solution),
    }
    token = tokens.make_token(payload)
    return JSONResponse({"puzzle": result.puzzle.to_dict(), "token": token})


async def api_check(request: Request) -> JSONResponse:
    """POST /api/check {token, placements, accusation} (SPEC §7 contract)."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _error("request body is not valid JSON")
    if not isinstance(body, dict):
        return _error("request body must be a JSON object")

    for field in ("token", "placements", "accusation"):
        if field not in body:
            return _error(f"missing field: {field}")

    token = body["token"]
    if not isinstance(token, str):
        return _error("token must be a string")
    try:
        payload = tokens.read_token(token)
    except tokens.InvalidToken:
        return _error("invalid token")

    raw_solution = payload.get("solution")
    killer_id = payload.get("killer_id")
    if not isinstance(raw_solution, dict) or not raw_solution:
        return _error("invalid token: solution missing")
    solution: dict[str, list[int]] = {}
    for pid, cell in raw_solution.items():
        if not isinstance(pid, str) \
                or not isinstance(cell, (list, tuple)) or len(cell) != 2 \
                or not _is_int(cell[0]) or not _is_int(cell[1]):
            return _error("invalid token: malformed solution entry")
        solution[pid] = [cell[0], cell[1]]
    people_ids = set(solution)
    suspect_ids = people_ids - {"victim"}

    placements = body["placements"]
    if not isinstance(placements, list):
        return _error("placements must be an array")
    placed: dict[str, list[int]] = {}
    for i, item in enumerate(placements):
        if not isinstance(item, dict):
            return _error(f"placements[{i}] must be an object")
        pid = item.get("person_id")
        r = item.get("r")
        c = item.get("c")
        if not isinstance(pid, str):
            return _error(f"placements[{i}].person_id must be a string")
        if not _is_int(r) or not _is_int(c):
            return _error(f"placements[{i}]: r and c must be integers")
        if pid not in people_ids:
            return _error(f"placements[{i}]: unknown person_id {pid!r}")
        if pid in placed:
            return _error(f"placements: duplicate entry for {pid!r}")
        placed[pid] = [r, c]
    missing = people_ids - set(placed)
    if missing:
        return _error(
            "placements must cover every person exactly once; missing: "
            + ", ".join(_people_order(missing))
        )

    accusation = body["accusation"]
    if not isinstance(accusation, str) or accusation not in suspect_ids:
        return _error(
            "accusation must be one of the suspect ids in the token"
        )

    wrong = [pid for pid in _people_order(people_ids)
             if placed[pid] != solution[pid]]
    if wrong:
        return JSONResponse({"won": False, "misplaced_person_id": wrong[0]})
    if accusation == killer_id:
        return JSONResponse({"won": True, "solution": solution})
    return JSONResponse({"won": False, "correct_accusation": False})


async def api_solution(request: Request) -> JSONResponse:
    """GET /api/solution?token=... — reveal the answer (the player gives up).

    The token is the same anti-cheat token issued by /api/puzzle; the server
    stays stateless.  This is a deliberate surrender: the frontend ends the
    game after calling it.
    """
    token = request.query_params.get("token")
    if not token:
        return _error("missing token")
    try:
        payload = tokens.read_token(token)
    except tokens.InvalidToken:
        return _error("invalid token")
    raw_solution = payload.get("solution")
    killer_id = payload.get("killer_id")
    if not isinstance(raw_solution, dict) or not raw_solution \
            or not isinstance(killer_id, str):
        return _error("invalid token: solution/killer_id missing")
    return JSONResponse({
        "solution": raw_solution,
        "killer_id": killer_id,
    })


routes = [
    Route("/api/puzzle", api_puzzle, methods=["GET"]),
    Route("/api/check", api_check, methods=["POST"]),
    Route("/api/solution", api_solution, methods=["GET"]),
    Mount("/", StaticFiles(directory=FRONTEND_DIR, html=True),
          name="frontend"),
]

app = Starlette(routes=routes)
