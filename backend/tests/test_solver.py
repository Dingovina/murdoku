"""Tests for murdoku.solver: clue semantics, rules, and limits.

Includes an independent naive brute-force enumerator (direct, per-clue
semantics) used to cross-check the optimized solver on small puzzles.
"""

import pytest

from murdoku.model import ObjectInstance, Person, Puzzle, Room
from murdoku.solver import count_solutions, solutions


# ----------------------------------------------------------------------
# builders
# ----------------------------------------------------------------------

def people_tuple(n_suspects):
    people = [
        Person(f"suspect_{i}", f"Подозреваемый_{i}", i)
        for i in range(1, n_suspects + 1)
    ]
    people.append(Person("victim", "Убитый", 0))
    return tuple(people)


def build(width, height, rooms, objects, people, clues=()):
    puzzle = Puzzle(width, height, tuple(rooms), tuple(objects),
                    tuple(people), tuple(clues))
    puzzle.validate()
    return puzzle


def scenario_rooms():
    """3x3: 2x2 block, then a 2-cell and a 3-cell room."""
    return (
        Room(1, frozenset({(0, 0), (0, 1), (1, 0), (1, 1)})),
        Room(2, frozenset({(0, 2), (1, 2)})),
        Room(3, frozenset({(2, 0), (2, 1), (2, 2)})),
    )


def scenario1(clues=()):
    """Unique solution: s1=(1,1) armchair, s2=(2,2) sofa, victim=(0,0)."""
    objects = (
        ObjectInstance("obj_1", "armchair", frozenset({(1, 1)})),
        ObjectInstance("obj_2", "sofa", frozenset({(2, 2)})),
        ObjectInstance("obj_3", "bed", frozenset({(0, 0), (1, 0)})),
    )
    return build(3, 3, scenario_rooms(), objects, people_tuple(2), clues)


def scenario1b(clues=()):
    """s2 stands ON a bed cell (2,0); own-cell rule makes not_adjacent true."""
    rooms = (
        Room(1, frozenset({(0, 0), (0, 1), (0, 2), (1, 0), (1, 1)})),
        Room(2, frozenset({(1, 2), (2, 2)})),
        Room(3, frozenset({(2, 0), (2, 1)})),
    )
    objects = (
        ObjectInstance("obj_1", "armchair", frozenset({(1, 1)})),
        ObjectInstance("obj_2", "bed", frozenset({(2, 0), (2, 1)})),
    )
    return build(3, 3, rooms, objects, people_tuple(2), clues)


def scenario1c(clues=()):
    """Same as scenario1 but the bed sits at (2,1)-(2,2) under s2."""
    objects = (
        ObjectInstance("obj_1", "armchair", frozenset({(1, 1)})),
        ObjectInstance("obj_2", "bed", frozenset({(2, 1), (2, 2)})),
    )
    return build(3, 3, scenario_rooms(), objects, people_tuple(2), clues)


def void_rooms():
    """3x3 board, center cell (1,1) is a void."""
    return (
        Room(1, frozenset({(0, 0), (0, 1), (1, 0)})),
        Room(2, frozenset({(0, 2), (1, 2), (2, 2)})),
        Room(3, frozenset({(2, 0), (2, 1)})),
    )


def void_scenario(clues=(), objects=()):
    """Exactly 2 solutions without clues (victim/killer swap in room 1)."""
    return build(3, 3, void_rooms(), objects, people_tuple(2), clues)


def staircase_scenario(clues=()):
    """Staircase murder room + L-shaped second room; void at (0,2)."""
    rooms = (
        Room(1, frozenset({(0, 0), (0, 1), (1, 1), (1, 2), (2, 2)})),
        Room(2, frozenset({(1, 0), (2, 0), (2, 1)})),
    )
    objects = (
        ObjectInstance("obj_1", "armchair", frozenset({(1, 2)})),
        ObjectInstance("obj_2", "sofa", frozenset({(2, 0)})),
    )
    return build(3, 3, rooms, objects, people_tuple(2), clues)


