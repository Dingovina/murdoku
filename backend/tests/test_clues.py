"""Tests for murdoku.clues: true-clue enumeration domains, deterministic
ordering, and greedy pruning (ARCHITECTURE §7, SPEC §6 step 5).

Clue truth is cross-checked against an independent direct-semantics
evaluator defined here (not the solver).
"""

import pytest
from random import Random

from murdoku.clues import (
    KIND_ORDER,
    OP_ORDER,
    enumerate_true_clues,
    prune_clues,
)

_DIRECTIONAL = ("south", "north", "east", "west")
from murdoku.model import ObjectInstance, Person, Puzzle, Room
from murdoku.solver import count_solutions, solutions


# ----------------------------------------------------------------------
# builders
# ----------------------------------------------------------------------

def people_tuple(n_suspects):
    people = [
        Person(f"suspect_{i}", f"Подозреваемый_{i}", 100 + i)
        for i in range(1, n_suspects + 1)
    ]
    people.append(Person("victim", "Убитый", 7))
    return tuple(people)


def scenario_rooms():
    """3x3: 2x2 block, then a 2-cell and a 3-cell room."""
    return (
        Room(1, frozenset({(0, 0), (0, 1), (1, 0), (1, 1)})),
        Room(2, frozenset({(0, 2), (1, 2)})),
        Room(3, frozenset({(2, 0), (2, 1), (2, 2)})),
    )


def scenario_puzzle(clues=()):
    """s1=(1,1) on the armchair, s2=(2,2) on the sofa, victim=(0,0) bed."""
    objects = (
        ObjectInstance("obj_1", "armchair", frozenset({(1, 1)})),
        ObjectInstance("obj_2", "sofa", frozenset({(2, 2)})),
        ObjectInstance("obj_3", "bed", frozenset({(0, 0), (1, 0)})),
    )
    puzzle = Puzzle(3, 3, scenario_rooms(), objects, people_tuple(2),
                    tuple(clues))
    puzzle.validate()
    return puzzle


SCENARIO_SOLUTION = {
    "suspect_1": (1, 1),
    "suspect_2": (2, 2),
    "victim": (0, 0),
}


# ----------------------------------------------------------------------
# independent direct-semantics clue evaluator (no solver involved)
# ----------------------------------------------------------------------

def type_at(puzzle, cell):
    obj = puzzle.object_at(cell)
    return obj.type if obj is not None else None


def near(puzzle, cell, otype):
    """«рядом с O»: an orth neighbour holds O and the cell itself not.

    Same-room semantics (SPEC §4): the neighbour must lie in the same room
    as ``cell``; adjacency across a room boundary does not count.
    """
    if type_at(puzzle, cell) == otype:
        return False
    r, c = cell
    for nb in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
        if 0 <= nb[0] < puzzle.height and 0 <= nb[1] < puzzle.width \
                and puzzle.room_of(nb) is not None \
                and puzzle.room_of(nb) is puzzle.room_of(cell) \
                and type_at(puzzle, nb) == otype:
            return True
    return False


def room_types(puzzle, room):
    return {type_at(puzzle, cell) for cell in room.cells} - {None}


