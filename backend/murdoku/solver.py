"""Solution counting and enumeration for Murdoku puzzles (ARCHITECTURE §6).

Backtracking with MRV over per-person candidate-cell bitmasks:

- the victim is placed first; then the murder-room rule is enforced by
  branching over which suspect shares the victim's room (exactly one suspect
  may be there, all other suspects are masked out of that room);
- row/column usage is tracked as bitmasks, so a person's live candidate set
  is ``base[p] & ~blocked_rows & ~blocked_cols``;
- per-person cell masks are precomputed from that person's A/B clues —
  ``on`` / ``not_on`` / ``adjacent`` / ``not_adjacent`` / room-has-object all
  depend only on the person's own cell, because object positions are static
  (for «рядом с O» the person's own cell must NOT contain an instance of O,
  which also covers standing on either cell of a bed);
- C clues (south/north/east/west, same/different room) are checked at
  assignment events against already-assigned people;
- D1 room-count clues prune on increments (upper bounds: eq/le/lt) and via a
  "lower bound can no longer be reached" test (eq/ge/gt), and are verified
  exactly at complete assignments; ``no_empty_rooms`` is verified at complete
  assignments, plus a cheap empty-rooms-vs-remaining-people prune.

Deterministic enumeration order: candidate cells in ascending index
(row-major), MRV ties broken by lowest person index, killer branches in
suspect-number order.  Pure standard library.
"""

from collections.abc import Iterator

from .model import Puzzle

Cell = tuple[int, int]

_OP_EQ, _OP_NE, _OP_GT, _OP_GE, _OP_LT, _OP_LE = range(6)
_OP_CODES = {"eq": 0, "ne": 1, "gt": 2, "ge": 3, "lt": 4, "le": 5}

_AB_KINDS = frozenset({
    "on", "not_on", "adjacent", "not_adjacent",
    "room_has_object", "room_not_has_object",
})
_C_KINDS = frozenset({
    "south", "north", "east", "west", "same_room", "not_same_room",
})
_UPPER_OPS = frozenset({_OP_EQ, _OP_LE, _OP_LT})


def solutions(puzzle: Puzzle, limit: int) -> Iterator[dict[str, Cell]]:
    """Enumerate up to ``limit`` solutions as person_id -> (r, c) mappings."""
    if limit <= 0:
        return
    prep = _Prepared(puzzle)
    emitted = 0
    for sol in prep.iter_solutions():
        yield sol
        emitted += 1
        if emitted >= limit:
            return


def count_solutions(puzzle: Puzzle, limit: int = 2) -> int:
    """Count solutions with early exit once ``limit`` have been found."""
    if limit <= 0:
        return 0
    prep = _Prepared(puzzle)
    count = 0
    for _ in prep.iter_solutions():
        count += 1
        if count >= limit:
            break
    return count


def _d1_ok(count: int, op: int, k: int) -> bool:
    if op == _OP_EQ:
        return count == k
    if op == _OP_NE:
        return count != k
    if op == _OP_GT:
        return count > k
    if op == _OP_GE:
        return count >= k
    if op == _OP_LT:
        return count < k
    return count <= k  # _OP_LE