def scenario4(clues=()):
    """4x4, N=4; all three rooms occupied -> no_empty_rooms is true."""
    rooms = (
        Room(1, frozenset({(0, 0), (0, 1), (1, 0), (1, 1)})),
        Room(2, frozenset({(2, 2), (2, 3)})),
        Room(3, frozenset({(3, 2), (3, 3)})),
    )
    objects = (
        ObjectInstance("obj_1", "armchair", frozenset({(1, 1)})),
        ObjectInstance("obj_2", "sofa", frozenset({(2, 2)})),
        ObjectInstance("obj_3", "carpet", frozenset({(3, 3)})),
    )
    return build(4, 4, rooms, objects, people_tuple(3), clues)


def sameroom_scenario(clues=()):
    """4x4, N=3: s1 shares the victim's room; s3 has 4 possible cells."""
    rooms = (
        Room(1, frozenset({(0, 0), (0, 1), (1, 0), (1, 1)})),
        Room(2, frozenset({(0, 2), (0, 3), (1, 2), (1, 3),
                           (2, 2), (2, 3), (3, 3)})),
        Room(3, frozenset({(2, 0), (2, 1), (3, 0), (3, 1), (3, 2)})),
    )
    objects = (
        ObjectInstance("obj_1", "armchair", frozenset({(1, 1)})),
        ObjectInstance("obj_2", "sofa", frozenset({(2, 2)})),
    )
    return build(4, 4, rooms, objects, people_tuple(3), clues)


def columns_puzzle(clues=()):
    """3x3, no objects -> many solutions (unclued open layout)."""
    return build(3, 3, scenario_rooms(), (), people_tuple(2), clues)


# ----------------------------------------------------------------------
# independent naive reference implementation
# ----------------------------------------------------------------------

def _neighbors(cell, width, height):
    r, c = cell
    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < height and 0 <= nc < width:
            yield (nr, nc)


def _on(puzzle, cell, otype):
    obj = puzzle.object_at(cell)
    return obj is not None and obj.type == otype


def _near(puzzle, cell, otype):
    """«рядом с O»: adjacent instance of O and own cell has none of O."""
    if _on(puzzle, cell, otype):
        return False
    return any(_on(puzzle, nb, otype)
               for nb in _neighbors(cell, puzzle.width, puzzle.height))


def _rules_ok(puzzle, place):
    """SPEC §3 murder-room rule: victim's room holds exactly one suspect."""
    vroom = puzzle.room_of(place["victim"])
    suspects_in = [pid for pid in puzzle.people_ids()
                   if pid != "victim"
                   and puzzle.room_of(place[pid]).id == vroom.id]
    return len(suspects_in) == 1


def _clue_holds(puzzle, clue, place):
    kind = clue["kind"]
    if kind == "on":
        return _on(puzzle, place[clue["person"]], clue["object_type"])
    if kind == "not_on":
        return not _on(puzzle, place[clue["person"]], clue["object_type"])
    if kind == "adjacent":
        return _near(puzzle, place[clue["person"]], clue["object_type"])
    if kind == "not_adjacent":
        return not _near(puzzle, place[clue["person"]], clue["object_type"])
    if kind == "room_has_object":
        room = puzzle.room_of(place[clue["person"]])
        return any(o.type == clue["object_type"]
                   and puzzle.room_of(next(iter(o.cells))) == room
                   for o in puzzle.objects)
    if kind == "room_not_has_object":
        room = puzzle.room_of(place[clue["person"]])
        return not any(o.type == clue["object_type"]
                       and puzzle.room_of(next(iter(o.cells))) == room
                       for o in puzzle.objects)
    if kind == "south":
        return place[clue["person"]][0] > place[clue["person2"]][0]
    if kind == "north":
        return place[clue["person"]][0] < place[clue["person2"]][0]
    if kind == "east":
        return place[clue["person"]][1] > place[clue["person2"]][1]
    if kind == "west":
        return place[clue["person"]][1] < place[clue["person2"]][1]
    if kind == "same_room":
        return (puzzle.room_of(place[clue["person"]])
                == puzzle.room_of(place[clue["person2"]]))
    if kind == "not_same_room":
        return (puzzle.room_of(place[clue["person"]])
                != puzzle.room_of(place[clue["person2"]]))
    if kind == "room_count":
        cnt = sum(1 for pid in puzzle.people_ids()
                  if puzzle.room_of(place[pid]).id == clue["room"])
        k, op = clue["count"], clue["op"]
        return {"eq": cnt == k, "ne": cnt != k, "gt": cnt > k,
                "ge": cnt >= k, "lt": cnt < k, "le": cnt <= k}[op]
    if kind == "no_empty_rooms":
        occupied = {puzzle.room_of(place[pid]).id
                    for pid in puzzle.people_ids()}
        return all(room.id in occupied for room in puzzle.rooms)
    raise AssertionError(f"naive evaluator: unknown kind {kind!r}")