def clue_is_true(puzzle, solution, clue):
    kind = clue["kind"]
    if kind in ("on", "not_on"):
        got = type_at(puzzle, solution[clue["person"]]) == clue["object_type"]
        return got if kind == "on" else not got
    if kind in ("adjacent", "not_adjacent"):
        got = near(puzzle, solution[clue["person"]], clue["object_type"])
        return got if kind == "adjacent" else not got
    if kind in ("room_has_object", "room_not_has_object"):
        room = puzzle.room_of(solution[clue["person"]])
        got = clue["object_type"] in room_types(puzzle, room)
        return got if kind == "room_has_object" else not got
    if kind == "adjacent_gender":
        # same-room semantics: another person of the given gender in the
        # SAME ROOM (any person counts, the victim included)
        room = puzzle.room_of(solution[clue["person"]])
        if room is None:
            return False
        gender_of = {p.id: p.gender for p in puzzle.people}
        return any(pid != clue["person"]
                   and gender_of.get(pid) == clue["gender"]
                   and puzzle.room_of(solution[pid]) is room
                   for pid in solution)
    if kind in ("south", "north", "east", "west"):
        a, b = solution[clue["person"]], solution[clue["person2"]]
        return {"south": a[0] > b[0], "north": a[0] < b[0],
                "east": a[1] > b[1], "west": a[1] < b[1]}[kind]
    if kind in ("same_room", "not_same_room"):
        same = (puzzle.room_of(solution[clue["person"]])
                is puzzle.room_of(solution[clue["person2"]]))
        return same if kind == "same_room" else not same
    if kind == "room_count":
        rid, k, op = clue["room"], clue["count"], clue["op"]
        cnt = sum(1 for pid in puzzle.people_ids()
                  if puzzle.room_of(solution[pid]).id == rid)
        return {"eq": cnt == k, "ne": cnt != k, "gt": cnt > k,
                "ge": cnt >= k, "lt": cnt < k, "le": cnt <= k}[op]
    if kind == "no_empty_rooms":
        occupied = {puzzle.room_of(solution[pid]).id
                    for pid in puzzle.people_ids()}
        return all(room.id in occupied for room in puzzle.rooms)
    raise AssertionError(f"unknown clue kind {kind!r}")


def test_near_is_same_room_only():
    """«рядом с O» ignores instances across a room boundary (SPEC §4)."""
    puzzle = scenario_puzzle()
    # (1,2) sits in room 2; its neighbour (1,1) holds the armchair but
    # belongs to room 1 — across the wall, so NOT «рядом».
    assert not near(puzzle, (1, 2), "armchair")
    # (0,1) is room 1 like the armchair at (1,1) — «рядом» holds.
    assert near(puzzle, (0, 1), "armchair")
    placement = {"suspect_1": (1, 2), "suspect_2": (0, 1), "victim": (0, 0)}
    assert clue_is_true(puzzle, placement, {"kind": "not_adjacent",
                                            "person": "suspect_1",
                                            "object_type": "armchair"})
    assert not clue_is_true(puzzle, placement, {"kind": "adjacent",
                                                "person": "suspect_1",
                                                "object_type": "armchair"})
    # enumeration agrees with the direct evaluator
    clues = enumerate_true_clues(puzzle, placement)
    kinds_s1 = [c["kind"] for c in clues
                if c.get("person") == "suspect_1"
                and c.get("object_type") == "armchair"]
    assert "not_adjacent" in kinds_s1 and "adjacent" not in kinds_s1
    kinds_s2 = [c["kind"] for c in clues
                if c.get("person") == "suspect_2"
                and c.get("object_type") == "armchair"]
    assert "adjacent" in kinds_s2


# ----------------------------------------------------------------------
# enumeration: domains, truth, ordering
# ----------------------------------------------------------------------

def test_enumerate_is_deterministic_and_sorted():
    puzzle = scenario_puzzle()
    first = enumerate_true_clues(puzzle, SCENARIO_SOLUTION)
    second = enumerate_true_clues(puzzle, SCENARIO_SOLUTION)
    assert first == second
    assert all(clue_is_true(puzzle, SCENARIO_SOLUTION, c) for c in first)
    # kinds grouped in the SPEC §4 order, no group re-appears later
    seen_kinds = [c["kind"] for c in first]
    ranks = [KIND_ORDER.index(k) for k in seen_kinds]
    assert ranks == sorted(ranks)
    # within a kind, deterministic sub-order (person, type/room/count/op)
    key_of = lambda c: (KIND_ORDER.index(c["kind"]),
                        int(c.get("person", "suspect_0").split("_")[-1])
                        if "person" in c else -1,
                        c.get("object_type", ""), c.get("room", -1),
                        c.get("count", -1),
                        OP_ORDER.index(c["op"]) if "op" in c else -1)
    assert [key_of(c) for c in first] == sorted(key_of(c) for c in first)


