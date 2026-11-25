"""Enumeration of true clues and greedy pruning (ARCHITECTURE §7, SPEC §6 step 5).

``enumerate_true_clues`` lists every TRUE clue of the catalogue over a known
solution, restricted to the SPEC §6 step-5 domains:

- A/B: each suspect × each object type **present on the field** (missing
  types are skipped — clues about them would be vacuum-true);
- C1: all ordered suspect pairs (south/north, east/west — only the true
  direction is listed, and none if the coordinate is equal);
- C2/C3: all unordered suspect pairs (same/different room);
- D1: each room × each op × k ∈ 0..N for the TRUE combinations only, where
  the room counters include **all** people, the victim included;
- D2: the global "no empty rooms" clue, if true.

The victim is never referenced by A/B/C clues (SPEC §4).

The result is sorted by a deterministic key: kind order as in SPEC §4,
person number, object type id, room id, count, op index (plus person2 as a
final tie-breaker for C1 pairs).

``prune_clues`` implements the SPEC greedy thinning: with the caller's RNG,
shuffle the directional C1 clues into a first pass and every other clue into
a second, then walk both passes, dropping a clue whenever
``count_solutions(puzzle without it, limit=2)`` stays 1.  Directional clues
are probed FIRST, so C1 clues that are individually redundant get dropped
before any other kind is touched — kept sets in practice contain few or no
south/north/east/west clues while uniqueness still holds.  (A directional
made necessary by the removal of another directional can survive — pairwise
redundancy — but that is rare.)  The surviving set
is locally minimal (a clue found necessary stays necessary, because dropping
clues only ever grows the solution set); the caller asserts its solution
count is exactly 1.
"""

from collections.abc import Mapping
from random import Random

from . import solver
from .model import Puzzle

Cell = tuple[int, int]

# Kind order exactly as in the SPEC §4 clue-format listing (deterministic
# sort key component #1; same order as model._CLUE_FIELDS).
KIND_ORDER: tuple[str, ...] = (
    "on", "not_on", "adjacent", "not_adjacent",
    "room_has_object", "room_not_has_object",
    "south", "north", "east", "west",
    "same_room", "not_same_room",
    "room_count", "no_empty_rooms",
)
_KIND_RANK = {kind: i for i, kind in enumerate(KIND_ORDER)}

# C1 kinds; prune_clues probes these first so kept sets stay lean of them.
_DIRECTIONAL_KINDS = frozenset({"south", "north", "east", "west"})

# op order as in the SPEC §4 clue format (sort key component #6).
OP_ORDER: tuple[str, ...] = ("eq", "ne", "gt", "ge", "lt", "le")
_OP_RANK = {op: i for i, op in enumerate(OP_ORDER)}

_VICTIM_RANK = 10 ** 9  # sorts after any suspect number (must not occur)


def _person_rank(pid: str | None) -> int:
    """Sort rank of a person id: suspect_n -> n, victim -> sentinel."""
    if pid is None:
        return -1
    if pid == "victim":
        return _VICTIM_RANK
    if pid.startswith("suspect_"):
        try:
            return int(pid[len("suspect_"):])
        except ValueError:
            pass
    return _VICTIM_RANK


def _sort_key(clue: dict) -> tuple:
    kind = clue["kind"]
    return (
        _KIND_RANK[kind],
        _person_rank(clue.get("person")),
        clue.get("object_type", ""),
        clue.get("room", -1),
        clue.get("count", -1),
        _OP_RANK.get(clue.get("op"), -1),
        _person_rank(clue.get("person2")),
    )


def _neighbors(cell: Cell, height: int, width: int) -> list[Cell]:
    r, c = cell
    out = []
    if r > 0:
        out.append((r - 1, c))
    if r < height - 1:
        out.append((r + 1, c))
    if c > 0:
        out.append((r, c - 1))
    if c < width - 1:
        out.append((r, c + 1))
    return out


def _d1_holds(count: int, op: str, k: int) -> bool:
    """True if |people(room)| ``op`` ``k`` holds for the given count."""
    if op == "eq":
        return count == k
    if op == "ne":
        return count != k
    if op == "gt":
        return count > k
    if op == "ge":
        return count >= k
    if op == "lt":
        return count < k
    return count <= k  # "le"