def naive_solutions(puzzle):
    """Brute force: injective row/col-distinct placements over allowed
    cells, filtered by rules and direct clue semantics."""
    people = puzzle.people_ids()
    cells = sorted(puzzle.allowed_cells())
    results = []
    place = {}

    def rec(i, used_rows, used_cols):
        if i == len(people):
            if _rules_ok(puzzle, place) and all(
                    _clue_holds(puzzle, clue, place)
                    for clue in puzzle.clues):
                results.append(dict(place))
            return
        pid = people[i]
        for cell in cells:
            if cell[0] in used_rows or cell[1] in used_cols:
                continue
            place[pid] = cell
            rec(i + 1, used_rows | {cell[0]}, used_cols | {cell[1]})
            del place[pid]

    rec(0, frozenset(), frozenset())
    return results


def assert_agrees_with_naive(puzzle):
    expected = sorted(tuple(sorted(s.items()))
                      for s in naive_solutions(puzzle))
    got = sorted(tuple(sorted(s.items())) for s in solutions(puzzle, 10 ** 6))
    assert got == expected
    assert count_solutions(puzzle, 10 ** 6) == len(expected)
    assert count_solutions(puzzle) == min(2, len(expected))


SOLUTION1 = {"suspect_1": (1, 1), "suspect_2": (2, 2), "victim": (0, 0)}
SOLUTION1B = {"suspect_1": (1, 1), "suspect_2": (2, 0), "victim": (0, 2)}
SOLUTION1C = {"suspect_1": (1, 1), "suspect_2": (2, 2), "victim": (0, 0)}


def clue(kind, **fields):
    return {"kind": kind, **fields}


def assert_unique(puzzle, expected):
    """Puzzle has exactly one solution and it equals ``expected``."""
    assert count_solutions(puzzle) == 1
    got = list(solutions(puzzle, 5))
    assert got == [expected]
    # every solver output satisfies the independent checker
    assert _rules_ok(puzzle, got[0])
    assert all(_clue_holds(puzzle, c, got[0]) for c in puzzle.clues)


BASE1 = (clue("on", person="suspect_1", object_type="armchair"),
         clue("on", person="suspect_2", object_type="sofa"))
BASE1B = (clue("on", person="suspect_1", object_type="armchair"),
          clue("on", person="suspect_2", object_type="bed"),
          clue("west", person="suspect_2", person2="suspect_1"))
BASE1C = (clue("on", person="suspect_1", object_type="armchair"),
          clue("on", person="suspect_2", object_type="bed"),
          clue("south", person="suspect_2", person2="suspect_1"))