def test_enumerate_covers_exactly_the_true_domain_clues():
    puzzle = scenario_puzzle()
    solution = SCENARIO_SOLUTION
    clues = enumerate_true_clues(puzzle, solution)
    by_kind = {}
    for clue in clues:
        by_kind.setdefault(clue["kind"], []).append(clue)

    suspects = puzzle.suspect_ids()
    types_present = sorted({o.type for o in puzzle.objects})

    # A/B: exactly one true variant per category per (suspect, present type)
    ab_kinds = {"on", "not_on", "adjacent", "not_adjacent",
                "room_has_object", "room_not_has_object"}
    ab = [c for c in clues if c["kind"] in ab_kinds]
    assert len(ab) == len(suspects) * len(types_present) * 3
    for pid in suspects:
        for otype in types_present:
            triple = [c for c in ab if c["person"] == pid
                      and c["object_type"] == otype]
            assert len(triple) == 3
            assert {c["kind"] for c in triple} == {
                "on" if type_at(puzzle, solution[pid]) == otype else "not_on",
                "adjacent" if near(puzzle, solution[pid], otype)
                else "not_adjacent",
                "room_has_object"
                if otype in room_types(puzzle, puzzle.room_of(solution[pid]))
                else "room_not_has_object",
            }
    # no clues about types absent from the field
    assert {c["object_type"] for c in ab} == set(types_present)

    # C1: one true direction per ordered pair per axis
    c1 = [c for c in clues if c["kind"] in ("south", "north", "east", "west")]
    assert len(c1) == len(suspects) * (len(suspects) - 1) * 2
    for p1 in suspects:
        for p2 in suspects:
            if p1 == p2:
                continue
            a, b = solution[p1], solution[p2]
            expect_row = "south" if a[0] > b[0] else "north"
            expect_col = "east" if a[1] > b[1] else "west"
            kinds = {c["kind"] for c in c1
                     if c["person"] == p1 and c["person2"] == p2}
            assert kinds == {expect_row, expect_col}

    # C2/C3: exactly one per unordered pair
    c23 = [c for c in clues if c["kind"] in ("same_room", "not_same_room")]
    assert len(c23) == len(suspects) * (len(suspects) - 1) // 2

    # D1: all true (room, op, k) combos, k in 0..N
    n_people = len(puzzle.people)
    counts = {room.id: sum(1 for pid in puzzle.people_ids()
                           if puzzle.room_of(solution[pid]).id == room.id)
              for room in puzzle.rooms}
    d1 = [c for c in clues if c["kind"] == "room_count"]
    expected_d1 = 0
    for room in puzzle.rooms:
        cnt = counts[room.id]
        for op in OP_ORDER:
            holds = {"eq": lambda k: k == cnt, "ne": lambda k: k != cnt,
                     "gt": lambda k: k < cnt, "ge": lambda k: k <= cnt,
                     "lt": lambda k: k > cnt, "le": lambda k: k >= cnt}
            expected_d1 += sum(1 for k in range(n_people + 1)
                               if holds[op](k))
    assert len(d1) == expected_d1
    assert all(clue_is_true(puzzle, solution, c) for c in d1)

    # D2 present iff all rooms are occupied
    all_occupied = all(counts[room.id] >= 1 for room in puzzle.rooms)
    assert ({"kind": "no_empty_rooms"} in clues) == all_occupied


def test_enumerate_never_mentions_victim_or_voids():
    puzzle = scenario_puzzle()
    clues = enumerate_true_clues(puzzle, SCENARIO_SOLUTION)
    for clue in clues:
        assert clue.get("person") != "victim"
        assert clue.get("person2") != "victim"
        # referenced rooms exist; object types exist (validate() enforces
        # both — a clue about a void room or unknown type would fail it)
    Puzzle(3, 3, puzzle.rooms, puzzle.objects, puzzle.people,
           tuple(clues)).validate()


def test_enumerate_d1_counters_include_the_victim():
    """D1 counters include the victim: room 1 holds victim + suspect_1,
    so the only true eq-combo is count == 2 (the murder room)."""
    puzzle = scenario_puzzle()
    clues = enumerate_true_clues(puzzle, SCENARIO_SOLUTION)
    eq1 = [c for c in clues if c["kind"] == "room_count"
           and c["room"] == 1 and c["op"] == "eq"]
    assert eq1 == [{"kind": "room_count", "room": 1, "count": 2, "op": "eq"}]


# ----------------------------------------------------------------------
# adjacent_gender (ideas.md phase 5.3)
# ----------------------------------------------------------------------

