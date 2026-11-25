"""Tests for murdoku.model: registry, validation, (de)serialization."""

import dataclasses

import pytest

from murdoku.model import (
    OBJECT_TYPES,
    OBJECT_TYPE_IDS,
    ObjectInstance,
    ObjectTypeDef,
    Person,
    Puzzle,
    PuzzleValidationError,
    Room,
)


def make_rooms():
    """3x3 board, three vertical rooms."""
    return (
        Room(1, frozenset({(0, 0), (1, 0), (2, 0)})),
        Room(2, frozenset({(0, 1), (1, 1), (2, 1)})),
        Room(3, frozenset({(0, 2), (1, 2), (2, 2)})),
    )


def make_objects():
    return (
        ObjectInstance("obj_1", "table", frozenset({(0, 1)})),
        ObjectInstance("obj_2", "bed", frozenset({(1, 2), (2, 2)})),
        ObjectInstance("obj_3", "carpet", frozenset({(2, 0)})),
    )


def make_people():
    return (
        Person("suspect_1", "Подозреваемый_1", 1),
        Person("suspect_2", "Подозреваемый_2", 2),
        Person("victim", "Убитый", 3),
    )


def make_clues():
    """One of every clue kind, all valid for the fixture."""
    return (
        {"kind": "on", "person": "suspect_1", "object_type": "carpet"},
        {"kind": "not_on", "person": "suspect_2", "object_type": "table"},
        {"kind": "adjacent", "person": "suspect_1", "object_type": "bed"},
        {"kind": "not_adjacent", "person": "suspect_2",
         "object_type": "wardrobe"},
        {"kind": "room_has_object", "person": "suspect_1",
         "object_type": "table"},
        {"kind": "room_not_has_object", "person": "suspect_2",
         "object_type": "bed"},
        {"kind": "south", "person": "suspect_1", "person2": "suspect_2"},
        {"kind": "north", "person": "suspect_2", "person2": "suspect_1"},
        {"kind": "east", "person": "suspect_1", "person2": "suspect_2"},
        {"kind": "west", "person": "suspect_2", "person2": "suspect_1"},
        {"kind": "same_room", "person": "suspect_1", "person2": "suspect_2"},
        {"kind": "not_same_room", "person": "suspect_1", "person2": "victim"},
        {"kind": "room_count", "room": 2, "count": 1, "op": "eq"},
        {"kind": "room_count", "room": 3, "count": 0, "op": "le"},
        {"kind": "no_empty_rooms"},
    )


def make_puzzle() -> Puzzle:
    return Puzzle(3, 3, make_rooms(), make_objects(), make_people(),
                  make_clues())


class TestRegistry:
    def test_registry_contents(self):
        expected = {
            # id: (cls, size, mergeable)
            "table": ("full", 1, True),
            "tv": ("full", 1, False),
            "wardrobe": ("full", 1, False),
            "fridge": ("full", 1, False),
            "bed": ("partial", 2, False),
            "carpet": ("partial", 1, True),
            "armchair": ("partial", 1, False),
            "sofa": ("partial", 1, False),
        }
        assert OBJECT_TYPE_IDS == tuple(expected)
        assert list(OBJECT_TYPES) == list(expected)
        for oid, (cls, size, mergeable) in expected.items():
            typedef = OBJECT_TYPES[oid]
            assert typedef == ObjectTypeDef(oid, cls, size, mergeable)

    def test_frozen_dataclasses(self):
        room = make_rooms()[0]
        with pytest.raises(dataclasses.FrozenInstanceError):
            room.id = 5
        person = make_people()[0]
        with pytest.raises(dataclasses.FrozenInstanceError):
            person.name = "x"


class TestValidPuzzles:
    def test_fixture_validates(self):
        make_puzzle().validate()

    def test_minimal_puzzle_validates(self):
        puzzle = Puzzle(3, 3, make_rooms(), (), make_people(), ())
        puzzle.validate()

    def test_corner_property(self):
        rooms = make_rooms()
        assert rooms[0].corner == (0, 0)
        assert rooms[1].corner == (0, 1)
        assert rooms[2].corner == (0, 2)