class TestAOnNotOn:
    def test_on_positive(self):
        assert_unique(scenario1(BASE1), SOLUTION1)

    def test_on_negative_polarity(self):
        # s1 is pinned to the armchair, so "on bed" is unsatisfiable
        assert count_solutions(scenario1(
            BASE1 + (clue("on", person="suspect_1", object_type="bed"),))) == 0

    def test_not_on(self):
        clues = BASE1 + (clue("not_on", person="suspect_2",
                              object_type="bed"),)
        assert_unique(scenario1(clues), SOLUTION1)

    def test_not_on_violated(self):
        # s2 stands on the bed in scenario1c -> not_on bed fails
        assert count_solutions(scenario1c(
            BASE1C + (clue("not_on", person="suspect_2",
                           object_type="bed"),))) == 0

    def test_full_object_blocks_on(self):
        # the only cell with the table is not an allowed cell at all
        rooms = (
            Room(1, frozenset({(0, 0), (1, 0), (2, 0)})),
            Room(2, frozenset({(0, 1), (1, 1), (2, 1)})),
            Room(3, frozenset({(0, 2), (1, 2), (2, 2)})),
        )
        objects = (ObjectInstance("obj_1", "table", frozenset({(1, 1)})),)
        puzzle = build(3, 3, rooms, objects, people_tuple(2),
                       (clue("on", person="suspect_1", object_type="table"),))
        assert count_solutions(puzzle) == 0
        assert (1, 1) not in puzzle.allowed_cells()
        assert_agrees_with_naive(puzzle)


class TestAAdjacent:
    """«рядом с O»: some orth-adjacent cell has O and the own cell has not."""

    def test_adjacent_positive(self):
        # s1=(1,1) neighbours bed cell (1,0) and stands on the armchair
        assert_unique(scenario1(BASE1 + (
            clue("adjacent", person="suspect_1", object_type="bed"),)),
            SOLUTION1)

    def test_adjacent_negative_polarity(self):
        # s2=(2,2) has no bed neighbours
        assert count_solutions(scenario1(BASE1 + (
            clue("adjacent", person="suspect_2", object_type="bed"),))) == 0

    def test_not_adjacent_positive(self):
        assert_unique(scenario1(BASE1 + (
            clue("not_adjacent", person="suspect_2", object_type="bed"),)),
            SOLUTION1)

    def test_not_adjacent_violated_when_near(self):
        assert count_solutions(scenario1(BASE1 + (
            clue("not_adjacent", person="suspect_1", object_type="bed"),)),
            ) == 0

    def test_standing_on_bed_is_not_near_first_cell(self):
        # scenario1b: s2 stands on bed cell (2,0); the other bed cell (2,1)
        # is orth-adjacent -> only the own-cell exclusion makes it "not near"
        clues = BASE1B + (clue("not_adjacent", person="suspect_2",
                               object_type="bed"),)
        assert_unique(scenario1b(clues), SOLUTION1B)
        # wrong semantics ("near" ignores own cell) would give 0 solutions
        assert count_solutions(scenario1b(
            BASE1B + (clue("adjacent", person="suspect_2",
                           object_type="bed"),))) == 0

    def test_standing_on_bed_is_not_near_second_cell(self):
        # scenario1c: s2 stands on bed cell (2,2); bed cell (2,1) adjacent
        clues = BASE1C + (clue("not_adjacent", person="suspect_2",
                               object_type="bed"),)
        assert_unique(scenario1c(clues), SOLUTION1C)
        assert count_solutions(scenario1c(
            BASE1C + (clue("adjacent", person="suspect_2",
                           object_type="bed"),))) == 0


class TestBRoomHasObject:
    def test_room_has_positive(self):
        assert_unique(scenario1(BASE1 + (
            clue("room_has_object", person="suspect_1",
                 object_type="bed"),)), SOLUTION1)

    def test_room_has_negative_polarity(self):
        assert count_solutions(scenario1(BASE1 + (
            clue("room_has_object", person="suspect_2",
                 object_type="bed"),))) == 0

    def test_room_not_has_positive(self):
        assert_unique(scenario1(BASE1 + (
            clue("room_not_has_object", person="suspect_2",
                 object_type="bed"),)), SOLUTION1)

    def test_room_not_has_violated(self):
        assert count_solutions(scenario1(BASE1 + (
            clue("room_not_has_object", person="suspect_1",
                 object_type="bed"),))) == 0