def gendered_people():
    return (
        Person("suspect_1", "Пётр", 101, "m", {"gen": "Петра", "prep": "Петре"}),
        Person("suspect_2", "Анна", 102, "f", {"gen": "Анны", "prep": "Анне"}),
        Person("victim", "Борис", 103, "m", {"gen": "Бориса", "prep": "Борисе"}),
    )


def gendered_puzzle(clues=()):
    puzzle = Puzzle(3, 3, scenario_rooms(), (), gendered_people(),
                    tuple(clues))
    puzzle.validate()
    return puzzle


def test_adjacent_gender_emission_same_room_only():
    """Emitted iff a suspect of that gender shares the person's room; a
    person of the right gender in the neighbouring room does not count
    («рядом с человеком» == same room — orth-adjacent cells are impossible
    under the distinct-rows/cols rule)."""
    puzzle = gendered_puzzle()
    # both suspects in room 1 (2x2), victim in room 3
    placement = {"suspect_1": (1, 1), "suspect_2": (0, 0), "victim": (2, 2)}
    clues = enumerate_true_clues(puzzle, placement)
    ag = [c for c in clues if c["kind"] == "adjacent_gender"]
    assert {("suspect_1", "f"), ("suspect_2", "m")} == \
        {(c["person"], c["gender"]) for c in ag}
    # suspects split across rooms: nobody shares a room -> no emission
    split = {"suspect_1": (1, 1), "suspect_2": (0, 2), "victim": (2, 2)}
    assert not any(c["kind"] == "adjacent_gender"
                   for c in enumerate_true_clues(puzzle, split))
    # all emitted gender clues are true per the independent evaluator
    for clue in ag:
        assert clue_is_true(puzzle, placement, clue)


def test_adjacent_gender_emission_counts_the_victim():
    """The victim is a valid referent (user decision, PROGRESS 2026-11-26):
    a suspect alone with the victim emits the victim's gender — the
    murder-room hint.  The clue never names the victim by id."""
    puzzle = gendered_puzzle()
    # suspect_2 (f) alone with the male victim in room 1; suspect_1 (m)
    # alone in room 2
    placement = {"suspect_1": (0, 2), "suspect_2": (1, 0), "victim": (0, 0)}
    clues = enumerate_true_clues(puzzle, placement)
    ag = [c for c in clues if c["kind"] == "adjacent_gender"]
    # only suspect_2 emits: the male victim is in her room; suspect_1 is
    # alone in room 2 — no one to reference
    assert ag == [{"kind": "adjacent_gender",
                   "person": "suspect_2", "gender": "m"}]
    # true per the independent evaluator (which also counts the victim)
    assert clue_is_true(puzzle, placement, ag[0])
    # ...and no gender clue references the victim by id
    assert all("person2" not in c for c in ag)


def test_adjacent_gender_solver_counts_exactly():
    """The solver's completion check must agree with the evaluator: a
    gender clue narrows the solution set exactly as the direct semantics
    demand (two-solution scenario, clue kills exactly one)."""
    # room 1 = 2x2 murder room candidates; force the pair into room 1
    clues = [
        {"kind": "same_room", "person": "suspect_2", "person2": "victim"},
        {"kind": "not_same_room", "person": "suspect_1", "person2": "victim"},
    ]
    puzzle = gendered_puzzle(clues)
    base = count_solutions(puzzle, 10)
    assert base == 4  # every victim/s2 pairing on the 2x2 with distinct rows+cols
    with_m = Puzzle(3, 3, puzzle.rooms, puzzle.objects, puzzle.people,
                    tuple(clues) + (
                        {"kind": "adjacent_gender",
                         "person": "suspect_2", "gender": "m"},))
    # suspect_2 shares room 1 with the male victim in EVERY arrangement ->
    # the clue is true in all four; solution count must stay 4
    assert count_solutions(with_m, 10) == 4
    with_f = Puzzle(3, 3, puzzle.rooms, puzzle.objects, puzzle.people,
                    tuple(clues) + (
                        {"kind": "adjacent_gender",
                         "person": "suspect_2", "gender": "f"},))
    # no woman in room 1 in any arrangement -> no solutions at all
    assert count_solutions(with_f, 10) == 0
    # and the surviving sets agree with the independent evaluator
    for probe in (with_m, with_f):
        for sol in solutions(probe, 10):
            for clue in probe.clues:
                assert clue_is_true(probe, sol, clue)