def assert_invalid(puzzle: Puzzle, fragment: str | None = None):
    with pytest.raises(PuzzleValidationError) as exc:
        puzzle.validate()
    if fragment is not None:
        assert fragment in str(exc.value)


class TestValidateDimensions:
    def test_zero_width(self):
        assert_invalid(dataclasses.replace(make_puzzle(), width=0))

    def test_zero_height(self):
        assert_invalid(dataclasses.replace(make_puzzle(), height=0))

    def test_negative_width(self):
        assert_invalid(dataclasses.replace(make_puzzle(), width=-2))


class TestValidateRooms:
    def test_room_cell_out_of_bounds(self):
        rooms = (
            Room(1, frozenset({(0, 0), (3, 0), (2, 0)})),
            Room(2, frozenset({(0, 1), (1, 1), (2, 1)})),
            Room(3, frozenset({(0, 2), (1, 2), (2, 2)})),
        )
        assert_invalid(dataclasses.replace(make_puzzle(), rooms=rooms))

    def test_room_ids_not_dense(self):
        rooms = (
            Room(1, frozenset({(0, 0), (1, 0), (2, 0)})),
            Room(3, frozenset({(0, 1), (1, 1), (2, 1)})),
        )
        puzzle = Puzzle(3, 3, rooms, (), make_people(), ())
        assert_invalid(puzzle, "dense")

    def test_rooms_not_sorted_by_corner(self):
        r1, r2, r3 = make_rooms()
        rooms = (r3, r2, r1)  # ids stay in tuple order -> density ok, order bad
        rooms = (Room(1, r3.cells), Room(2, r2.cells), Room(3, r1.cells))
        assert_invalid(
            dataclasses.replace(make_puzzle(), rooms=rooms), "corner")

    def test_overlapping_rooms(self):
        rooms = (
            Room(1, frozenset({(0, 0), (1, 0), (2, 0), (1, 1)})),
            Room(2, frozenset({(0, 1), (1, 1), (2, 1)})),
            Room(3, frozenset({(0, 2), (1, 2), (2, 2)})),
        )
        assert_invalid(
            dataclasses.replace(make_puzzle(), rooms=rooms), "more than one")

    def test_disconnected_room(self):
        # two separate blobs inside the board bounds -> not one room
        rooms = (
            Room(1, frozenset({(0, 0), (0, 1), (2, 0), (2, 1)})),
            Room(2, frozenset({(0, 2), (1, 2), (2, 2)})),
            Room(3, frozenset({(1, 0), (1, 1)})),
        )
        assert_invalid(
            dataclasses.replace(make_puzzle(), rooms=rooms), "connected")

    def test_diagonal_cells_are_not_connected(self):
        # diagonal adjacency does not connect rooms (orth-only per SPEC §1)
        rooms = (
            Room(1, frozenset({(0, 0), (1, 1)})),
            Room(2, frozenset({(0, 2), (1, 2), (2, 2)})),
            Room(3, frozenset({(2, 0), (2, 1)})),
        )
        assert_invalid(
            dataclasses.replace(make_puzzle(), rooms=rooms), "connected")

    def test_connected_rooms_still_pass(self):
        make_puzzle().validate()
        void_puzzle().validate()


def void_rooms():
    """3x3 board with the center cell (1, 1) excluded from the play field."""
    return (
        Room(1, frozenset({(0, 0), (0, 1), (1, 0)})),
        Room(2, frozenset({(0, 2), (1, 2), (2, 2)})),
        Room(3, frozenset({(2, 0), (2, 1)})),
    )


def void_puzzle(objects=(), clues=()) -> Puzzle:
    return Puzzle(3, 3, void_rooms(), objects, make_people(), clues)


