"""Full puzzle generation pipeline (SPEC §6, ARCHITECTURE §7).

One ``random.Random(seed)`` drives the whole pipeline, so the same seed
always yields the same puzzle bytes.  Per SPEC: every step gets up to 50
inner attempts; when a step exhausts them, the whole outer attempt restarts
(the RNG stream simply continues), up to 40 outer attempts.

Steps:

1. pick the number of void rooms ``x ∈ {0,1}`` and the target number of
   playable rooms ``R = randint(rooms range) - x`` (the difficulty range
   counts rooms INCLUDING voids); grow ``R + x`` regions over the whole
   rectangle (BFS from seeds in random order, every region ≥ 2 cells);
2. exclude ``x`` random regions as voids (≤ 30% of the rectangle area),
   validate the silhouette (every row and column keeps ≥ 1 playable cell);
3. place object instances (class first with P(full) = 0.4, then a uniform
   type within the class; bed = 2 orth-adjacent cells of one room; all
   instance cells pairwise distinct); validate person-allowed coverage;
4. choose the murder room (≥ 2 allowed cells in distinct rows AND cols),
   place the victim and the killer there, backtrack the remaining suspects
   under the SPEC §3 rules (nobody else in the murder room);
5. enumerate ALL true clues; if the full set is not unique — the outer
   attempt fails (removing clues can never reduce the solution count, so a
   non-unique full set can never be pruned to unique); otherwise greedily
   prune and assert the final set is unique.
"""

from dataclasses import dataclass
from random import Random
from time import perf_counter

from .clues import enumerate_true_clues, prune_clues
from .model import (
    OBJECT_TYPE_IDS,
    OBJECT_TYPES,
    FULL,
    PARTIAL,
    ObjectInstance,
    Person,
    Puzzle,
    Room,
)
from .solver import count_solutions

Cell = tuple[int, int]

# Difficulty parameters per SPEC §6; the "rooms" range counts rooms INCLUDING
# the voids — playable rooms = drawn value minus x (SPEC §6 step 1).
DIFFICULTY_PARAMS: dict[str, dict] = {
    "easy":   {"size": 6, "people": (4, 5), "objects": (6, 10), "rooms": (3, 5)},
    "medium": {"size": 7, "people": (5, 7), "objects": (5, 15), "rooms": (5, 10)},
    "hard":   {"size": 8, "people": (6, 8), "objects": (7, 19), "rooms": (6, 13)},
    "expert": {"size": 9, "people": (7, 9), "objects": (8, 24), "rooms": (7, 16)},
}
DIFFICULTIES: tuple[str, ...] = tuple(DIFFICULTY_PARAMS)

STEP_ATTEMPTS = 50   # per-step attempt limit (SPEC §6)
OUTER_ATTEMPTS = 40  # outer attempt limit (SPEC §6)

_FULL_TYPE_IDS = tuple(
    t for t in OBJECT_TYPE_IDS if OBJECT_TYPES[t].cls == FULL)
_PARTIAL_TYPE_IDS = tuple(
    t for t in OBJECT_TYPE_IDS if OBJECT_TYPES[t].cls == PARTIAL)


class GenerationError(RuntimeError):
    """Raised when all outer attempts failed (practically never happens)."""


@dataclass
class GenerationResult:
    """Puzzle plus its known solution and generation metadata."""

    puzzle: Puzzle
    solution: dict[str, Cell]  # full placement, incl. victim & killer
    meta: dict                 # seed, difficulty, generation_ms, clue_count, ...


def generate(seed: int, difficulty: str) -> GenerationResult:
    """Generate a unique-solution puzzle for ``difficulty`` from ``seed``.

    Deterministic: the same (seed, difficulty) pair always produces the same
    puzzle.  Raises ``ValueError`` on an unknown difficulty and
    ``GenerationError`` if every outer attempt failed.
    """
    params = DIFFICULTY_PARAMS.get(difficulty)
    if params is None:
        raise ValueError(
            f"unknown difficulty {difficulty!r}; "
            f"expected one of: {', '.join(DIFFICULTIES)}")
    rng = Random(seed)
    started = perf_counter()
    for attempt in range(1, OUTER_ATTEMPTS + 1):
        found = _attempt(rng, params)
        if found is not None:
            rooms, objects, people, solution, kept, full_count = found
            size = params["size"]
            puzzle = Puzzle(size, size, rooms, objects, people, tuple(kept))
            elapsed_ms = (perf_counter() - started) * 1000.0
            meta = {
                "seed": seed,
                "difficulty": difficulty,
                "generation_ms": round(elapsed_ms, 3),
                "clue_count": len(puzzle.clues),
                "attempts": attempt,
                "full_clue_count": full_count,
                "people_count": len(people),
                "room_count": len(rooms),
                "object_count": len(objects),
                "void_cells": size * size - len(puzzle.playable_cells()),
            }
            return GenerationResult(puzzle, solution, meta)
    raise GenerationError(
        f"generation failed: seed={seed}, difficulty={difficulty!r}, "
        f"{OUTER_ATTEMPTS} outer attempts exhausted")