class _Prepared:
    """Immutable precomputation for one puzzle, shared by a whole search."""

    def __init__(self, puzzle: Puzzle) -> None:
        people = puzzle.people_ids()
        if "victim" not in people:
            raise ValueError("puzzle must contain a person with id 'victim'")
        self.people = people
        self.n_people = len(people)
        self.victim_idx = people.index("victim")
        self.suspects = [i for i, pid in enumerate(people) if pid != "victim"]

        w = puzzle.width
        h = puzzle.height
        self.w = w
        self.h = h
        n = w * h
        self.full_mask = (1 << n) - 1
        n_rooms = max((room.id for room in puzzle.rooms), default=0)
        self.n_rooms = n_rooms

        room_id_of = [0] * n
        room_cells = [0] * (n_rooms + 1)
        for room in puzzle.rooms:
            mask = 0
            for (r, c) in room.cells:
                idx = r * w + c
                room_id_of[idx] = room.id
                mask |= 1 << idx
            room_cells[room.id] = mask
        self.room_id_of = room_id_of
        self.room_cells = room_cells

        row_mask = [0] * h
        col_mask = [0] * w
        row_of = [0] * n
        col_of = [0] * n
        for idx in range(n):
            row_of[idx] = idx // w
            col_of[idx] = idx % w
            row_mask[idx // w] |= 1 << idx
            col_mask[idx % w] |= 1 << idx
        self.row_mask = row_mask
        self.col_mask = col_mask
        self.row_of = row_of
        self.col_of = col_of

        allowed_mask = 0
        for (r, c) in puzzle.allowed_cells():
            allowed_mask |= 1 << (r * w + c)
        self.base = self._person_masks(puzzle, allowed_mask)
        self._parse_c_clues(puzzle)
        self._parse_d_clues(puzzle)

    # -- A/B clues: static per-person cell masks -----------------------

    def _type_masks(self, puzzle: Puzzle, otype: str) -> tuple[int, int, int]:
        """Bitmasks over cells: (has O, near O, room contains O)."""
        w, h = self.w, self.h
        has = 0
        for obj in puzzle.objects:
            if obj.type == otype:
                for (r, c) in obj.cells:
                    has |= 1 << (r * w + c)
        near = 0
        for idx in range(w * h):
            bit = 1 << idx
            if has & bit:
                continue
            r, c = divmod(idx, w)
            hit = (
                (r > 0 and has & (bit >> w))
                or (r < h - 1 and has & (bit << w))
                or (c > 0 and has & (bit >> 1))
                or (c < w - 1 and has & (bit << 1))
            )
            if hit:
                near |= bit
        room_has = 0
        for rid in range(1, self.n_rooms + 1):
            if self.room_cells[rid] & has:
                room_has |= self.room_cells[rid]
        return has, near, room_has

    def _person_masks(self, puzzle: Puzzle, allowed_mask: int) -> list[int]:
        w = self.w
        full = self.full_mask
        clues_by_person: dict[str, list[dict]] = {
            pid: [] for pid in self.people}
        for clue in puzzle.clues:
            pid = clue.get("person")
            if pid in clues_by_person:
                clues_by_person[pid].append(clue)
        needed = sorted({
            clue["object_type"]
            for clues in clues_by_person.values()
            for clue in clues
            if clue.get("kind") in _AB_KINDS
            and isinstance(clue.get("object_type"), str)
        })
        type_masks = {t: self._type_masks(puzzle, t) for t in needed}
        masks: list[int] = []
        for pid in self.people:
            mask = allowed_mask
            for clue in clues_by_person[pid]:
                kind = clue.get("kind")
                if kind in _AB_KINDS:
                    tm = type_masks[clue["object_type"]]
                    if kind == "on":
                        mask &= tm[0]
                    elif kind == "not_on":
                        mask &= self.full_mask & ~tm[0]
                    elif kind == "adjacent":
                        mask &= tm[1]
                    elif kind == "not_adjacent":
                        mask &= self.full_mask & ~tm[1]
                    elif kind == "room_has_object":
                        mask &= tm[2]
                    else:  # room_not_has_object
                        mask &= self.full_mask & ~tm[2]
            masks.append(mask & full)
        return masks

    # -- C clues: pairwise constraints checked on assignment ------------

    def _parse_c_clues(self, puzzle: Puzzle) -> None:
        by_person: list[list[tuple[int, int, int, int]]] = \
            [[] for _ in range(self.n_people)]
        for clue in puzzle.clues:
            kind = clue.get("kind")
            if kind not in _C_KINDS:
                continue
            p1, p2 = clue.get("person"), clue.get("person2")
            if p1 not in self.people or p2 not in self.people:
                continue
            i = self.people.index(p1)
            j = self.people.index(p2)
            row_sign = col_sign = room_req = 0
            if kind == "south":        # row(P1) > row(P2)
                row_sign = 1
            elif kind == "north":      # row(P1) < row(P2)
                row_sign = -1
            elif kind == "east":       # col(P1) > col(P2)
                col_sign = 1
            elif kind == "west":       # col(P1) < col(P2)
                col_sign = -1
            elif kind == "same_room":
                room_req = 1
            else:                      # not_same_room
                room_req = -1
            by_person[i].append((j, row_sign, col_sign, room_req))
            by_person[j].append(
                (i, -row_sign, -col_sign, room_req))
        self.c_clues = by_person

    # -- D clues: room population --------------------------------------

    def _parse_d_clues(self, puzzle: Puzzle) -> None:
        d1: list[tuple[int, int, int]] = []
        upper: dict[int, list[tuple[int, int]]] = {}
        lower_need: dict[int, int] = {}
        no_empty = False
        for clue in puzzle.clues:
            kind = clue.get("kind")
            if kind == "room_count":
                room, k, op = clue.get("room"), clue.get("count"), clue.get("op")
                code = _OP_CODES.get(op) if isinstance(op, str) else None
                if (isinstance(room, int) and isinstance(k, int)
                        and code is not None and 1 <= room <= self.n_rooms):
                    d1.append((room, code, k))
                    upper.setdefault(room, []).append((code, k))
                    need = 0
                    if code in (_OP_EQ, _OP_GE):
                        need = k
                    elif code == _OP_GT:
                        need = k + 1
                    if need > lower_need.get(room, 0):
                        lower_need[room] = need
            elif kind == "no_empty_rooms":
                no_empty = True
        self.d1 = d1
        self.d_upper = {
            room: [c for c in constraints if c[0] in _UPPER_OPS]
            for room, constraints in upper.items()
        }
        self.d_lower_need = lower_need
        self.no_empty = no_empty

    # -- search ---------------------------------------------------------

    def iter_solutions(self) -> Iterator[dict[str, Cell]]:
        """Yield every solution; the victim is placed first, then the search
        branches on which suspect is in the victim's room."""
        v = self.victim_idx
        w = self.w
        full = self.full_mask
        room_id_of = self.room_id_of
        victim_mask = self.base[v]
        while victim_mask:
            vb = victim_mask & -victim_mask
            victim_mask ^= vb
            vcell = vb.bit_length() - 1
            vroom = room_id_of[vcell]
            room_m = self.room_cells[vroom] if vroom else 0
            for killer in self.suspects:
                kmask = self.base[killer] & room_m
                if not kmask:
                    continue
                bases = list(self.base)
                bases[v] = vb
                bases[killer] = kmask
                for s in self.suspects:
                    if s != killer:
                        bases[s] &= full & ~room_m
                yield from self._search(bases, vcell, w)

    def _search(self, bases: list[int], vcell: int, w: int) -> \
            Iterator[dict[str, Cell]]:
        """MRV backtracking below a fixed victim placement."""
        n = self.n_people
        full = self.full_mask
        room_id_of = self.room_id_of
        row_mask = self.row_mask
        col_mask = self.col_mask
        row_of = self.row_of
        col_of = self.col_of
        c_clues = self.c_clues
        d1 = self.d1
        d_upper = self.d_upper
        d_lower_need = self.d_lower_need
        no_empty = self.no_empty
        n_rooms = self.n_rooms
        people = self.people

        assigned = [-1] * n
        assigned[self.victim_idx] = vcell
        counts = [0] * (n_rooms + 1)
        counts[room_id_of[vcell]] = 1
        blocked_rows = row_mask[row_of[vcell]]
        blocked_cols = col_mask[col_of[vcell]]
        assigned_count = 1
        remaining = n - 1

        def dfs():
            nonlocal assigned_count, remaining, blocked_rows, blocked_cols
            if assigned_count == n:
                for (room, op, k) in d1:
                    if not _d1_ok(counts[room], op, k):
                        return
                if no_empty:
                    for room in range(1, n_rooms + 1):
                        if counts[room] == 0:
                            return
                yield {people[i]: (c // w, c % w)
                       for i, c in enumerate(assigned)}
                return
            for room, need in d_lower_need.items():
                if need - counts[room] > remaining:
                    return
            if no_empty:
                empties = 0
                for room in range(1, n_rooms + 1):
                    if counts[room] == 0:
                        empties += 1
                        if empties > remaining:
                            return
            avail = full & ~blocked_rows & ~blocked_cols
            best_p = -1
            best_cnt = full.bit_count() + 1  # > any candidate count
            best_mask = 0
            for p in range(n):
                if assigned[p] >= 0:
                    continue
                m = bases[p] & avail
                cnt = m.bit_count()
                if cnt < best_cnt:
                    best_cnt, best_p, best_mask = cnt, p, m
                    if cnt == 0:
                        return
            p = best_p
            c_checks = c_clues[p]
            m = best_mask
            while m:
                b = m & -m
                m ^= b
                x = b.bit_length() - 1
                room = room_id_of[x]
                upper = d_upper.get(room)
                if upper is not None:
                    new_count = counts[room] + 1
                    bad = False
                    for (op, k) in upper:
                        if op == _OP_LT:
                            if new_count >= k:
                                bad = True
                                break
                        elif new_count > k:  # _OP_EQ, _OP_LE
                            bad = True
                            break
                    if bad:
                        continue
                bad = False
                for (j, rs, cs, rr) in c_checks:
                    y = assigned[j]
                    if y < 0:
                        continue
                    if rs and (row_of[x] - row_of[y]) * rs <= 0:
                        bad = True
                        break
                    if cs and (col_of[x] - col_of[y]) * cs <= 0:
                        bad = True
                        break
                    if rr and ((room == room_id_of[y]) != (rr > 0)):
                        bad = True
                        break
                if bad:
                    continue
                assigned[p] = x
                assigned_count += 1
                remaining -= 1
                counts[room] += 1
                blocked_rows |= row_mask[row_of[x]]
                blocked_cols |= col_mask[col_of[x]]
                yield from dfs()
                blocked_cols &= ~col_mask[col_of[x]]
                blocked_rows &= ~row_mask[row_of[x]]
                counts[room] -= 1
                remaining += 1
                assigned_count -= 1
                assigned[p] = -1

        yield from dfs()