class TestValidateObjects:
    def test_unknown_type(self):
        objects = (ObjectInstance("obj_1", "bathtub", frozenset({(0, 1)})),)
        assert_invalid(
            dataclasses.replace(make_puzzle(), objects=objects), "unknown")

    def test_overlapping_objects(self):
        objects = (
            ObjectInstance("obj_1", "table", frozenset({(0, 1)})),
            ObjectInstance("obj_2", "tv", frozenset({(0, 1)})),
        )
        assert_invalid(
            dataclasses.replace(make_puzzle(), objects=objects), "object")

    def test_object_spans_two_rooms(self):
        objects = (
            ObjectInstance("obj_1", "bed", frozenset({(1, 1), (1, 2)})),
        )
        assert_invalid(
            dataclasses.replace(make_puzzle(), objects=objects), "rooms")

    def test_bed_not_adjacent(self):
        objects = (ObjectInstance("obj_1", "bed",
                                  frozenset({(0, 2), (2, 2)})),)
        assert_invalid(
            dataclasses.replace(make_puzzle(), objects=objects), "adjacent")

    def test_bed_single_cell(self):
        objects = (ObjectInstance("obj_1", "bed", frozenset({(1, 2)})),)
        assert_invalid(
            dataclasses.replace(make_puzzle(), objects=objects), "exactly")

    def test_bed_three_cells(self):
        objects = (ObjectInstance("obj_1", "bed",
                                  frozenset({(1, 2), (2, 2), (0, 2)})),)
        assert_invalid(
            dataclasses.replace(make_puzzle(), objects=objects), "exactly")

    def test_object_cell_out_of_bounds(self):
        objects = (ObjectInstance("obj_1", "table", frozenset({(5, 5)})),)
        assert_invalid(
            dataclasses.replace(make_puzzle(), objects=objects), "bounds")

    def test_object_cell_on_void(self):
        objects = (ObjectInstance("obj_1", "table", frozenset({(1, 1)})),)
        assert_invalid(void_puzzle(objects), "void")

    def test_object_ids_not_dense(self):
        objects = (
            ObjectInstance("obj_2", "table", frozenset({(0, 1)})),
            ObjectInstance("obj_3", "carpet", frozenset({(2, 0)})),
        )
        assert_invalid(
            dataclasses.replace(make_puzzle(), objects=objects), "dense")


