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
import os
import secrets
import sys
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .. import clue_truth
from ..model import Puzzle, PuzzleValidationError
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


def _parsed_solution(payload: dict) -> dict[str, list[int]] | None:
    """Validated ``{person_id: [r, c]}`` from a token payload, or None.

    Shared by /api/check and /api/solution so both endpoints reject
    malformed solution entries identically.
    """
    raw_solution = payload.get("solution")
    if not isinstance(raw_solution, dict) or not raw_solution:
        return None
    solution: dict[str, list[int]] = {}
    for pid, cell in raw_solution.items():
        if not isinstance(pid, str) \
                or not isinstance(cell, (list, tuple)) or len(cell) != 2 \
                or not _is_int(cell[0]) or not _is_int(cell[1]):
            return None
        solution[pid] = [cell[0], cell[1]]
    return solution


def _killer_id(puzzle, solution: dict) -> str:
    """The only suspect in the victim's room (SPEC §3 rule 4)."""
    killer = clue_truth.unique_killer(puzzle, solution)
    if killer is None:
        raise RuntimeError(
            "generated solution violates SPEC §3: no suspect in the victim's room"
        )
    return killer


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
        # full streak of failures becomes a 503.  The drawn seed travels in
        # the token (needed for alternative-win logging).
        for _ in range(GENERATION_RETRIES):
            seed = secrets.randbelow(2**32)
            try:
                result = generate(seed, difficulty)
                break
            except GenerationError:
                continue
        if result is None:
            return _generation_failed(difficulty, seed=None)
    payload = {
        "game_id": uuid.uuid4().hex,
        "difficulty": difficulty,
        "seed": seed,
        "solution": {pid: [r, c] for pid, (r, c) in result.solution.items()},
        "killer_id": _killer_id(result.puzzle, result.solution),
        # The full puzzle rides in the token so the stateless /api/check can
        # validate ALTERNATIVE (non-identical) solutions against the clues.
        "puzzle": result.puzzle.to_dict(),
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

    solution = _parsed_solution(payload)
    killer_id = payload.get("killer_id")
    if solution is None:
        return _error("invalid token: solution missing or malformed")
    if not isinstance(killer_id, str):
        return _error("invalid token: killer_id missing")
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
        alt = _alternative_check(payload, placed, accusation, solution)
        if alt is not None:
            return alt
        return JSONResponse({"won": False, "misplaced_person_id": wrong[0]})
    if accusation == killer_id:
        return JSONResponse({"won": True, "solution": solution})
    return JSONResponse({"won": False, "correct_accusation": False})


def _alternative_check(payload: dict, placed: dict, accusation: str,
                       solution: dict) -> JSONResponse | None:
    """Alternative-solution validation (ideas.md): a placement DIFFERENT from
    the server's but satisfying every clue and the SPEC §3 rules is a win,
    judged against the user's own arrangement — the inferred killer is the
    suspect alone with the victim in THAT arrangement, and the accusation is
    compared to it.  Such a win can only stem from a generator/validation
    bug (generated puzzles are unique), so it is granted AND logged for bug
    hunting.  Returns None to fall through to the legacy exact-match
    responses when the token carries no (parsable) puzzle or the arrangement
    is invalid — every pre-existing outcome stays byte-identical.
    """
    embedded = payload.get("puzzle")
    if embedded is None:
        return None  # legacy token without an embedded puzzle
    try:
        puzzle = Puzzle.from_dict(embedded)
    except PuzzleValidationError:
        return None  # malformed embedded puzzle -> legacy behavior
    placement = {pid: (cell[0], cell[1]) for pid, cell in placed.items()}
    # a defect in the evaluator must NOT silently degrade an alternative win
    # into "misplaced" (that outcome is what alt_wins.jsonl exists to catch),
    # so evaluation happens outside the try and any raise surfaces as a 500
    ctx = clue_truth.TruthContext(puzzle)
    user_killer = clue_truth.unique_killer(puzzle, placement)
    if not (ctx.rules_ok(placement) and ctx.all_clues_hold(placement)):
        return None
    if accusation != user_killer:
        return JSONResponse({"won": False, "correct_accusation": False})
    _log_alt_win(payload, placement, accusation, user_killer)
    return JSONResponse({"won": True, "solution": solution, "alternative": True})


def _log_alt_win(payload: dict, placement: dict, accusation: str,
                 inferred_killer: str) -> None:
    """Append an alternative-win record (JSONL) for generator-bug hunting.
    IO failures must never affect the response (ideas.md decision)."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "game_id": payload.get("game_id"),
        "seed": payload.get("seed"),
        "difficulty": payload.get("difficulty"),
        "clues": payload["puzzle"]["clues"],
        "user_solution": {pid: [r, c] for pid, (r, c) in placement.items()},
        "server_solution": payload.get("solution"),
        "accusation": accusation,
        "inferred_killer": inferred_killer,
    }
    try:
        data_dir = Path(os.environ.get("MURDOKU_DATA_DIR", "data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        with (data_dir / "alt_wins.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"warning: could not log alternative win: {exc}", file=sys.stderr)


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
    solution = _parsed_solution(payload)
    killer_id = payload.get("killer_id")
    if solution is None or not isinstance(killer_id, str):
        return _error("invalid token: solution/killer_id missing or malformed")
    return JSONResponse({
        "solution": solution,
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