class TestCRelative:
    @pytest.mark.parametrize("kind,person,person2,ok", [
        ("south", "suspect_2", "suspect_1", True),   # 2 > 1
        ("south", "suspect_1", "suspect_2", False),  # 1 > 2 is false
        ("north", "suspect_1", "suspect_2", True),   # 1 < 2
        ("north", "suspect_2", "suspect_1", False),
        ("east", "suspect_2", "suspect_1", True),    # col 2 > col 1
        ("east", "suspect_1", "suspect_2", False),
        ("west", "suspect_1", "suspect_2", True),    # col 1 < col 2
        ("west", "suspect_2", "suspect_1", False),
    ])
    def test_direction(self, kind, person, person2, ok):
        puzzle = scenario1(BASE1 + (clue(kind, person=person,
                                         person2=person2),))
        assert count_solutions(puzzle) == (1 if ok else 0)
        assert_agrees_with_naive(puzzle)


class TestCSameRoom:
    def test_same_room_false_here(self):
        # s1 in room 1, s2 in room 3
        assert count_solutions(scenario1(BASE1 + (
            clue("same_room", person="suspect_1",
                 person2="suspect_2"),))) == 0

    def test_not_same_room_true(self):
        assert_unique(scenario1(BASE1 + (
            clue("not_same_room", person="suspect_1",
                 person2="suspect_2"),)), SOLUTION1)

    def test_same_room_filters(self):
        # 4x4, N=3 suspects: without a room clue there are 4 placements of
        # s3; same_room(s2, s3) keeps exactly one of them.
        base = (clue("on", person="suspect_1", object_type="armchair"),
                clue("on", person="suspect_2", object_type="sofa"))
        free = sameroom_scenario(base)
        assert count_solutions(free, 10) == 3
        same = sameroom_scenario(base + (
            clue("same_room", person="suspect_2", person2="suspect_3"),))
        assert count_solutions(same) == 1
        assert_agrees_with_naive(free)
        assert_agrees_with_naive(same)

    def test_not_same_room_filters(self):
        base = (clue("on", person="suspect_1", object_type="armchair"),
                clue("on", person="suspect_2", object_type="sofa"))
        diff = sameroom_scenario(base + (
            clue("not_same_room", person="suspect_2",
                 person2="suspect_3"),))
        assert count_solutions(diff) == 2
        assert_agrees_with_naive(diff)

    def test_same_room_of_two_suspects_needs_third_killer(self):
        # N=3: both suspects in one room -> no suspect left to share the
        # victim's room -> zero solutions
        assert count_solutions(scenario1(BASE1 + (
            clue("same_room", person="suspect_1",
                 person2="suspect_2"),))) == 0
        assert_agrees_with_naive(scenario1(BASE1 + (
            clue("same_room", person="suspect_1", person2="suspect_2"),)))


class TestDRoomCount:
    @pytest.mark.parametrize("op,k,ok", [
        ("eq", 2, True), ("ne", 3, True), ("gt", 1, True),
        ("ge", 2, True), ("lt", 3, True), ("le", 2, True),
        ("eq", 1, False), ("eq", 3, False), ("ne", 2, False),
        ("gt", 2, False), ("ge", 3, False), ("lt", 2, False),
        ("le", 1, False),
    ])
    def test_ops_on_murder_room(self, op, k, ok):
        # room 1 holds victim + suspect_1 = 2 people (victim counted!)
        puzzle = scenario1(BASE1 + (
            clue("room_count", room=1, count=k, op=op),))
        assert count_solutions(puzzle) == (1 if ok else 0)
        if ok:
            assert_agrees_with_naive(puzzle)

    def test_victim_is_counted(self):
        # room 1 holds 2 people only because the victim counts;
        # if the victim were ignored the clue "exactly 1" would hold
        puzzle = scenario1(BASE1 + (
            clue("room_count", room=1, count=2, op="eq"),))
        assert count_solutions(puzzle) == 1
        puzzle = scenario1(BASE1 + (
            clue("room_count", room=1, count=1, op="eq"),))
        assert count_solutions(puzzle) == 0

    def test_other_room_counts(self):
        puzzle = scenario1(BASE1 + (
            clue("room_count", room=3, count=1, op="eq"),
            clue("room_count", room=2, count=0, op="eq"),
            clue("room_count", room=1, count=2, op="eq"),))
        assert_unique(puzzle, SOLUTION1)
        assert_agrees_with_naive(puzzle)