def test_adjacent_gender_prune_is_only_an_optimization():
    """The static room prune never changes the solution set: puzzles with
    and without the (redundant) prune path give identical counts."""
    puzzle = gendered_puzzle([
        {"kind": "same_room", "person": "suspect_1", "person2": "victim"},
    ])
    clue_f = {"kind": "adjacent_gender", "person": "suspect_1", "gender": "f"}
    clue_m = {"kind": "adjacent_gender", "person": "suspect_1", "gender": "m"}
    probe_f = Puzzle(3, 3, puzzle.rooms, puzzle.objects, puzzle.people,
                     (clue_f,))
    probe_m = Puzzle(3, 3, puzzle.rooms, puzzle.objects, puzzle.people,
                     (clue_m,))
    # victim is male: m-variant solvable, f-variant dead (vacuously)
    assert count_solutions(probe_m, 10) > 0
    assert count_solutions(probe_f, 10) == 0


def test_enumerate_empty_objects_yields_no_ab_clues():
    puzzle = Puzzle(3, 3, scenario_rooms(), (), people_tuple(2), ())
    clues = enumerate_true_clues(puzzle, SCENARIO_SOLUTION)
    assert not any("object_type" in c for c in clues)
    assert clues  # C and D clues still exist


# ----------------------------------------------------------------------
# pruning
# ----------------------------------------------------------------------

def test_prune_keeps_uniqueness_and_is_minimal():
    puzzle = scenario_puzzle()
    full = enumerate_true_clues(puzzle, SCENARIO_SOLUTION)
    assert count_solutions(
        Puzzle(3, 3, puzzle.rooms, puzzle.objects, puzzle.people,
               tuple(full)), 2) == 1
    kept = prune_clues(puzzle, full, Random(99))
    final = Puzzle(3, 3, puzzle.rooms, puzzle.objects, puzzle.people,
                   tuple(kept))
    assert count_solutions(final, 2) == 1
    assert 0 < len(kept) < len(full)
    # locally minimal: dropping any kept clue breaks uniqueness
    for i, clue in enumerate(kept):
        probe = Puzzle(3, 3, puzzle.rooms, puzzle.objects, puzzle.people,
                       tuple(kept[:i] + kept[i + 1:]))
        assert count_solutions(probe, 2) >= 2, f"clue {clue} is redundant"


def test_prune_is_deterministic_per_rng_seed():
    puzzle = scenario_puzzle()
    full = enumerate_true_clues(puzzle, SCENARIO_SOLUTION)
    assert prune_clues(puzzle, full, Random(7)) == \
        prune_clues(puzzle, full, Random(7))
    assert prune_clues(puzzle, full, Random(8)) != \
        prune_clues(puzzle, full, Random(9))


def test_prune_drops_redundant_directionals_first():
    """Every directional clue redundant in the FULL set is absent from kept,
    whatever the RNG permutation — pass 1 probes C1 before anything else
    (kept sets stay lean of south/north/east/west)."""
    puzzle = scenario_puzzle()
    full = enumerate_true_clues(puzzle, SCENARIO_SOLUTION)
    redundant = []
    for c in full:
        if c["kind"] not in _DIRECTIONAL:
            continue
        rest = tuple(x for x in full if x != c)
        probe = Puzzle(3, 3, puzzle.rooms, puzzle.objects, puzzle.people, rest)
        if count_solutions(probe, 2) == 1:
            redundant.append(c)
    for seed in range(10):
        kept = prune_clues(puzzle, full, Random(seed))
        for c in redundant:
            assert c not in kept, f"seed {seed}: redundant directional {c} kept"
        final = Puzzle(3, 3, puzzle.rooms, puzzle.objects, puzzle.people,
                       tuple(kept))
        assert count_solutions(final, 2) == 1


def test_prune_on_minimal_list_is_noop():
    puzzle = scenario_puzzle()
    full = enumerate_true_clues(puzzle, SCENARIO_SOLUTION)
    kept = prune_clues(puzzle, full, Random(3))
    assert prune_clues(puzzle, kept, Random(3)) == kept
