"""Benchmark for murdoku.solver on a dense 9x9, N=9 puzzle (ARCHITECTURE §6).

Builds a deterministic "expert-size" puzzle satisfying all SPEC rules:
- 9x9 board, 9 rooms (3x3 blocks), no voids;
- ~20 object instances covering every registry type (beds included),
  ~40% of them full objects;
- 9 people (8 suspects + victim); the victim and the killer share the
  center room, all other suspects are placed outside it;
- the full set of TRUE clues from the SPEC §6 step-5 domains (A/B per
  suspect x type present, C1 ordered pairs, C2/C3 unordered pairs, D1
  room x op x k in 0..N, D2 global) — several hundred clues covering every
  clue kind — synthesized from a known full assignment.

It then measures count_solutions(puzzle, limit=2) over several runs and
prints min/mean/max timings against the 100 ms budget (SPEC §5).

Usage:  python scripts/bench_solver.py [runs]
"""

import sys
import time
from itertools import permutations
from random import Random

from murdoku.model import (
    OBJECT_TYPES,
    FULL,
    ObjectInstance,
    Person,
    Puzzle,
    Room,
)
from murdoku.solver import count_solutions, solutions

SIZE = 9
BLOCK = 3
N_SUSPECTS = 8
MURDER_ROOM_ID = 5  # center 3x3 block
OBJECT_PLAN = [
    "bed", "bed",
    "table", "table", "table", "table",
    "carpet", "carpet", "carpet", "carpet",
    "tv", "tv",
    "wardrobe", "wardrobe",
    "fridge", "fridge",
    "armchair", "armchair",
    "sofa", "sofa",
]
SEED = 20261119
SEED_TRIES = 20  # advance the seed until the full clue set is unique
TARGET_MS = 100.0


def build_rooms():
    """Nine 3x3 block rooms, ids dense and ordered by corner cell."""
    rooms = []
    for br in range(BLOCK):
        for bc in range(BLOCK):
            cells = frozenset(
                (r, c)
                for r in range(br * BLOCK, br * BLOCK + BLOCK)
                for c in range(bc * BLOCK, bc * BLOCK + BLOCK)
            )
            rooms.append(Room(len(rooms) + 1, cells))
    return tuple(rooms)


def place_objects(rng, room_of_cell):
    """Place OBJECT_PLAN instances on distinct cells; a bed takes a free
    orth neighbour in the same room.  Returns (objects,) tuple."""
    free = set(room_of_cell)
    objects = []
    for i, otype in enumerate(OBJECT_PLAN, start=1):
        if otype == "bed":
            pairs = []
            for cell in sorted(free):
                for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nb = (cell[0] + dr, cell[1] + dc)
                    if nb in free and room_of_cell[nb] == room_of_cell[cell]:
                        pairs.append((cell, nb))
            if not pairs:
                raise RuntimeError("no bed placement left")
            cell, nb = rng.choice(pairs)
            cells = frozenset({cell, nb})
        else:
            if not free:
                raise RuntimeError("no cells left for objects")
            cells = frozenset({rng.choice(sorted(free))})
        free -= cells
        objects.append(ObjectInstance(f"obj_{i}", otype, cells))
    return tuple(objects)


def place_people(objects):
    """Deterministic backtracking: victim + killer in the center room,
    all other suspects outside it; distinct rows and columns; nobody on
    a full-object cell.  Returns person_id -> (r, c)."""
    room_of_cell = {}
    for room in build_rooms():
        for cell in room.cells:
            room_of_cell[cell] = room.id
    full = {cell
            for obj in objects
            for cell in obj.cells
            if OBJECT_TYPES[obj.type].cls == FULL}
    center = {cell for cell, rid in room_of_cell.items()
              if rid == MURDER_ROOM_ID}
    center_ok = sorted(center - full)
    outside_ok = sorted(set(room_of_cell) - center - full)
    people = [f"suspect_{i}" for i in range(1, N_SUSPECTS + 1)]

    def rows_cols_ok(placed, cell):
        return all(cell[0] != p[0] and cell[1] != p[1]
                   for p in placed.values())

    def rec(i, placed):
        if i == len(people):
            return True
        pid = people[i]
        for cell in outside_ok:
            if rows_cols_ok(placed, cell):
                placed[pid] = cell
                if rec(i + 1, placed):
                    return True
                del placed[pid]
        return False

    for vcell, kcell in permutations(center_ok, 2):
        if vcell[0] == kcell[0] or vcell[1] == kcell[1]:
            continue
        placed = {"victim": vcell, "suspect_1": kcell}
        if rec(1, placed):
            return placed
    raise RuntimeError("no people placement found")


def neighbors(cell):
    r, c = cell
    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < SIZE and 0 <= nc < SIZE:
            yield (nr, nc)


