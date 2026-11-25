"""Canonical truth evaluator for clue dicts and placements.

Single source of direct (non-solver) semantics for server-side
alternative-solution validation: whether a placement satisfies the SPEC §3
rules and every clue of a puzzle.  The solver keeps its own fast bitmask
encoding; the test suites keep their independent evaluators as deliberate
cross-checks, so a semantics change must touch all three in the same commit
(the tests pin them against each other).

A placement maps person id -> ``(r, c)`` tuple.  Malformed clue dicts raise
(ValueError/KeyError); the callers validate puzzles up front
(``Puzzle.from_dict`` -> ``validate()``) and wrap evaluation in try/except.
"""

from .model import Puzzle

_NEIGHBOR_OFFSETS = ((-1, 0), (1, 0), (0, -1), (0, 1))

_OPS = {
    "eq": lambda a, k: a == k,
    "ne": lambda a, k: a != k,
    "gt": lambda a, k: a > k,
    "ge": lambda a, k: a >= k,
    "lt": lambda a, k: a < k,
    "le": lambda a, k: a <= k,
}


def _is_int(value) -> bool:
    """True for real ints (bool excluded)."""
    return isinstance(value, int) and not isinstance(value, bool)


class TruthContext:
    """Precomputed board views for one puzzle; placements vary per call."""

    def __init__(self, puzzle: Puzzle) -> None:
        self.puzzle = puzzle
        self.type_at: dict[Cell, str] = {}
        room_types: dict[int, set[str]] = {}
        for obj in puzzle.objects:
            for cell in obj.cells:
                self.type_at[cell] = obj.type
            room = puzzle.room_of(next(iter(obj.cells)))
            if room is not None:
                room_types.setdefault(room.id, set()).add(obj.type)
        self.room_types = room_types
        # same-room neighbor cells per cell (same-room «рядом» semantics)
        self._near_cells: dict[Cell, frozenset[Cell]] = {}
        for cell in puzzle.playable_cells():
            room = puzzle.room_of(cell)
            near = {
                (cell[0] + dr, cell[1] + dc)
                for dr, dc in _NEIGHBOR_OFFSETS
                if puzzle.room_of((cell[0] + dr, cell[1] + dc)) is room
            }
            self._near_cells[cell] = frozenset(near)

    # ------------------------------------------------------------------
    # clue truth
    # ------------------------------------------------------------------

    def clue_holds(self, clue: dict, placement: dict) -> bool:
        """Direct semantics of one clue dict under ``placement``."""
        kind = clue["kind"]
        if kind in ("on", "not_on"):
            got = self.type_at.get(tuple(placement[clue["person"]])) \
                == clue["object_type"]
            return got if kind == "on" else not got
        if kind in ("adjacent", "not_adjacent"):
            got = self._near(placement[clue["person"]], clue["object_type"])
            return got if kind == "adjacent" else not got
        if kind in ("room_has_object", "room_not_has_object"):
            room = self.puzzle.room_of(tuple(placement[clue["person"]]))
            got = room is not None \
                and clue["object_type"] in self.room_types.get(room.id, ())
            return got if kind == "room_has_object" else not got
        if kind in ("south", "north", "east", "west"):
            a = tuple(placement[clue["person"]])
            b = tuple(placement[clue["person2"]])
            return {
                "south": a[0] > b[0], "north": a[0] < b[0],
                "east": a[1] > b[1], "west": a[1] < b[1],
            }[kind]
        if kind in ("same_room", "not_same_room"):
            ra = self.puzzle.room_of(tuple(placement[clue["person"]]))
            rb = self.puzzle.room_of(tuple(placement[clue["person2"]]))
            same = ra is not None and ra is rb
            return same if kind == "same_room" else not same
        if kind == "room_count":
            rid, k, op = clue["room"], clue["count"], clue["op"]
            return _OPS[op](self._room_count(placement, rid), k)
        if kind == "no_empty_rooms":
            occupied = {self._room_id(placement[pid])
                        for pid in self.puzzle.people_ids()}
            return all(room.id in occupied for room in self.puzzle.rooms)
        raise ValueError(f"unknown clue kind {kind!r}")

    def all_clues_hold(self, placement: dict) -> bool:
        return all(self.clue_holds(clue, placement)
                   for clue in self.puzzle.clues)

    # ------------------------------------------------------------------
    # SPEC §3 rules
    # ------------------------------------------------------------------

    def rules_ok(self, placement: dict) -> bool:
        """SPEC §3: allowed cells, distinct rows, distinct cols, and the
        murder room holds the victim plus exactly one suspect.  Off-field
        or malformed coordinates are "not ok" (False), never an exception.
        """
        puzzle = self.puzzle
        people = puzzle.people_ids()
        if set(placement) != set(people):
            return False
        allowed = puzzle.allowed_cells()
        cells: list[Cell] = []
        for pid in people:
            cell = placement[pid]
            if not isinstance(cell, tuple) or len(cell) != 2 \
                    or not _is_int(cell[0]) or not _is_int(cell[1]):
                return False
            if cell not in allowed:
                return False
            cells.append(cell)
        if len({r for r, _ in cells}) != len(cells) \
                or len({c for _, c in cells}) != len(cells):
            return False
        # murder room: the victim's room holds exactly one suspect
        vroom = self.puzzle.room_of(tuple(placement["victim"]))
        suspects_in = [pid for pid in puzzle.suspect_ids()
                       if self.puzzle.room_of(tuple(placement[pid])) is vroom]
        return len(suspects_in) == 1

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _room_id(self, cell) -> int | None:
        room = self.puzzle.room_of(tuple(cell))
        return room.id if room is not None else None

    def _room_count(self, placement: dict, rid: int) -> int:
        return sum(1 for pid in self.puzzle.people_ids()
                   if self._room_id(placement[pid]) == rid)

    def _near(self, cell, otype: str) -> bool:
        cell = tuple(cell)
        if self.type_at.get(cell) == otype:
            return False  # standing on O is never «рядом с O» (both bed cells)
        return any(self.type_at.get(nb) == otype
                   for nb in self._near_cells.get(cell, ()))


def unique_killer(puzzle: Puzzle, placement: dict) -> str | None:
    """The suspect alone with the victim per ``placement``, or None when the
    victim's room does not hold exactly one suspect."""
    room = puzzle.room_of(tuple(placement["victim"])) if "victim" in placement \
        else None
    if room is None:
        return None
    inside = [pid for pid in puzzle.suspect_ids()
              if puzzle.room_of(tuple(placement[pid])) is room]
    return inside[0] if len(inside) == 1 else None


def placement_satisfies(puzzle: Puzzle, placement: dict) -> bool:
    """SPEC §3 rules AND every clue of ``puzzle`` hold for ``placement``."""
    ctx = TruthContext(puzzle)
    return ctx.rules_ok(placement) and ctx.all_clues_hold(placement)