# ----------------------------------------------------------------------
# one outer attempt
# ----------------------------------------------------------------------

def _attempt(rng: Random, params: dict):
    """Run one outer attempt; return its parts or None on any failure.

    The RNG stream continues across attempts, which keeps the mapping
    seed -> puzzle deterministic.
    """
    size = params["size"]
    x = rng.randint(0, 1)                     # void rooms (SPEC §6 step 1)
    n_rooms = rng.randint(*params["rooms"]) - x  # playable rooms target
    n_people = rng.randint(*params["people"])
    n_objects = rng.randint(*params["objects"])

    rooms = _make_rooms(rng, size, n_rooms, x)
    if rooms is None:
        return None
    room_index: dict[Cell, Room] = {}
    for room in rooms:
        for cell in room.cells:
            room_index[cell] = room
    playable = frozenset(room_index)

    objects = _make_objects(rng, room_index, playable, n_objects, n_people)
    if objects is None:
        return None
    allowed = _allowed_cells(room_index, objects)

    placement = _place_people(rng, rooms, room_index, allowed, n_people)
    if placement is None:
        return None

    people = _make_people(rng, n_people)
    skeleton = Puzzle(size, size, rooms, objects, people, ())
    skeleton.validate()  # paranoia: rooms/objects/people are well-formed

    # clues: full true set must already be unique, otherwise pruning can
    # never reach a unique puzzle (removals only add solutions)
    full = enumerate_true_clues(skeleton, placement)
    full_puzzle = Puzzle(size, size, rooms, objects, people, tuple(full))
    if count_solutions(full_puzzle, 2) != 1:
        return None
    kept = prune_clues(full_puzzle, full, rng)
    final = Puzzle(size, size, rooms, objects, people, tuple(kept))
    if count_solutions(final, 2) != 1:
        # kept is unique by construction (every drop was verified against
        # the surviving set), so this is an internal invariant violation -
        # fail loudly instead of shipping a non-unique puzzle
        raise GenerationError("internal invariant violated: the pruned "
                              "clue set is not unique")
    return rooms, objects, people, placement, kept, len(full)


# ----------------------------------------------------------------------
# steps 1-2: regions and voids
# ----------------------------------------------------------------------

def _make_rooms(rng: Random, size: int, n_playable: int, x_voids: int):
    """Grow regions, exclude voids, renumber; None after 50 failed tries."""
    for _ in range(STEP_ATTEMPTS):
        regions = _grow_regions(rng, size, n_playable + x_voids)
        if regions is None:
            continue
        void_cells: set[Cell] = set()
        for region in rng.sample(regions, x_voids):
            void_cells |= region
        # void area <= 30% of the rectangle (SPEC §1)
        if 10 * len(void_cells) > 3 * size * size:
            continue
        # silhouette: every row and column keeps >= 1 playable cell
        playable = [(r, c) for r in range(size) for c in range(size)
                    if (r, c) not in void_cells]
        if {r for r, _ in playable} != set(range(size)) \
                or {c for _, c in playable} != set(range(size)):
            continue
        remaining = [region for region in regions
                     if region.isdisjoint(void_cells)]
        remaining.sort(key=min)
        rooms = tuple(Room(i + 1, frozenset(region))
                      for i, region in enumerate(remaining))
        return rooms
    return None