def true_clues(puzzle, solution):
    """All TRUE clues from the SPEC §6 step-5 domains, in a deterministic
    order, synthesized from the known assignment (direct semantics)."""
    type_at = {}
    room_types = {}
    for obj in puzzle.objects:
        for cell in obj.cells:
            type_at[cell] = obj.type
        rid = puzzle.room_of(next(iter(obj.cells))).id
        room_types.setdefault(rid, set()).add(obj.type)

    def on(person, t):
        return type_at.get(solution[person]) == t

    def near(person, t):
        cell = solution[person]
        if type_at.get(cell) == t:
            return False  # standing on an instance of O is not "near"
        return any(type_at.get(nb) == t for nb in neighbors(cell))

    def room_has(person, t):
        return t in room_types.get(puzzle.room_of(solution[person]).id, ())

    clues = []
    suspects = puzzle.suspect_ids()
    types_present = sorted({obj.type for obj in puzzle.objects})
    for pid in suspects:
        for t in types_present:
            person_fields = {"person": pid, "object_type": t}
            clues.append({"kind": "on" if on(pid, t) else "not_on",
                          **person_fields})
            clues.append({"kind": "adjacent" if near(pid, t)
                          else "not_adjacent", **person_fields})
            clues.append({"kind": "room_has_object" if room_has(pid, t)
                          else "room_not_has_object", **person_fields})
    for p1 in suspects:
        for p2 in suspects:
            if p1 == p2:
                continue
            if solution[p1][0] > solution[p2][0]:
                clues.append({"kind": "south", "person": p1, "person2": p2})
            else:
                clues.append({"kind": "north", "person": p1, "person2": p2})
            if solution[p1][1] > solution[p2][1]:
                clues.append({"kind": "east", "person": p1, "person2": p2})
            else:
                clues.append({"kind": "west", "person": p1, "person2": p2})
    for i, p1 in enumerate(suspects):
        for p2 in suspects[i + 1:]:
            same = (puzzle.room_of(solution[p1])
                    == puzzle.room_of(solution[p2]))
            clues.append({"kind": "same_room" if same else "not_same_room",
                          "person": p1, "person2": p2})
    n_people = len(puzzle.people)
    counts = {room.id: sum(1 for pid in puzzle.people_ids()
                           if puzzle.room_of(solution[pid]).id == room.id)
              for room in puzzle.rooms}
    for rid in sorted(counts):
        cnt = counts[rid]
        for op, holds in (("eq", lambda k: k == cnt),
                          ("ne", lambda k: k != cnt),
                          ("gt", lambda k: k < cnt),
                          ("ge", lambda k: k <= cnt),
                          ("lt", lambda k: k > cnt),
                          ("le", lambda k: k >= cnt)):
            clues.extend({"kind": "room_count", "room": rid,
                          "count": k, "op": op}
                         for k in range(n_people + 1) if holds(k))
    occupied = {puzzle.room_of(solution[pid]).id
                for pid in puzzle.people_ids()}
    if all(room.id in occupied for room in puzzle.rooms):
        clues.append({"kind": "no_empty_rooms"})
    return clues


def build_bench_puzzle():
    """Assemble the deterministic 9x9 benchmark puzzle and its solution.

    Advances the seed (deterministically) until the full TRUE clue set pins
    the puzzle to exactly one solution — the generator (SPEC §6) does the
    same by retrying, because the complete clue catalogue is not guaranteed
    to discriminate every layout.
    """
    rooms = build_rooms()
    room_of_cell = {cell: room.id
                    for room in rooms for cell in room.cells}
    people = tuple(
        [Person(f"suspect_{i}", f"Подозреваемый_{i}", 1000 + i)
         for i in range(1, N_SUSPECTS + 1)]
        + [Person("victim", "Убитый", 7)]
    )
    for attempt in range(SEED_TRIES):
        seed = SEED + attempt
        rng = Random(seed)
        objects = place_objects(rng, room_of_cell)
        placement = place_people(objects)
        skeleton = Puzzle(SIZE, SIZE, rooms, objects, people, ())
        clues = true_clues(skeleton, placement)
        puzzle = Puzzle(SIZE, SIZE, rooms, objects, people, tuple(clues))
        puzzle.validate()
        if count_solutions(puzzle, 2) == 1:
            return puzzle, placement, seed
    raise RuntimeError("no unique layout found within SEED_TRIES")


def measure(fn, runs, warmup=3):
    for _ in range(warmup):
        fn()
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        times.append((time.perf_counter() - start) * 1000.0)
    return times


def report(label, times):
    lo = min(times)
    mean = sum(times) / len(times)
    hi = max(times)
    print(f"  {label:<38} min {lo:8.3f} ms   mean {mean:8.3f} ms   "
          f"max {hi:8.3f} ms")
    return lo


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    puzzle, placement, seed = build_bench_puzzle()
    allowed = len(puzzle.allowed_cells())
    objects_full = sum(1 for o in puzzle.objects
                       if OBJECT_TYPES[o.type].cls == FULL)
    by_kind = {}
    for clue in puzzle.clues:
        by_kind[clue["kind"]] = by_kind.get(clue["kind"], 0) + 1

    print(f"bench_solver: dense 9x9, N=9, deterministic (seed {seed})")
    print(f"  rooms {len(puzzle.rooms)}, objects {len(puzzle.objects)} "
          f"({objects_full} full), allowed cells {allowed}")
    print(f"  clues {len(puzzle.clues)}: "
          + ", ".join(f"{k} x{by_kind[k]}" for k in sorted(by_kind)))

    first = next(iter(solutions(puzzle, 1)))
    assert first == placement, "solver solution differs from known assignment"
    assert count_solutions(puzzle, 2) == 1, "puzzle is not unique"
    print("  sanity: known assignment reproduced, exactly 1 solution")

    print(f"\n  timings over {runs} runs (after 3 warmups):")
    t_count = measure(lambda: count_solutions(puzzle, 2), runs)
    report("count_solutions(puzzle, limit=2)", t_count)
    t_one = measure(lambda: count_solutions(puzzle, 1), runs)
    report("count_solutions(puzzle, limit=1)", t_one)
    t_enum = measure(lambda: solutions(puzzle, 1).__next__(), runs)
    report("solutions(puzzle, 1) first item", t_enum)

    best = min(t_count)
    verdict = "OK — within budget" if best < TARGET_MS \
        else "FAIL — above budget"
    print(f"\n  budget {TARGET_MS:.0f} ms (SPEC §5): best "
          f"count_solutions = {best:.3f} ms -> {verdict}")
    return 0 if best < TARGET_MS else 1


if __name__ == "__main__":
    sys.exit(main())