def enumerate_true_clues(puzzle: Puzzle,
                         solution: Mapping[str, Cell]) -> list[dict]:
    """All TRUE clues from the SPEC §6 step-5 domains, deterministically
    ordered.  ``solution`` must be a full placement (person id -> cell)
    satisfying the SPEC §3 rules for ``puzzle``."""
    height, width = puzzle.height, puzzle.width

    # static views over the field
    type_at: dict[Cell, str] = {}
    room_types: dict[int, set[str]] = {}
    for obj in puzzle.objects:
        rid = puzzle.room_of(next(iter(obj.cells)))
        rid_id = rid.id if rid is not None else 0
        for cell in obj.cells:
            type_at[cell] = obj.type
        room_types.setdefault(rid_id, set()).add(obj.type)

    suspects = puzzle.suspect_ids()
    types_present = sorted({obj.type for obj in puzzle.objects})
    clues: list[dict] = []

    # A/B: suspect x present type; exactly one true variant per category.
    for pid in suspects:
        cell = solution[pid]
        room = puzzle.room_of(cell)
        rid = room.id if room is not None else 0
        standing_on = type_at.get(cell)
        near_set = {type_at.get(nb) for nb in _neighbors(cell, height, width)
                    if room == puzzle.room_of(nb)}
        room_has = room_types.get(rid, ())
        for otype in types_present:
            fields = {"person": pid, "object_type": otype}
            on = standing_on == otype
            near = on is False and otype in near_set
            in_room = otype in room_has
            clues.append({"kind": "on" if on else "not_on", **fields})
            clues.append({"kind": "adjacent" if near else "not_adjacent",
                          **fields})
            clues.append({"kind": "room_has_object" if in_room
                          else "room_not_has_object", **fields})

    # C1: ordered pairs; emit only the true direction (rows/cols of a valid
    # solution are pairwise distinct, but equality-safe all the same).
    for p1 in suspects:
        for p2 in suspects:
            if p1 == p2:
                continue
            a, b = solution[p1], solution[p2]
            if a[0] > b[0]:
                clues.append({"kind": "south", "person": p1, "person2": p2})
            elif a[0] < b[0]:
                clues.append({"kind": "north", "person": p1, "person2": p2})
            if a[1] > b[1]:
                clues.append({"kind": "east", "person": p1, "person2": p2})
            elif a[1] < b[1]:
                clues.append({"kind": "west", "person": p1, "person2": p2})

    # C2/C3: unordered pairs.
    for i, p1 in enumerate(suspects):
        for p2 in suspects[i + 1:]:
            same = puzzle.room_of(solution[p1]) is puzzle.room_of(solution[p2])
            clues.append({"kind": "same_room" if same else "not_same_room",
                          "person": p1, "person2": p2})

    # D1: room x op x k in 0..N over the TRUE combinations; counters include
    # every person (the victim too).
    n_people = len(puzzle.people)
    counts: dict[int, int] = {}
    for pid in puzzle.people_ids():
        room = puzzle.room_of(solution[pid])
        rid = room.id if room is not None else 0
        counts[rid] = counts.get(rid, 0) + 1
    for room in puzzle.rooms:
        cnt = counts.get(room.id, 0)
        for op in OP_ORDER:
            clues.extend(
                {"kind": "room_count", "room": room.id, "count": k, "op": op}
                for k in range(n_people + 1)
                if _d1_holds(cnt, op, k))

    # D2: global "no empty rooms" if true.
    if puzzle.rooms and all(counts.get(room.id, 0) >= 1
                            for room in puzzle.rooms):
        clues.append({"kind": "no_empty_rooms"})

    clues.sort(key=_sort_key)
    return clues


def prune_clues(puzzle: Puzzle, clues: list[dict],
                rng: Random) -> list[dict]:
    """Greedy SPEC §6 thinning, directional clues probed first.

    Pass 1 shuffles (with ``rng``) only the C1 directional clues and probes
    each; pass 2 does the same for every other kind.  A clue is dropped when
    its removal keeps ``count_solutions(...) == 1``.  Returns the locally
    minimal surviving list (order: as passed in, minus the dropped clues);
    the caller asserts that its solution count is exactly 1.

    Determinism: one RNG stream, fixed pass order — same seed, same kept set.

    Probes reuse a single shared ``Geometry``, so per-probe preparation only
    rebuilds the clue-dependent masks; results are identical to plain
    ``count_solutions`` calls.
    """
    kept = list(clues)
    directional = [c for c in kept if c["kind"] in _DIRECTIONAL_KINDS]
    others = [c for c in kept if c["kind"] not in _DIRECTIONAL_KINDS]
    rng.shuffle(directional)
    rng.shuffle(others)
    geometry = solver.Geometry(puzzle)
    for clue in (*directional, *others):
        idx = _index_of(kept, clue)
        if idx < 0:
            continue  # duplicate entry already removed
        probe_clues = kept[:idx] + kept[idx + 1:]
        probe = Puzzle(puzzle.width, puzzle.height, puzzle.rooms,
                       puzzle.objects, puzzle.people, tuple(probe_clues))
        if solver.Prepared(probe, geometry).count_solutions(2) == 1:
            kept = probe_clues
    return kept


def _index_of(kept: list[dict], clue: dict) -> int:
    """Index of ``clue`` in ``kept`` by identity, falling back to equality."""
    for i, item in enumerate(kept):
        if item is clue:
            return i
    for i, item in enumerate(kept):
        if item == clue:
            return i
    return -1