class TestValidatePeople:
    def test_too_few_people(self):
        people = (
            Person("suspect_1", "Подозреваемый_1", 1),
            Person("victim", "Убитый", 2),
        )
        assert_invalid(dataclasses.replace(make_puzzle(), people=people))

    def test_suspects_out_of_order(self):
        people = (
            Person("suspect_2", "Подозреваемый_2", 1),
            Person("suspect_1", "Подозреваемый_1", 2),
            Person("victim", "Убитый", 3),
        )
        assert_invalid(dataclasses.replace(make_puzzle(), people=people))

    def test_suspect_gap(self):
        people = (
            Person("suspect_1", "Подозреваемый_1", 1),
            Person("suspect_3", "Подозреваемый_3", 2),
            Person("victim", "Убитый", 3),
        )
        assert_invalid(dataclasses.replace(make_puzzle(), people=people))

    def test_victim_not_last(self):
        people = (
            Person("victim", "Убитый", 3),
            Person("suspect_1", "Подозреваемый_1", 1),
            Person("suspect_2", "Подозреваемый_2", 2),
        )
        assert_invalid(dataclasses.replace(make_puzzle(), people=people))

    def test_two_victims(self):
        people = (
            Person("suspect_1", "Подозреваемый_1", 1),
            Person("victim", "Убитый", 3),
            Person("victim", "Убитый", 4),
        )
        assert_invalid(dataclasses.replace(make_puzzle(), people=people))

    def test_duplicate_person_name_rejected(self):
        people = (
            Person("suspect_1", "Анна", 1),
            Person("suspect_2", "Анна", 2),
            Person("victim", "Убитый", 3),
        )
        assert_invalid(dataclasses.replace(make_puzzle(), people=people),
                       "duplicate")

    def test_empty_person_name_rejected(self):
        people = (
            Person("suspect_1", "", 1),
            Person("suspect_2", "Борис", 2),
            Person("victim", "Вера", 3),
        )
        assert_invalid(dataclasses.replace(make_puzzle(), people=people),
                       "non-empty")

    def test_free_form_names_validate(self):
        """Since phase 5 names come from the generator pool; any distinct
        non-empty names are valid (legacy placeholders included)."""
        people = (
            Person("suspect_1", "Анна", 1, "f",
                   {"gen": "Анны", "prep": "Анне"}),
            Person("suspect_2", "Подозреваемый_2", 2),
            Person("victim", "Пётр", 3, "m", {"gen": "Петра"}),
        )
        dataclasses.replace(make_puzzle(), people=people).validate()

    def test_bad_gender_rejected(self):
        people = (
            Person("suspect_1", "Анна", 1, "x"),
            Person("suspect_2", "Борис", 2),
            Person("victim", "Вера", 3),
        )
        assert_invalid(dataclasses.replace(make_puzzle(), people=people),
                       "gender")

    def test_bad_person_forms_rejected(self):
        people = (
            Person("suspect_1", "Анна", 1, "f",
                   {"gen": "Анны", "voc": "Анн"}),
            Person("suspect_2", "Борис", 2),
            Person("victim", "Вера", 3),
        )
        assert_invalid(dataclasses.replace(make_puzzle(), people=people),
                       "form keys")

    def test_non_string_form_rejected(self):
        people = (
            Person("suspect_1", "Анна", 1, "f", {"gen": 5}),
            Person("suspect_2", "Борис", 2),
            Person("victim", "Вера", 3),
        )
        assert_invalid(dataclasses.replace(make_puzzle(), people=people),
                       "non-empty string")

    def test_duplicate_room_name_rejected(self):
        rooms = (
            Room(1, frozenset({(0, 0), (1, 0), (2, 0)}), "Спальня"),
            Room(2, frozenset({(0, 1), (1, 1), (2, 1)}), "Спальня"),
            Room(3, frozenset({(0, 2), (1, 2), (2, 2)})),
        )
        assert_invalid(dataclasses.replace(make_puzzle(), rooms=rooms),
                       "duplicate")

    def test_room_names_and_forms_validate(self):
        rooms = (
            Room(1, frozenset({(0, 0), (1, 0), (2, 0)}), "Спальня",
                 {"gen": "спальни", "prep": "спальне"}),
            Room(2, frozenset({(0, 1), (1, 1), (2, 1)})),
            Room(3, frozenset({(0, 2), (1, 2), (2, 2)}), "Кухня", {}),
        )
        dataclasses.replace(make_puzzle(), rooms=rooms).validate()

    def test_bad_room_forms_rejected(self):
        rooms = (
            Room(1, frozenset({(0, 0), (1, 0), (2, 0)}), "Спальня",
                 {"instr": "спальней"}),
            Room(2, frozenset({(0, 1), (1, 1), (2, 1)})),
            Room(3, frozenset({(0, 2), (1, 2), (2, 2)})),
        )
        assert_invalid(dataclasses.replace(make_puzzle(), rooms=rooms),
                       "form keys")

    def test_portrait_seed_negative(self):
        people = (
            Person("suspect_1", "Подозреваемый_1", -1),
            Person("suspect_2", "Подозреваемый_2", 2),
            Person("victim", "Убитый", 3),
        )
        assert_invalid(dataclasses.replace(make_puzzle(), people=people))

    def test_portrait_seed_too_big(self):
        people = (
            Person("suspect_1", "Подозреваемый_1", 1),
            Person("suspect_2", "Подозреваемый_2", 2 ** 32),
            Person("victim", "Убитый", 3),
        )
        assert_invalid(dataclasses.replace(make_puzzle(), people=people))

    def test_portrait_seed_bounds_ok(self):
        people = (
            Person("suspect_1", "Подозреваемый_1", 0),
            Person("suspect_2", "Подозреваемый_2", 2 ** 32 - 1),
            Person("victim", "Убитый", 3),
        )
        dataclasses.replace(make_puzzle(), people=people).validate()