class TestNoEmptyRooms:
    def test_true_keeps_solution(self):
        # 4x4 N=4 scenario: all three rooms are occupied
        clues = (clue("on", person="suspect_1", object_type="armchair"),
                 clue("on", person="suspect_2", object_type="sofa"),
                 clue("on", person="suspect_3", object_type="carpet"))
        assert_unique(scenario4(clues + (clue("no_empty_rooms"),)),
                      {"suspect_1": (1, 1), "suspect_2": (2, 2),
                       "suspect_3": (3, 3), "victim": (0, 0)})
        assert_agrees_with_naive(scenario4(clues + (clue("no_empty_rooms"),)))

    def test_false_rejects_everything(self):
        # scenario1 leaves room 2 empty, so the clue cannot hold
        assert count_solutions(scenario1(
            BASE1 + (clue("no_empty_rooms"),))) == 0
        assert_agrees_with_naive(scenario1(
            BASE1 + (clue("no_empty_rooms"),)))


class TestMurderRoom:
    def test_exactly_one_suspect_is_fine(self):
        # scenario1: victim (0,0) and suspect_1 (1,1) share room 1
        assert_unique(scenario1(BASE1), SOLUTION1)

    def test_zero_suspects_in_victim_room(self):
        # force room 1 (the victim's room) to hold only the victim
        puzzle = scenario1(BASE1 + (
            clue("room_count", room=1, count=1, op="eq"),))
        assert count_solutions(puzzle) == 0
        assert_agrees_with_naive(puzzle)

    def test_two_suspects_in_victim_room(self):
        # staircase room: pins force all three people into room 1
        rooms = (
            Room(1, frozenset({(0, 0), (0, 1), (1, 1), (1, 2), (2, 2)})),
            Room(2, frozenset({(1, 0), (2, 0), (2, 1)})),
        )
        objects = (
            ObjectInstance("obj_1", "armchair", frozenset({(1, 1)})),
            ObjectInstance("obj_2", "sofa", frozenset({(2, 2)})),
        )
        puzzle = build(3, 3, rooms, objects, people_tuple(2), BASE1)
        assert count_solutions(puzzle) == 0
        assert_agrees_with_naive(puzzle)

    def test_single_room_board_has_no_solutions(self):
        # murder room must hold exactly one suspect, but everyone is in it
        rooms = (Room(1, frozenset({(r, c) for r in range(3)
                                    for c in range(3)})),)
        puzzle = build(3, 3, rooms, (), people_tuple(2), ())
        assert count_solutions(puzzle) == 0
        assert_agrees_with_naive(puzzle)

    def test_staircase_positive(self):
        # killer in the staircase room, second suspect in room 2
        clues = (clue("on", person="suspect_1", object_type="armchair"),
                 clue("on", person="suspect_2", object_type="sofa"))
        assert_unique(staircase_scenario(clues),
                      {"suspect_1": (1, 2), "suspect_2": (2, 0),
                       "victim": (0, 1)})
        assert_agrees_with_naive(staircase_scenario(clues))