def _grow_regions(rng: Random, size: int, n_regions: int):
    """Partition the whole rectangle into ``n_regions`` orthogonally
    connected regions of >= 2 cells (multi-source BFS from random seeds,
    regions expanded in random order); None if some region stayed 1-cell."""
    total = size * size
    if n_regions < 1 or 2 * n_regions > total:
        return None
    owner = [-1] * total          # region index, -1 = unclaimed
    seeds = rng.sample(range(total), n_regions)
    for i, s in enumerate(seeds):
        owner[s] = i
    frontier = [set(_free_neighbors(owner, size, s)) for s in seeds]
    sizes = [1] * n_regions

    def claim(region: int, cell: int) -> None:
        owner[cell] = region
        sizes[region] += 1
        for other in frontier:
            other.discard(cell)
        for nb in _neighbors4(cell, size):
            if owner[nb] == -1:
                frontier[region].add(nb)

    # phase 1: give every seed a chance to grab one neighbour (so that a
    # seed ringed by other seeds fails fast instead of at the very end)
    order = list(range(n_regions))
    rng.shuffle(order)
    for i in order:
        f = frontier[i]
        if f:
            claim(i, rng.choice(sorted(f)))

    # phase 2: random-order expansion until the rectangle is covered
    remaining = total - sum(sizes)
    while remaining:
        order = [i for i in range(n_regions) if frontier[i]]
        if not order:
            return None  # isolated free cells: cannot happen on a grid
        rng.shuffle(order)
        for i in order:
            f = frontier[i]
            if f:
                claim(i, rng.choice(sorted(f)))
                remaining -= 1
    if min(sizes) < 2:
        return None
    return [frozenset((idx // size, idx % size) for idx in range(total)
                      if owner[idx] == i)
            for i in range(n_regions)]


def _neighbors4(idx: int, size: int) -> list[int]:
    r, c = divmod(idx, size)
    out = []
    if r > 0:
        out.append(idx - size)
    if r < size - 1:
        out.append(idx + size)
    if c > 0:
        out.append(idx - 1)
    if c < size - 1:
        out.append(idx + 1)
    return out


def _free_neighbors(owner: list[int], size: int, idx: int) -> list[int]:
    return [nb for nb in _neighbors4(idx, size) if owner[nb] == -1]


# ----------------------------------------------------------------------
# step 3: objects
# ----------------------------------------------------------------------

def _make_objects(rng: Random, room_index: dict, playable: frozenset,
                  n_objects: int, n_people: int):
    """Place object instances; None after 50 failed tries."""
    size = max(r for r, _ in playable) + 1
    for _ in range(STEP_ATTEMPTS):
        objects = _place_objects(rng, room_index, playable, n_objects)
        if objects is None:
            continue
        allowed = _allowed_cells(room_index, objects)
        # validation: every row/column keeps >= 1 person-allowed cell and
        # there are at least n_people of them (SPEC §6 step 3)
        if len(allowed) < n_people:
            continue
        rows = {r for r, _ in allowed}
        cols = {c for _, c in allowed}
        if len(rows) < size or len(cols) < size:
            continue
        return objects
    return None


def _place_objects(rng: Random, room_index: dict, playable: frozenset,
                   n_objects: int):
    """One placement try; the object tuple, or None on a dead end."""
    free = set(playable)
    objects: list[ObjectInstance] = []
    for i in range(1, n_objects + 1):
        if not free:
            return None
        is_full = rng.random() < 0.4  # class first, then a type (SPEC §6)
        otype = rng.choice(_FULL_TYPE_IDS if is_full else _PARTIAL_TYPE_IDS)
        if OBJECT_TYPES[otype].size == 2:
            # multi-cell instance: a cell plus an orth neighbour of the
            # same room (uniform over the free unordered adjacent pairs)
            pairs = []
            for cell in sorted(free):
                for nb in _cell_neighbors(cell):
                    if nb in free and room_index[nb] is room_index[cell]:
                        pairs.append((cell, nb))
            if not pairs:
                return None
            a, b = rng.choice(pairs)
            cells = frozenset((a, b))
        else:
            cells = frozenset((rng.choice(sorted(free)),))
        free -= cells
        objects.append(ObjectInstance(f"obj_{i}", otype, cells))
    return tuple(objects)


def _cell_neighbors(cell: Cell) -> tuple[Cell, Cell, Cell, Cell]:
    r, c = cell
    return ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1))


# ----------------------------------------------------------------------
# step 4: people
# ----------------------------------------------------------------------

