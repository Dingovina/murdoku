"""Export real-puzzle fixtures for the frontend contract tests (stage 5).

Generates two puzzles with the production generator (easy seed 1 and
medium seed 1) and writes their FULL SPEC §4 puzzle JSON to
``frontend/tests/fixtures/`` so the node test suite can run ``clueToText``
over real clue sets produced by the backend — the backend->frontend
contract loop.

Usage (repo root or anywhere, with the project venv):
    .venv/bin/python backend/scripts/export_clue_fixtures.py

Deterministic: the same generator seeds always rewrite the same bytes.
"""

import json
from pathlib import Path

from murdoku.generator import generate

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "frontend" / "tests" / "fixtures"

# (difficulty, seed) pairs; small boards keep the committed fixtures small.
EXPORTS = (("easy", 1), ("medium", 1))


def main() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    for difficulty, seed in EXPORTS:
        result = generate(seed, difficulty)
        puzzle_json = result.puzzle.to_dict()
        out_path = FIXTURES_DIR / f"{difficulty}_seed_{seed}.json"
        out_path.write_text(
            json.dumps(puzzle_json, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            f"wrote {out_path.relative_to(REPO_ROOT)} "
            f"({len(puzzle_json['clues'])} clues, "
            f"{len(puzzle_json['people'])} people, "
            f"{len(puzzle_json['objects'])} objects)"
        )


if __name__ == "__main__":
    main()
