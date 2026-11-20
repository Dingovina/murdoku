"""Benchmark for murdoku.generator (SPEC §6, ARCHITECTURE §10).

Generates a fixed batch of puzzles per difficulty — easy 20 seeds,
medium 20, hard 15, expert 10 — and prints avg/max wall time, clue counts
and outer-attempt counts per difficulty.  Every generated puzzle is
verified unique (generate() asserts count_solutions == 1 internally; this
script re-checks a sample of them with the solver).

Budget (SPEC §6): expert generation < 3 s on average.  The script exits
with a non-zero status if the expert average exceeds it.

Usage:  python scripts/bench_generator.py
"""

import sys
import time

from murdoku.generator import generate
from murdoku.solver import count_solutions

PLAN = (
    ("easy", 20, 10_000),
    ("medium", 20, 20_000),
    ("hard", 15, 30_000),
    ("expert", 10, 40_000),
)
BUDGET_MS = 3000.0  # expert average budget (SPEC §6)
VERIFY_SAMPLE = 3   # re-verify uniqueness for N puzzles per difficulty


def main():
    print("bench_generator: wall time per generated puzzle "
          "(deterministic seed batches)")
    print(f"{'difficulty':<10} {'n':>3} {'avg ms':>9} {'max ms':>9} "
          f"{'avg clues':>10} {'max attempts':>13}  verdict")
    failed = False
    for difficulty, count, base_seed in PLAN:
        times = []
        clue_counts = []
        attempts = []
        puzzles = []
        started = time.perf_counter()
        for i in range(count):
            result = generate(base_seed + i, difficulty)
            times.append((time.perf_counter() - started) * 1000.0)
            started = time.perf_counter()
            clue_counts.append(result.meta["clue_count"])
            attempts.append(result.meta["attempts"])
            puzzles.append(result)
        # spot-check uniqueness independently of generate()'s own assert
        for result in puzzles[:VERIFY_SAMPLE]:
            assert count_solutions(result.puzzle, 2) == 1, (
                f"{difficulty} seed={result.meta['seed']} is not unique")
        avg = sum(times) / count
        row = (f"{difficulty:<10} {count:>3} {avg:>9.1f} {max(times):>9.1f} "
               f"{sum(clue_counts) / count:>10.1f} {max(attempts):>13}")
        if difficulty == "expert":
            verdict = ("OK — within 3 s budget" if avg < BUDGET_MS
                       else "FAIL — over 3 s budget")
            if avg >= BUDGET_MS:
                failed = True
        else:
            verdict = "—"
        print(row + "  " + verdict)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