class TestGeometry:
    def test_row_conflict_rejected(self):
        # pins put both suspects into row 0 of a 3-row board
        rooms = (
            Room(1, frozenset({(0, 0), (1, 0), (2, 0)})),
            Room(2, frozenset({(0, 1), (1, 1), (2, 1)})),
            Room(3, frozenset({(0, 2), (1, 2), (2, 2)})),
        )
        objects = (
            ObjectInstance("obj_1", "armchair", frozenset({(0, 1)})),
            ObjectInstance("obj_2", "sofa", frozenset({(0, 2)})),
        )
        puzzle = build(3, 3, rooms, objects, people_tuple(2), BASE1)
        assert count_solutions(puzzle) == 0
        assert_agrees_with_naive(puzzle)

    def test_column_conflict_rejected(self):
        # pins put both suspects into column 1
        rooms = (
            Room(1, frozenset({(0, 0), (1, 0), (2, 0)})),
            Room(2, frozenset({(0, 1), (1, 1), (2, 1)})),
            Room(3, frozenset({(0, 2), (1, 2), (2, 2)})),
        )
        objects = (
            ObjectInstance("obj_1", "armchair", frozenset({(1, 1)})),
            ObjectInstance("obj_2", "sofa", frozenset({(2, 1)})),
        )
        puzzle = build(3, 3, rooms, objects, people_tuple(2), BASE1)
        assert count_solutions(puzzle) == 0
        assert_agrees_with_naive(puzzle)

    def test_distinct_rows_and_cols_admitted(self):
        puzzle = scenario1(BASE1)
        assert count_solutions(puzzle) >= 1

    def test_void_cells_excluded(self):
        puzzle = void_scenario()
        sols = list(solutions(puzzle, 10))
        assert sols
        for sol in sols:
            assert all(cell != (1, 1) for cell in sol.values())
            assert all(cell in puzzle.allowed_cells()
                       for cell in sol.values())

    def test_four_solutions_without_clues(self):
        # void board: victim/killer swap inside room 1, suspects swappable
        assert len(naive_solutions(void_scenario())) == 4
        assert count_solutions(void_scenario(), 10) == 4

    def test_objects_and_voids_combined(self):
        objects = (
            ObjectInstance("obj_1", "bed", frozenset({(0, 0), (1, 0)})),
            ObjectInstance("obj_2", "table", frozenset({(1, 2)})),
            ObjectInstance("obj_3", "carpet", frozenset({(2, 0)})),
        )
        puzzle = void_scenario(objects=objects)
        assert_agrees_with_naive(puzzle)
        assert count_solutions(puzzle, 10) == 4


class TestLimitsAndDeterminism:
    def test_limit_zero(self):
        puzzle = void_scenario()
        assert count_solutions(puzzle, 0) == 0
        assert list(solutions(puzzle, 0)) == []

    def test_limit_one_on_two_solution_puzzle(self):
        puzzle = void_scenario()
        assert count_solutions(puzzle, 1) == 1
        assert len(list(solutions(puzzle, 1))) == 1

    def test_limit_two_on_two_solution_puzzle(self):
        puzzle = void_scenario()
        assert count_solutions(puzzle, 2) == 2
        assert len(list(solutions(puzzle, 2))) == 2

    def test_limit_above_solution_count(self):
        puzzle = void_scenario()
        assert count_solutions(puzzle, 100) == 4
        assert count_solutions(puzzle, 10 ** 6) == 4
        assert count_solutions(puzzle, 3) == 3

    def test_default_limit_is_two(self):
        puzzle = columns_puzzle()
        assert count_solutions(puzzle) == 2

    def test_solutions_deterministic_order(self):
        puzzle = columns_puzzle()
        first = list(solutions(puzzle, 10))
        second = list(solutions(puzzle, 10))
        assert first == second
        assert len(first) >= 2
        # dicts map every person to a distinct cell
        for sol in first:
            assert set(sol) == set(puzzle.people_ids())
            assert len(set(sol.values())) == len(sol)

    def test_zero_solution_puzzle(self):
        puzzle = scenario1(BASE1 + (clue("no_empty_rooms"),))
        assert count_solutions(puzzle) == 0
        assert list(solutions(puzzle, 5)) == []

    def test_empty_clues_column_puzzle_agrees(self):
        puzzle = columns_puzzle()
        assert_agrees_with_naive(puzzle)