def _place_people(rng: Random, rooms: tuple[Room, ...], room_index: dict,
                  allowed: frozenset, n_people: int):
    """Place victim + killer + suspects; None after 50 failed tries."""
    murder_candidates = []
    for room in rooms:
        ok = sorted(cell for cell in room.cells if cell in allowed)
        if _has_row_col_pair(ok):
            murder_candidates.append(ok)
    for _ in range(STEP_ATTEMPTS):
        result = _try_people(rng, murder_candidates, room_index, allowed,
                             n_people)
        if result is not None:
            return result
    return None


def _try_people(rng: Random, murder_candidates, room_index: dict,
                allowed: frozenset, n_people: int):
    """One placement try (SPEC §3 rules 1-4) or None on a dead end."""
    if not murder_candidates:
        return None
    murder_room_cells = rng.choice(murder_candidates)
    murder_room = room_index[murder_room_cells[0]]
    killer_num = rng.randint(1, n_people - 1)
    victim_cell = rng.choice(murder_room_cells)
    killer_cells = [cell for cell in murder_room_cells
                    if cell[0] != victim_cell[0]
                    and cell[1] != victim_cell[1]]
    if not killer_cells:
        return None
    killer_cell = rng.choice(killer_cells)

    placed: dict[str, Cell] = {
        "victim": victim_cell,
        f"suspect_{killer_num}": killer_cell,
    }
    used_rows = {victim_cell[0], killer_cell[0]}
    used_cols = {victim_cell[1], killer_cell[1]}

    # remaining suspects: nobody else in the murder room (rule 4)
    pool = sorted(cell for cell in allowed
                  if room_index[cell] is not murder_room)
    order = [i for i in range(1, n_people) if i != killer_num]
    candidates = []
    for _ in order:
        cells = list(pool)
        rng.shuffle(cells)
        candidates.append(cells)

    def dfs(j: int) -> bool:
        if j == len(order):
            return True
        pid = f"suspect_{order[j]}"
        for cell in candidates[j]:
            if cell[0] in used_rows or cell[1] in used_cols:
                continue
            placed[pid] = cell
            used_rows.add(cell[0])
            used_cols.add(cell[1])
            if dfs(j + 1):
                return True
            del placed[pid]
            used_rows.discard(cell[0])
            used_cols.discard(cell[1])
        return False

    if not dfs(0):
        return None

    # The victim is referenced by no A/B/C clue, and a same-room victim
    # move leaves every room counter unchanged — so a full true clue set
    # can never distinguish two placements that differ only in the
    # victim's cell within the murder room.  A unique puzzle therefore
    # requires a "locked" victim: no other allowed cell of the murder room
    # may have both a row and a column that no person uses.  Retry with
    # fresh RNG draws otherwise.
    size = max(r for r, _ in allowed) + 1
    used_rows = {cell[0] for cell in placed.values()}
    used_cols = {cell[1] for cell in placed.values()}
    free_rows = {r for r in range(size) if r not in used_rows}
    free_cols = {c for c in range(size) if c not in used_cols}
    for cell in murder_room_cells:
        if cell != victim_cell and cell[0] in free_rows \
                and cell[1] in free_cols:
            return None
    return placed


def _has_row_col_pair(cells: list[Cell]) -> bool:
    """True if some two cells differ in both row and column (a room needs
    >= 2 allowed cells in distinct rows AND distinct cols for the victim
    and the killer)."""
    n = len(cells)
    for i in range(n):
        r0, c0 = cells[i]
        for j in range(i + 1, n):
            r1, c1 = cells[j]
            if r0 != r1 and c0 != c1:
                return True
    return False


def _make_people(rng: Random, n_people: int) -> tuple[Person, ...]:
    """Suspects in numeric order, then the victim; 32-bit portrait seeds."""
    people = [Person(f"suspect_{i}", f"Подозреваемый_{i}",
                     rng.getrandbits(32))
              for i in range(1, n_people)]
    people.append(Person("victim", "Убитый", rng.getrandbits(32)))
    return tuple(people)


def _allowed_cells(room_index: dict, objects: tuple[ObjectInstance, ...]) \
        -> frozenset:
    """Playable cells minus cells covered by full objects."""
    full_cells = {cell for obj in objects
                  if OBJECT_TYPES[obj.type].cls == FULL
                  for cell in obj.cells}
    return frozenset(room_index) - full_cells
