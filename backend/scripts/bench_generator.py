"""Benchmark for murdoku.generator (SPEC §6, ARCHITECTURE §10).

Generates a fixed batch of puzzles per difficulty — easy 20 seeds,
medium 20, hard 15, expert 10 — and prints avg/max wall time, clue counts
and outer-attempt counts per difficulty.  Every generated puzzle is
verified unique (generate() asserts count_solutions == 1 internally; this
script re-checks a sample of them with the solver).

A seed can legitimately exhaust the generator's outer attempts (SPEC §6);
those are counted and reported as "dead" seeds rather than crashing the
run.  Budget (SPEC §6): expert generation < 3 s on average.  The script
exits with a non-zero status if the expert average exceeds it.

Usage:  python scripts/bench_generator.py
"""

import sys
import time

from murdoku.generator import GenerationError, generate
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
    print(f"{'difficulty':<10} {'ok':>3} {'dead':>4} {'avg ms':>9} "
          f"{'max ms':>9} {'avg clues':>10} {'max attempts':>13}  verdict")
    failed = False
    for difficulty, count, base_seed in PLAN:
        times = []
        clue_counts = []
        attempts = []
        puzzles = []
        dead = 0
        started = time.perf_counter()
        for i in range(count):
            try:
                result = generate(base_seed + i, difficulty)
            except GenerationError:
                dead += 1  # deterministic seed exhausted its attempts
                continue
            times.append((time.perf_counter() - started) * 1000.0)
            started = time.perf_counter()
            clue_counts.append(result.meta["clue_count"])
            attempts.append(result.meta["attempts"])
            puzzles.append(result)
        # spot-check uniqueness independently of generate()'s own assert
        for result in puzzles[:VERIFY_SAMPLE]:
            assert count_solutions(result.puzzle, 2) == 1, (
                f"{difficulty} seed={result.meta['seed']} is not unique")
        ok = len(puzzles)
        if not puzzles:
            print(f"{difficulty:<10} {ok:>3} {dead:>4}  — all seeds dead")
            failed = True
            continue
        avg = sum(times) / ok
        row = (f"{difficulty:<10} {ok:>3} {dead:>4} {avg:>9.1f} "
               f"{max(times):>9.1f} {sum(clue_counts) / ok:>10.1f} "
               f"{max(attempts):>13}")
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