class TestValidateClues:
    def test_unknown_kind(self):
        clues = make_clues() + ({"kind": "on_the_roof", "person": "suspect_1"},)
        assert_invalid(dataclasses.replace(make_puzzle(), clues=clues))

    def test_no_extra_fields_allowed(self):
        clues = make_clues() + ({"kind": "no_empty_rooms", "person": "suspect_1"},)
        assert_invalid(dataclasses.replace(make_puzzle(), clues=clues))

    def test_missing_field(self):
        clues = make_clues() + ({"kind": "on", "person": "suspect_1"},)
        assert_invalid(dataclasses.replace(make_puzzle(), clues=clues))

    def test_person_wrong_type(self):
        clues = make_clues() + ({"kind": "on", "person": 1,
                                 "object_type": "table"},)
        assert_invalid(dataclasses.replace(make_puzzle(), clues=clues))

    def test_unknown_person(self):
        clues = make_clues() + ({"kind": "on", "person": "suspect_99",
                                 "object_type": "table"},)
        assert_invalid(dataclasses.replace(make_puzzle(), clues=clues))

    def test_unknown_person2(self):
        clues = make_clues() + ({"kind": "south", "person": "suspect_1",
                                 "person2": "suspect_77"},)
        assert_invalid(dataclasses.replace(make_puzzle(), clues=clues))

    def test_person_equals_person2(self):
        clues = make_clues() + ({"kind": "south", "person": "suspect_1",
                                 "person2": "suspect_1"},)
        assert_invalid(dataclasses.replace(make_puzzle(), clues=clues))

    def test_unknown_object_type(self):
        clues = make_clues() + ({"kind": "on", "person": "suspect_1",
                                 "object_type": "bathtub"},)
        assert_invalid(dataclasses.replace(make_puzzle(), clues=clues))

    def test_unknown_room(self):
        clues = make_clues() + ({"kind": "room_count", "room": 9,
                                 "count": 1, "op": "eq"},)
        assert_invalid(dataclasses.replace(make_puzzle(), clues=clues))

    def test_room_wrong_type(self):
        clues = make_clues() + ({"kind": "room_count", "room": "2",
                                 "count": 1, "op": "eq"},)
        assert_invalid(dataclasses.replace(make_puzzle(), clues=clues))

    def test_negative_count(self):
        clues = make_clues() + ({"kind": "room_count", "room": 2,
                                 "count": -1, "op": "eq"},)
        assert_invalid(dataclasses.replace(make_puzzle(), clues=clues))

    def test_count_bool_rejected(self):
        clues = make_clues() + ({"kind": "room_count", "room": 2,
                                 "count": True, "op": "eq"},)
        assert_invalid(dataclasses.replace(make_puzzle(), clues=clues))

    def test_bad_op(self):
        for op in ("==", "<>", "EQ", ""):
            clues = make_clues() + ({"kind": "room_count", "room": 2,
                                     "count": 1, "op": op},)
            assert_invalid(dataclasses.replace(make_puzzle(), clues=clues))

    def test_all_ops_valid(self):
        for op in ("eq", "ne", "gt", "ge", "lt", "le"):
            clues = make_clues() + ({"kind": "room_count", "room": 2,
                                     "count": 1, "op": op},)
            dataclasses.replace(make_puzzle(), clues=clues).validate()

    def test_clue_not_a_dict(self):
        clues = make_clues() + ("on",)
        assert_invalid(dataclasses.replace(make_puzzle(), clues=clues))


