"""Domain model for Murdoku puzzles (ARCHITECTURE.md §3).

Object-type registry, frozen dataclasses for rooms / objects / people /
puzzles, structural validation (``Puzzle.validate``) and strict JSON
(de)serialization per SPEC §4.  Pure standard library.

``Puzzle`` is intentionally unhashable (clues are plain dicts).  All derived
helpers are precomputed once in ``__post_init__``, so repeated calls (e.g.
from the solver) are cheap and pure.
"""

from dataclasses import dataclass, field

Cell = tuple[int, int]  # (r, c); r=0 top row, c=0 left column

FULL = "full"        # a person may not stand on a cell of a full object
PARTIAL = "partial"  # a person may stand on a cell of a partial object


class PuzzleValidationError(ValueError):
    """Raised when a puzzle violates the structural rules of §3/§4."""


@dataclass(frozen=True)
class ObjectTypeDef:
    """Static definition of an object type (registry entry)."""

    id: str          # registry key
    cls: str         # FULL | PARTIAL
    size: int        # 1, or 2 for bed (always exactly 2)
    mergeable: bool  # visual merging only (table, carpet)


# Registry of object types; insertion order = registry order (ARCHITECTURE §3).
OBJECT_TYPES: dict[str, ObjectTypeDef] = {
    "table": ObjectTypeDef("table", FULL, 1, True),
    "tv": ObjectTypeDef("tv", FULL, 1, False),
    "wardrobe": ObjectTypeDef("wardrobe", FULL, 1, False),
    "fridge": ObjectTypeDef("fridge", FULL, 1, False),
    "bed": ObjectTypeDef("bed", PARTIAL, 2, False),
    "carpet": ObjectTypeDef("carpet", PARTIAL, 1, True),
    "armchair": ObjectTypeDef("armchair", PARTIAL, 1, False),
    "sofa": ObjectTypeDef("sofa", PARTIAL, 1, False),
}

# Registry keys as a tuple (stable order).
OBJECT_TYPE_IDS: tuple[str, ...] = tuple(OBJECT_TYPES)


@dataclass(frozen=True)
class Room:
    """A room: a connected set of playable cells with a dense numeric id.

    ``name`` is the display nominative ("Спальня"); "" means unnamed (the
    frontend falls back to "Комната_{id}").  ``forms`` carries explicit
    inflected Russian forms {"gen", "prep"} (ideas.md v2 names — the
    frontend never inflects); it is display metadata, excluded from
    equality/hash.
    """

    id: int                      # 1..R, dense, sorted by corner cell (SPEC §1)
    cells: frozenset[Cell]
    name: str = ""
    forms: dict = field(default_factory=dict, compare=False, hash=False)

    @property
    def corner(self) -> Cell:
        """Cell with the minimum (r, c) in lexicographic order."""
        return min(self.cells)


@dataclass(frozen=True)
class ObjectInstance:
    """A concrete object placed on the board."""

    id: str                    # "obj_1".. (dense in generation order)
    type: str                  # key in OBJECT_TYPES
    cells: frozenset[Cell]     # bed: 2 orthogonally adjacent cells, same room


@dataclass(frozen=True)
class Person:
    """A person: one of the suspects or the victim.

    ``name`` is the display nominative (a real Russian name from the
    generator's curated pool, or a legacy placeholder).  ``gender`` is
    "" (unspecified), "m" or "f".  ``forms`` carries explicit inflected
    forms {"gen", "prep"} (ideas.md v2 names); display metadata, excluded
    from equality/hash.
    """

    id: str             # "suspect_1".."suspect_{N-1}", victim id == "victim"
    name: str
    portrait_seed: int  # 0 .. 2**32-1
    gender: str = ""
    forms: dict = field(default_factory=dict, compare=False, hash=False)