class TestAgainstNaive:
    """Cross-check the optimized solver against the naive enumerator."""

    def test_scenario1_with_all_true_clues(self):
        clues = BASE1 + (
            clue("adjacent", person="suspect_1", object_type="bed"),
            clue("not_adjacent", person="suspect_2", object_type="bed"),
            clue("not_on", person="suspect_1", object_type="carpet"),
            clue("not_on", person="suspect_2", object_type="bed"),
            clue("room_has_object", person="suspect_1", object_type="bed"),
            clue("room_not_has_object", person="suspect_2",
                 object_type="bed"),
            clue("south", person="suspect_2", person2="suspect_1"),
            clue("east", person="suspect_2", person2="suspect_1"),
            clue("not_same_room", person="suspect_1", person2="suspect_2"),
            clue("room_count", room=1, count=2, op="eq"),
            clue("room_count", room=3, count=1, op="ge"),
            clue("room_count", room=2, count=0, op="le"),
        )
        puzzle = scenario1(clues)
        assert_unique(puzzle, SOLUTION1)
        assert_agrees_with_naive(puzzle)

    def test_bed_scenarios(self):
        for base, factory in ((BASE1B, scenario1b), (BASE1C, scenario1c)):
            puzzle = factory(base)
            assert_agrees_with_naive(puzzle)
            assert count_solutions(puzzle) == 1

    def test_void_puzzles(self):
        assert_agrees_with_naive(void_scenario())
        assert_agrees_with_naive(void_scenario(
            clues=(clue("south", person="suspect_1", person2="victim"),)))
        # south(s1, victim) requires s1 below the victim, keeping 3 of the
        # 4 placements (the two suspects are otherwise interchangeable)
        assert count_solutions(void_scenario(
            clues=(clue("south", person="suspect_1",
                        person2="victim"),)), 10) == 3

    def test_staircase_and_four_by_four(self):
        assert_agrees_with_naive(staircase_scenario())
        clues = (clue("on", person="suspect_1", object_type="armchair"),
                 clue("on", person="suspect_2", object_type="sofa"),
                 clue("on", person="suspect_3", object_type="carpet"))
        assert_agrees_with_naive(scenario4(clues))
        assert_agrees_with_naive(scenario4(clues + (clue("no_empty_rooms"),)))
        assert_agrees_with_naive(scenario4(clues + (
            clue("room_count", room=1, count=2, op="eq"),
            clue("room_count", room=2, count=1, op="eq"),
            clue("room_count", room=3, count=1, op="eq"),)))

    def test_unclued_four_by_four(self):
        # regression: a weakly clued board where every candidate mask stays
        # larger than the number of people — MRV must still select a person
        # (candidate counts are cell counts, not person counts)
        rooms = (
            Room(1, frozenset({(0, 0), (0, 1), (1, 0), (1, 1)})),
            Room(2, frozenset({(r, c) for r in range(5) for c in range(5)
                               if (r, c) not in {(0, 0), (0, 1), (1, 0),
                                                 (1, 1)}})),
        )
        puzzle = build(5, 5, rooms, (), people_tuple(4), ())
        assert_agrees_with_naive(puzzle)
        assert count_solutions(puzzle, 10) >= 2

    def test_object_heavy_puzzle(self):
        objects = (
            ObjectInstance("obj_1", "bed", frozenset({(0, 0), (1, 0)})),
            ObjectInstance("obj_2", "table", frozenset({(1, 2)})),
            ObjectInstance("obj_3", "tv", frozenset({(0, 2)})),
            ObjectInstance("obj_4", "carpet", frozenset({(2, 1)})),
        )
        puzzle = build(3, 3, scenario_rooms(), objects, people_tuple(2), (
            clue("room_has_object", person="suspect_1", object_type="bed"),
            clue("on", person="suspect_1", object_type="bed"),
            clue("not_adjacent", person="suspect_2", object_type="tv"),
            clue("room_count", room=1, count=2, op="eq"),
            clue("room_count", room=3, count=1, op="eq"),
            clue("room_count", room=2, count=0, op="eq"),
        ))
        assert_agrees_with_naive(puzzle)
        assert count_solutions(puzzle, 10) == 2
