"""Canonical truth evaluator for clue dicts and placements.

Single source of direct (non-solver) semantics for server-side
alternative-solution validation: whether a placement satisfies the SPEC §3
rules and every clue of a puzzle.  Consumers: ``server/app.py``
(alternative-check slow path) and ``clues.enumerate_true_clues`` (clue
emission reuses the board views).  Semantics changes must touch, and keep
in agreement: this module, ``solver.py`` (its own fast bitmask encoding),
and the independent test evaluators (deliberate cross-checks — the tests
pin all of them against each other).

A placement maps person id -> ``(r, c)`` pair; list-valued pairs are
normalized to tuples at every public entry.  Malformed clue dicts raise
(ValueError/KeyError); callers validate puzzles up front
(``Puzzle.from_dict`` -> ``validate()``) and wrap parsing in try/except.
"""

from .model import Puzzle, _is_int, d1_holds

Cell = tuple[int, int]

_NEIGHBOR_OFFSETS = ((-1, 0), (1, 0), (0, -1), (0, 1))

# strict row/col comparisons for the directional clue kinds
_DIRECTIONAL = {
    "south": lambda a, b: a[0] > b[0],
    "north": lambda a, b: a[0] < b[0],
    "east": lambda a, b: a[1] > b[1],
    "west": lambda a, b: a[1] < b[1],
}


def _normalized(placement: dict) -> dict:
    """Copy of the placement with every cell pair converted to a tuple."""
    return {pid: tuple(cell) for pid, cell in placement.items()}


def _suspect_alone_with_victim(puzzle: Puzzle, placement: dict) -> str | None:
    """The suspect in the victim's room, or None when the victim's room does
    not hold exactly one suspect (SPEC §3 murder-room rule)."""
    vroom = puzzle.room_of(placement["victim"])
    if vroom is None:
        return None
    inside = [pid for pid in puzzle.suspect_ids()
              if puzzle.room_of(placement[pid]) is vroom]
    return inside[0] if len(inside) == 1 else None


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
        self._people = tuple(puzzle.people_ids())
        self._suspects = tuple(puzzle.suspect_ids())
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

    def near_types(self, cell: Cell) -> set[str | None]:
        """Object types on same-room neighbor cells (``None`` for empty
        neighbors) — the emission-side view of the same-room «рядом»."""
        return {self.type_at.get(nb)
                for nb in self._near_cells.get(tuple(cell), ())}

    # ------------------------------------------------------------------
    # clue truth
    # ------------------------------------------------------------------

    def clue_holds(self, clue: dict, placement: dict) -> bool:
        """Direct semantics of one clue dict under ``placement``."""
        placement = _normalized(placement)
        kind = clue["kind"]
        if kind in ("on", "not_on"):
            got = self.type_at.get(placement[clue["person"]]) \
                == clue["object_type"]
            return got if kind == "on" else not got
        if kind in ("adjacent", "not_adjacent"):
            got = self._near(placement[clue["person"]], clue["object_type"])
            return got if kind == "adjacent" else not got
        if kind in ("room_has_object", "room_not_has_object"):
            room = self.puzzle.room_of(placement[clue["person"]])
            got = room is not None \
                and clue["object_type"] in self.room_types.get(room.id, ())
            return got if kind == "room_has_object" else not got
        if kind in _DIRECTIONAL:
            return _DIRECTIONAL[kind](placement[clue["person"]],
                                      placement[clue["person2"]])
        if kind in ("same_room", "not_same_room"):
            ra = self.puzzle.room_of(placement[clue["person"]])
            rb = self.puzzle.room_of(placement[clue["person2"]])
            same = ra is not None and ra is rb
            return same if kind == "same_room" else not same
        if kind == "room_count":
            return d1_holds(self._room_count(placement, clue["room"]),
                            clue["op"], clue["count"])
        if kind == "no_empty_rooms":
            occupied = {self._room_id(placement[pid]) for pid in self._people}
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
        people = self._people
        if set(placement) != set(people):
            return False
        allowed = puzzle.allowed_cells()
        cells: list[Cell] = []
        for pid in people:
            cell = placement[pid]
            if isinstance(cell, list):
                cell = tuple(cell)
            elif not isinstance(cell, tuple):
                return False
            if len(cell) != 2 or not _is_int(cell[0]) or not _is_int(cell[1]):
                return False
            if cell not in allowed:
                return False
            cells.append(cell)
        if len({r for r, _ in cells}) != len(cells) \
                or len({c for _, c in cells}) != len(cells):
            return False
        # murder room: the victim's room holds exactly one suspect
        return _suspect_alone_with_victim(puzzle, placement) is not None

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _room_id(self, cell) -> int | None:
        room = self.puzzle.room_of(tuple(cell))
        return room.id if room is not None else None

    def _room_count(self, placement: dict, rid: int) -> int:
        return sum(1 for pid in self._people
                   if self._room_id(placement[pid]) == rid)

    def _near(self, cell, otype: str) -> bool:
        if self.type_at.get(cell) == otype:
            return False  # standing on O is never «рядом с O» (both bed cells)
        return any(self.type_at.get(nb) == otype
                   for nb in self._near_cells.get(cell, ()))


def unique_killer(puzzle: Puzzle, placement: dict) -> str | None:
    """The suspect alone with the victim per ``placement``, or None when the
    victim's room does not hold exactly one suspect."""
    return _suspect_alone_with_victim(puzzle, _normalized(placement))


def placement_satisfies(puzzle: Puzzle, placement: dict) -> bool:
    """SPEC §3 rules AND every clue of ``puzzle`` hold for ``placement``."""
    ctx = TruthContext(puzzle)
    return ctx.rules_ok(placement) and ctx.all_clues_hold(placement)