@dataclass(frozen=True)
class Puzzle:
    """Full puzzle data (no solution inside)."""

    width: int
    height: int
    rooms: tuple[Room, ...]           # sorted by id
    objects: tuple[ObjectInstance, ...]
    people: tuple[Person, ...]        # suspects in numeric order, victim LAST
    clues: tuple[dict, ...]           # plain dicts, SPEC §4 clue format

    # precomputed derived state (not part of identity)
    _playable: frozenset[Cell] = field(
        init=False, repr=False, compare=False, default=frozenset())
    _room_index: dict[Cell, Room] = field(
        init=False, repr=False, compare=False, default_factory=dict)
    _object_at: dict[Cell, ObjectInstance] = field(
        init=False, repr=False, compare=False, default_factory=dict)
    _allowed: frozenset[Cell] = field(
        init=False, repr=False, compare=False, default=frozenset())
    _suspect_ids: tuple[str, ...] = field(
        init=False, repr=False, compare=False, default=())
    _people_ids: tuple[str, ...] = field(
        init=False, repr=False, compare=False, default=())

    def __post_init__(self) -> None:
        playable: set[Cell] = set()
        room_index: dict[Cell, Room] = {}
        for room in self.rooms:
            playable |= room.cells
            for cell in room.cells:
                room_index[cell] = room
        object_at: dict[Cell, ObjectInstance] = {}
        full_cells: set[Cell] = set()
        for obj in self.objects:
            for cell in obj.cells:
                object_at[cell] = obj
                typedef = OBJECT_TYPES.get(obj.type)
                if typedef is not None and typedef.cls == FULL:
                    full_cells.add(cell)
        suspects = tuple(p.id for p in self.people if p.id != "victim")
        people_ids = tuple(p.id for p in self.people)
        object.__setattr__(self, "_playable", frozenset(playable))
        object.__setattr__(self, "_room_index", room_index)
        object.__setattr__(self, "_object_at", object_at)
        object.__setattr__(self, "_allowed",
                           frozenset(playable - full_cells))
        object.__setattr__(self, "_suspect_ids", suspects)
        object.__setattr__(self, "_people_ids", people_ids)

    # ------------------------------------------------------------------
    # Derived helpers (pure, precomputed)
    # ------------------------------------------------------------------

    def playable_cells(self) -> frozenset[Cell]:
        """Union of all room cells (the play field)."""
        return self._playable

    def room_of(self, cell: Cell) -> Room | None:
        """Room containing ``cell``, or None for voids / out-of-board cells."""
        return self._room_index.get(cell)

    def object_at(self, cell: Cell) -> ObjectInstance | None:
        """Object instance covering ``cell``, or None."""
        return self._object_at.get(cell)

    def allowed_cells(self) -> frozenset[Cell]:
        """Playable cells minus cells covered by full objects."""
        return self._allowed

    def suspect_ids(self) -> list[str]:
        """["suspect_1", ...] in numeric order (no victim)."""
        return list(self._suspect_ids)

    def people_ids(self) -> list[str]:
        """Suspects then "victim"."""
        return list(self._people_ids)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """Raise ``PuzzleValidationError`` if the puzzle is not well-formed."""
        err = PuzzleValidationError
        if not _is_int(self.width) or not _is_int(self.height) \
                or self.width < 1 or self.height < 1:
            raise err("width and height must be integers >= 1")

        def in_bounds(cell: Cell) -> bool:
            r, c = cell
            return 0 <= r < self.height and 0 <= c < self.width

        # rooms ----------------------------------------------------------
        prev_corner: Cell | None = None
        seen_cells: set[Cell] = set()
        seen_names: set[str] = set()
        for i, room in enumerate(self.rooms):
            if not _is_int(room.id) or room.id != i + 1:
                raise err(
                    f"room ids must be dense 1..R in order; "
                    f"got id={room.id!r} at position {i}")
            for cell in room.cells:
                if not in_bounds(cell):
                    raise err(f"room {room.id} cell {cell} is out of bounds")
                if cell in seen_cells:
                    raise err(f"cell {cell} belongs to more than one room")
                seen_cells.add(cell)
            if not _orth_connected(room.cells):
                raise err(
                    f"room {room.id} is not orthogonally connected "
                    f"(SPEC §1: a room is a maximal connected cell set)")
            corner = room.corner
            if prev_corner is not None and corner <= prev_corner:
                raise err(
                    f"rooms must be sorted by corner cell; "
                    f"room {room.id} corner {corner} follows {prev_corner}")
            prev_corner = corner
            if not isinstance(room.name, str):
                raise err(f"room {room.id}: name must be a string")
            if room.name and room.name in seen_names:
                raise err(f"duplicate room name {room.name!r}")
            if room.name:
                seen_names.add(room.name)
            _check_forms(room.forms, f"room {room.id}", err)

        # objects --------------------------------------------------------
        obj_cells: set[Cell] = set()
        for i, obj in enumerate(self.objects):
            if obj.id != f"obj_{i + 1}":
                raise err(
                    f"object ids must be dense obj_1..obj_k in order; "
                    f"got {obj.id!r} at position {i}")
            if obj.type not in OBJECT_TYPES:
                raise err(f"{obj.id}: unknown object type {obj.type!r}")
            typedef = OBJECT_TYPES[obj.type]
            if len(obj.cells) != typedef.size:
                raise err(
                    f"{obj.id} ({obj.type}) must cover exactly "
                    f"{typedef.size} cell(s), got {len(obj.cells)}")
            if len(obj.cells) == 2:
                a, b = sorted(obj.cells)
                if abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
                    raise err(
                        f"{obj.id} (bed) cells {a} and {b} "
                        f"are not orthogonally adjacent")
            obj_room: int | None = None
            for cell in obj.cells:
                if not in_bounds(cell):
                    raise err(f"{obj.id} cell {cell} is out of bounds")
                if cell in obj_cells:
                    raise err(f"cell {cell} is covered by more than one object")
                obj_cells.add(cell)
                room = self._room_index.get(cell)
                if room is None:
                    raise err(
                        f"{obj.id} cell {cell} is not inside any room (void)")
                if obj_room is None:
                    obj_room = room.id
                elif room.id != obj_room:
                    raise err(
                        f"{obj.id} spans several rooms "
                        f"({obj_room} and {room.id})")

        # people ---------------------------------------------------------
        n_people = len(self.people)
        if n_people < 3:
            raise err(f"need at least 3 people, got {n_people}")
        for i, person in enumerate(self.people[:-1]):
            expected_id = f"suspect_{i + 1}"
            if person.id != expected_id:
                raise err(
                    f"people[{i}]: expected id {expected_id!r}, "
                    f"got {person.id!r}")
        victim = self.people[-1]
        if victim.id != "victim":
            raise err(
                f"last person must be the victim, got id {victim.id!r}")
        # names are free-form since phase 5 (real Russian names from the
        # generator pool; legacy "Подозреваемый_N" placeholders stay valid):
        # non-empty and pairwise distinct, so clue texts stay unambiguous
        names: set[str] = set()
        for person in self.people:
            if not isinstance(person.name, str) or not person.name:
                raise err(
                    f"{person.id}: name must be a non-empty string, "
                    f"got {person.name!r}")
            if person.name in names:
                raise err(f"duplicate person name {person.name!r}")
            names.add(person.name)
            if person.gender not in ("", "m", "f"):
                raise err(
                    f"{person.id}: gender must be '', 'm' or 'f', "
                    f"got {person.gender!r}")
            _check_forms(person.forms, person.id, err)
        seed_max = 2 ** 32 - 1
        for person in self.people:
            if not _is_int(person.portrait_seed) \
                    or not 0 <= person.portrait_seed <= seed_max:
                raise err(
                    f"{person.id}: portrait_seed must be an integer "
                    f"in 0..{seed_max}, got {person.portrait_seed!r}")

        # clues ----------------------------------------------------------
        known_person_ids = set(self._people_ids)
        known_room_ids = {room.id for room in self.rooms}
        for i, clue in enumerate(self.clues):
            where = f"clue[{i}]"
            if not isinstance(clue, dict):
                raise err(f"{where} must be a dict, got {type(clue).__name__}")
            kind = clue.get("kind")
            if not isinstance(kind, str) or kind not in _CLUE_FIELDS:
                raise err(f"{where}: unknown kind {kind!r}")
            allowed = _CLUE_FIELDS[kind]
            extra = set(clue) - allowed - {"kind"}
            if extra:
                raise err(f"{where} ({kind}): unexpected fields {sorted(extra)}")
            missing = allowed - set(clue)
            if missing:
                raise err(f"{where} ({kind}): missing fields {sorted(missing)}")
            if "person" in allowed:
                pid = clue["person"]
                if not isinstance(pid, str) or pid not in known_person_ids:
                    raise err(f"{where} ({kind}): unknown person {pid!r}")
            if "person2" in allowed:
                pid2 = clue["person2"]
                if not isinstance(pid2, str) or pid2 not in known_person_ids:
                    raise err(f"{where} ({kind}): unknown person2 {pid2!r}")
                if pid2 == clue["person"]:
                    raise err(f"{where} ({kind}): person must differ from person2")
            if "object_type" in allowed:
                otype = clue["object_type"]
                if not isinstance(otype, str) or otype not in OBJECT_TYPES:
                    raise err(f"{where} ({kind}): unknown object_type {otype!r}")
            if "room" in allowed:
                rid = clue["room"]
                if not _is_int(rid) or rid not in known_room_ids:
                    raise err(f"{where} ({kind}): unknown room {rid!r}")
            if "count" in allowed:
                count = clue["count"]
                if not _is_int(count) or count < 0:
                    raise err(
                        f"{where} ({kind}): count must be an integer >= 0, "
                        f"got {count!r}")
            if "op" in allowed:
                op = clue["op"]
                if not isinstance(op, str) or op not in _OPS:
                    raise err(
                        f"{where} ({kind}): op must be one of "
                        f"{', '.join(_OPS)}, got {op!r}")

    # ------------------------------------------------------------------
    # Serialization (SPEC §4 JSON)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Convert to the SPEC §4 JSON structure (cells sorted by (r, c))."""
        def cells(cells: frozenset[Cell]) -> list[dict]:
            return [{"r": r, "c": c} for r, c in sorted(cells)]

        return {
            "width": self.width,
            "height": self.height,
            "rooms": [
                {"id": room.id, "cells": cells(room.cells),
                 **({"name": room.name} if room.name else {}),
                 **({"forms": dict(room.forms)} if room.forms else {})}
                for room in self.rooms
            ],
            "objects": [
                {"id": obj.id, "type": obj.type, "cells": cells(obj.cells)}
                for obj in self.objects
            ],
            "people": [
                {"id": p.id, "name": p.name, "portrait_seed": p.portrait_seed,
                 **({"gender": p.gender} if p.gender else {}),
                 **({"forms": dict(p.forms)} if p.forms else {})}
                for p in self.people
            ],
            "clues": [dict(clue) for clue in self.clues],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Puzzle":
        """Strict parse of the SPEC §4 JSON structure, then validate()."""
        if not isinstance(d, dict):
            raise PuzzleValidationError("puzzle JSON must be an object")
        _exact_keys(d, {"width", "height", "rooms", "objects", "people",
                        "clues"}, "puzzle")
        width = _int_field(d, "width", 1, "puzzle")
        height = _int_field(d, "height", 1, "puzzle")

        raw_rooms = _list_field(d, "rooms", "puzzle")
        rooms = []
        for i, raw in enumerate(raw_rooms):
            # "name"/"forms" are optional (legacy puzzles pre-phase 5)
            _optional_keys(raw, {"id", "cells"}, {"name", "forms"},
                           f"rooms[{i}]")
            rid = _int_field(raw, "id", None, f"rooms[{i}]")
            cells = _cell_set(raw["cells"], f"rooms[{i}]")
            name = raw.get("name", "")
            forms = raw.get("forms", {})
            if not isinstance(name, str):
                raise PuzzleValidationError(
                    f"rooms[{i}].name must be a string")
            if not isinstance(forms, dict):
                raise PuzzleValidationError(
                    f"rooms[{i}].forms must be an object")
            rooms.append(Room(rid, cells, name, dict(forms)))

        raw_objects = _list_field(d, "objects", "puzzle")
        objects = []
        for i, raw in enumerate(raw_objects):
            _exact_keys(raw, {"id", "type", "cells"}, f"objects[{i}]")
            if not isinstance(raw["id"], str) or not raw["id"]:
                raise PuzzleValidationError(
                    f"objects[{i}].id must be a non-empty string")
            if not isinstance(raw["type"], str) or not raw["type"]:
                raise PuzzleValidationError(
                    f"objects[{i}].type must be a non-empty string")
            objects.append(ObjectInstance(
                raw["id"], raw["type"],
                _cell_set(raw["cells"], f"objects[{i}]")))

        raw_people = _list_field(d, "people", "puzzle")
        people = []
        for i, raw in enumerate(raw_people):
            # "gender"/"forms" are optional (legacy puzzles pre-phase 5)
            _optional_keys(raw, {"id", "name", "portrait_seed"},
                           {"gender", "forms"}, f"people[{i}]")
            if not isinstance(raw["id"], str) or not raw["id"]:
                raise PuzzleValidationError(
                    f"people[{i}].id must be a non-empty string")
            if not isinstance(raw["name"], str) or not raw["name"]:
                raise PuzzleValidationError(
                    f"people[{i}].name must be a non-empty string")
            seed = raw["portrait_seed"]
            if not _is_int(seed):
                raise PuzzleValidationError(
                    f"people[{i}].portrait_seed must be an integer")
            gender = raw.get("gender", "")
            forms = raw.get("forms", {})
            if not isinstance(gender, str):
                raise PuzzleValidationError(
                    f"people[{i}].gender must be a string")
            if not isinstance(forms, dict):
                raise PuzzleValidationError(
                    f"people[{i}].forms must be an object")
            people.append(Person(raw["id"], raw["name"], seed, gender,
                                 dict(forms)))

        raw_clues = _list_field(d, "clues", "puzzle")
        clues = []
        for i, raw in enumerate(raw_clues):
            if not isinstance(raw, dict):
                raise PuzzleValidationError(
                    f"clues[{i}] must be an object, got {type(raw).__name__}")
            clues.append(dict(raw))

        puzzle = cls(width, height, tuple(rooms), tuple(objects),
                     tuple(people), tuple(clues))
        puzzle.validate()
        return puzzle


# ----------------------------------------------------------------------
# Module-level constants and strict-parsing helpers
# ----------------------------------------------------------------------

# clue kind -> set of extra fields allowed for that kind
_CLUE_FIELDS: dict[str, frozenset[str]] = {
    "on": frozenset({"person", "object_type"}),
    "not_on": frozenset({"person", "object_type"}),
    "adjacent": frozenset({"person", "object_type"}),
    "not_adjacent": frozenset({"person", "object_type"}),
    "room_has_object": frozenset({"person", "object_type"}),
    "room_not_has_object": frozenset({"person", "object_type"}),
    "south": frozenset({"person", "person2"}),
    "north": frozenset({"person", "person2"}),
    "east": frozenset({"person", "person2"}),
    "west": frozenset({"person", "person2"}),
    "same_room": frozenset({"person", "person2"}),
    "not_same_room": frozenset({"person", "person2"}),
    "room_count": frozenset({"room", "count", "op"}),
    "no_empty_rooms": frozenset(),
}

_OPS: tuple[str, ...] = ("eq", "ne", "gt", "ge", "lt", "le")


def d1_holds(count: int, op: str, k: int) -> bool:
    """D1 room-count semantics shared by clue emission and the canonical
    evaluator: ``|people(room)| op k``."""
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


def _is_int(value: object) -> bool:
    """True for real ints (bool excluded)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _orth_connected(cells: frozenset[Cell]) -> bool:
    """True if the cell set is orthogonally connected (iterative DFS)."""
    start = min(cells)
    seen: set[Cell] = {start}
    stack: list[Cell] = [start]
    while stack:
        r, c = stack.pop()
        for nb in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
            if nb in cells and nb not in seen:
                seen.add(nb)
                stack.append(nb)
    return len(seen) == len(cells)


def _exact_keys(d: dict, expected: set[str], where: str) -> None:
    if not isinstance(d, dict):
        raise PuzzleValidationError(f"{where} must be an object")
    extra = set(d) - expected
    if extra:
        raise PuzzleValidationError(
            f"{where}: unexpected fields {sorted(extra)}")
    missing = expected - set(d)
    if missing:
        raise PuzzleValidationError(f"{where}: missing fields {sorted(missing)}")


def _optional_keys(d: dict, required: set[str], optional: set[str],
                   where: str) -> None:
    """Strict keys with an optional subset (legacy entries pre-phase 5)."""
    if not isinstance(d, dict):
        raise PuzzleValidationError(f"{where} must be an object")
    extra = set(d) - required - optional
    if extra:
        raise PuzzleValidationError(
            f"{where}: unexpected fields {sorted(extra)}")
    missing = required - set(d)
    if missing:
        raise PuzzleValidationError(f"{where}: missing fields {sorted(missing)}")


# inflected-form keys allowed in Room/Person ``forms`` dicts (SPEC §4)
_FORM_KEYS = frozenset({"gen", "prep"})


def _check_forms(forms: dict, where: str, err) -> None:
    """Raise ``err`` unless ``forms`` maps a subset of {"gen", "prep"} to
    non-empty strings."""
    if not isinstance(forms, dict):
        raise err(f"{where}: forms must be an object, "
                  f"got {type(forms).__name__}")
    bad = set(forms) - _FORM_KEYS
    if bad:
        raise err(f"{where}: unknown form keys {sorted(bad)}")
    for key, value in forms.items():
        if not isinstance(value, str) or not value:
            raise err(
                f"{where}: forms[{key!r}] must be a non-empty string, "
                f"got {value!r}")


def _int_field(d: dict, key: str, minimum: int | None, where: str) -> int:
    value = d[key]
    if not _is_int(value) or (minimum is not None and value < minimum):
        low = f" >= {minimum}" if minimum is not None else ""
        raise PuzzleValidationError(f"{where}.{key} must be an int{low}")
    return value


def _list_field(d: dict, key: str, where: str) -> list:
    value = d[key]
    if not isinstance(value, list):
        raise PuzzleValidationError(f"{where}.{key} must be an array")
    return value


def _cell_set(raw_cells: list, where: str) -> frozenset[Cell]:
    if not isinstance(raw_cells, list) or not raw_cells:
        raise PuzzleValidationError(f"{where}.cells must be a non-empty array")
    cells: set[Cell] = set()
    for i, raw in enumerate(raw_cells):
        _exact_keys(raw, {"r", "c"}, f"{where}.cells[{i}]")
        r = _int_field(raw, "r", 0, f"{where}.cells[{i}]")
        c = _int_field(raw, "c", 0, f"{where}.cells[{i}]")
        cells.add((r, c))
    return frozenset(cells)