class TestSerialization:
    def test_round_trip(self):
        puzzle = make_puzzle()
        assert Puzzle.from_dict(puzzle.to_dict()) == puzzle

    def test_round_trip_with_names_and_forms(self):
        """names/gender/forms survive the JSON round trip."""
        rooms = (
            Room(1, frozenset({(0, 0), (1, 0), (2, 0)}), "Спальня",
                 {"gen": "спальни", "prep": "спальне"}),
            Room(2, frozenset({(0, 1), (1, 1), (2, 1)})),
            Room(3, frozenset({(0, 2), (1, 2), (2, 2)}), "Кухня",
                 {"gen": "кухни", "prep": "кухне"}),
        )
        people = (
            Person("suspect_1", "Анна", 1, "f",
                   {"gen": "Анны", "prep": "Анне"}),
            Person("suspect_2", "Пётр", 2, "m",
                   {"gen": "Петра", "prep": "Петре"}),
            Person("victim", "Ольга", 3, "f",
                   {"gen": "Ольги", "prep": "Ольге"}),
        )
        puzzle = dataclasses.replace(make_puzzle(), rooms=rooms, people=people)
        restored = Puzzle.from_dict(puzzle.to_dict())
        assert restored == puzzle
        assert restored.rooms[0].name == "Спальня"
        assert restored.rooms[0].forms == {"gen": "спальни", "prep": "спальне"}
        assert restored.people[0].gender == "f"
        assert restored.people[1].forms == {"gen": "Петра", "prep": "Петре"}

    def test_from_dict_accepts_legacy_entries_without_new_fields(self):
        """Pre-phase-5 puzzle JSON (no name/forms/gender) still parses."""
        good = make_puzzle().to_dict()
        good["rooms"][0].pop("name", None)
        good["rooms"][0].pop("forms", None)
        good["people"][0].pop("gender", None)
        good["people"][0].pop("forms", None)
        puzzle = Puzzle.from_dict(good)
        assert puzzle.rooms[0].name == ""
        assert puzzle.people[0].gender == ""

    def test_round_trip_via_raw_json_style(self):
        puzzle = make_puzzle()
        d = puzzle.to_dict()
        assert set(d) == {"width", "height", "rooms", "objects", "people",
                          "clues"}
        assert Puzzle.from_dict(d) == puzzle

    def test_to_dict_deterministic_cell_order(self):
        d = make_puzzle().to_dict()
        bed = next(o for o in d["objects"] if o["type"] == "bed")
        assert bed["cells"] == [{"r": 1, "c": 2}, {"r": 2, "c": 2}]
        assert d["rooms"][0]["cells"] == [{"r": 0, "c": 0}, {"r": 1, "c": 0},
                                          {"r": 2, "c": 0}]

    def test_to_dict_is_deep(self):
        puzzle = make_puzzle()
        d = puzzle.to_dict()
        d["clues"][0]["kind"] = "mutated"
        d["rooms"][0]["cells"].append({"r": 9, "c": 9})
        assert Puzzle.from_dict(puzzle.to_dict()) == puzzle

    def test_from_dict_rejects_top_level_problems(self):
        good = make_puzzle().to_dict()
        for key in ("width", "height", "rooms", "objects", "people", "clues"):
            bad = dict(good)
            del bad[key]
            with pytest.raises(PuzzleValidationError):
                Puzzle.from_dict(bad)
        bad = dict(good)
        bad["surprise"] = 1
        with pytest.raises(PuzzleValidationError):
            Puzzle.from_dict(bad)
        with pytest.raises(PuzzleValidationError):
            Puzzle.from_dict([good])

    def test_from_dict_rejects_wrong_scalar_types(self):
        good = make_puzzle().to_dict()
        for key, value in (("width", "3"), ("height", True), ("width", 3.0)):
            bad = dict(good)
            bad[key] = value
            with pytest.raises(PuzzleValidationError):
                Puzzle.from_dict(bad)

    def test_from_dict_rejects_bad_rooms(self):
        good = make_puzzle().to_dict()
        bad = dict(good)
        bad["rooms"] = "no"
        with pytest.raises(PuzzleValidationError):
            Puzzle.from_dict(bad)
        bad = dict(good)
        bad["rooms"] = [{"id": 1}]
        with pytest.raises(PuzzleValidationError):
            Puzzle.from_dict(bad)
        bad = dict(good)
        bad["rooms"] = [{"id": 1, "cells": []}]
        with pytest.raises(PuzzleValidationError):
            Puzzle.from_dict(bad)
        bad = dict(good)
        bad["rooms"] = [{"id": 1, "cells": [{"r": 0}]}]
        with pytest.raises(PuzzleValidationError):
            Puzzle.from_dict(bad)
        bad = dict(good)
        bad["rooms"] = [{"id": 1, "cells": [{"r": 0, "c": 0, "x": 1}]}]
        with pytest.raises(PuzzleValidationError):
            Puzzle.from_dict(bad)

    def test_from_dict_rejects_bad_people(self):
        good = make_puzzle().to_dict()
        bad = dict(good)
        bad["people"] = [{"id": "suspect_1", "name": "n",
                          "portrait_seed": 1.5}]
        with pytest.raises(PuzzleValidationError):
            Puzzle.from_dict(bad)

    def test_from_dict_rejects_bad_clue_entries(self):
        good = make_puzzle().to_dict()
        bad = dict(good)
        bad["clues"] = ["not-a-dict"]
        with pytest.raises(PuzzleValidationError):
            Puzzle.from_dict(bad)

    def test_from_dict_runs_validation(self):
        good = make_puzzle().to_dict()
        good["rooms"][0]["id"] = 7
        with pytest.raises(PuzzleValidationError):
            Puzzle.from_dict(good)


class TestDerivedHelpers:
    def test_playable_cells(self):
        puzzle = make_puzzle()
        assert puzzle.playable_cells() == frozenset(
            (r, c) for r in range(3) for c in range(3))
        assert void_puzzle().playable_cells() == frozenset({
            (0, 0), (0, 1), (1, 0),
            (0, 2), (1, 2), (2, 2),
            (2, 0), (2, 1),
        })

    def test_room_of(self):
        puzzle = make_puzzle()
        assert puzzle.room_of((0, 0)).id == 1
        assert puzzle.room_of((1, 2)).id == 3
        assert puzzle.room_of((9, 9)) is None
        assert void_puzzle().room_of((1, 1)) is None  # void

    def test_object_at(self):
        puzzle = make_puzzle()
        assert puzzle.object_at((0, 1)).type == "table"
        bed = puzzle.object_at((1, 2))
        assert bed is not None and bed.type == "bed"
        # standing on either bed cell finds the same instance
        assert puzzle.object_at((2, 2)) == bed
        assert puzzle.object_at((2, 1)) is None

    def test_allowed_cells(self):
        puzzle = make_puzzle()
        allowed = puzzle.allowed_cells()
        assert (0, 1) not in allowed          # table (full object)
        assert (2, 0) in allowed              # carpet (partial)
        assert (1, 2) in allowed and (2, 2) in allowed  # bed (partial)
        assert allowed | frozenset() == puzzle.playable_cells() \
            or allowed <= puzzle.playable_cells()
        assert allowed == puzzle.playable_cells() - {(0, 1)}

    def test_suspect_and_people_ids(self):
        puzzle = make_puzzle()
        assert puzzle.suspect_ids() == ["suspect_1", "suspect_2"]
        assert puzzle.people_ids() == ["suspect_1", "suspect_2", "victim"]
        # fresh lists: mutating them must not corrupt the puzzle
        puzzle.suspect_ids().append("x")
        puzzle.people_ids().clear()
        assert puzzle.suspect_ids() == ["suspect_1", "suspect_2"]
        assert puzzle.people_ids() == ["suspect_1", "suspect_2", "victim"]
