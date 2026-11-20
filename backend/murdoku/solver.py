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
- C clues (south/north/east/west, same/different room) are applied three
  ways: statically (bounds consistency over the per-person masks before the
  search), at assignment events against already-assigned people, and as
  forward propagation — assigning a person folds its fixed row/col/room
  into the masks of every unassigned C-clue partner;
- D1 room-count clues are enforced through per-room capacities (eq/le/lt
  imply a cap; a room at capacity is removed from everyone's candidates)
  plus a "lower bound can no longer be reached / can no longer be staffed"
  test (eq/ge/gt), and are verified exactly at complete assignments;
  ``no_empty_rooms`` is verified at complete assignments, plus cheap
  empty-rooms-vs-remaining-people prunes, and rooms no suspect can enter
  must hold the victim.

Deterministic enumeration order: candidate cells in ascending index
(row-major), MRV ties broken by lowest person index, killer branches in
suspect-number order.  Pure standard library.

Public API:

- ``solutions(puzzle, limit)`` / ``count_solutions(puzzle, limit=2)`` —
  one-shot functions (unchanged contract);
- ``Prepared(puzzle)`` — precomputed search context for one puzzle, with
  ``iter_solutions()`` / ``count_solutions(limit=2)``;
- ``Geometry(puzzle)`` — the clue-independent part of the precomputation
  (rooms, objects, rows/cols, allowed cells, per-type masks).  It can be
  shared between ``Prepared`` contexts built for clue variants of the same
  puzzle, which is what greedy clue pruning does (SPEC §6 step 5).
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


def solutions(puzzle: Puzzle, limit: int) -> Iterator[dict[str, Cell]]:
    """Enumerate up to ``limit`` solutions as person_id -> (r, c) mappings."""
    if limit <= 0:
        return
    prep = Prepared(puzzle)
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
    return Prepared(puzzle).count_solutions(limit)


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


class Geometry:
    """Clue-independent precomputation for one puzzle (static per board).

    Covers room/row/col bitboards, the allowed-cell mask and per-object-type
    masks.  It does not depend on clues, so one instance can be shared by
    ``Prepared`` contexts built for different clue subsets of the same puzzle
    (greedy clue pruning builds hundreds of such subsets).
    """

    __slots__ = (
        "w", "h", "full_mask", "n_rooms", "room_cells", "room_id_of",
        "row_mask", "col_mask", "row_of", "col_of", "allowed_mask",
        "rows_at_most", "cols_at_most", "objects", "_type_cache",
    )

    def __init__(self, puzzle: Puzzle) -> None:
        w = puzzle.width
        self.objects = puzzle.objects
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
        # prefix masks: all cells in rows <= r / cols <= c (for bounds
        # propagation over C clues)
        rows_at_most = [0] * h
        cols_at_most = [0] * w
        acc_r = acc_c = 0
        for r in range(h):
            acc_r |= row_mask[r]
            rows_at_most[r] = acc_r
        for c in range(w):
            acc_c |= col_mask[c]
            cols_at_most[c] = acc_c
        self.rows_at_most = rows_at_most
        self.cols_at_most = cols_at_most

        allowed_mask = 0
        for (r, c) in puzzle.allowed_cells():
            allowed_mask |= 1 << (r * w + c)
        self.allowed_mask = allowed_mask
        self._type_cache: dict[str, tuple[int, int, int]] = {}

    def type_masks(self, otype: str) -> tuple[int, int, int]:
        """Bitmasks over cells: (has O, near O, room contains O), cached."""
        masks = self._type_cache.get(otype)
        if masks is None:
            masks = self._compute_type_masks(otype)
            self._type_cache[otype] = masks
        return masks

    def _compute_type_masks(self, otype: str) -> tuple[int, int, int]:
        """Bitmasks over cells: (has O, near O, room contains O)."""
        w, h = self.w, self.h
        has = 0
        for obj in self.objects:
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


class Prepared:
    """Precomputed solver context for one puzzle.

    ``geometry`` may be a ``Geometry`` instance shared with other contexts
    for clue variants of the same puzzle; passing ``None`` builds a private
    one.  Results of ``iter_solutions`` / ``count_solutions`` are identical
    to the one-shot module-level functions.
    """

    __slots__ = (
        "geometry", "people", "n_people", "victim_idx", "suspects",
        "base", "c_clues", "d1", "room_cap", "d_lower_list", "no_empty",
    )

    def __init__(self, puzzle: Puzzle, geometry: Geometry | None = None) -> None:
        self.geometry = geometry if geometry is not None else Geometry(puzzle)
        geo = self.geometry
        people = puzzle.people_ids()
        if "victim" not in people:
            raise ValueError("puzzle must contain a person with id 'victim'")
        self.people = people
        self.n_people = len(people)
        self.victim_idx = people.index("victim")
        self.suspects = [i for i, pid in enumerate(people) if pid != "victim"]
        self.base = self._person_masks(puzzle, geo.allowed_mask)
        self._parse_c_clues(puzzle)
        self._parse_d_clues(puzzle)
        self._propagate_c_clues()
        self._restrict_victim_mask()

    # -- A/B clues: static per-person cell masks -----------------------

    def _person_masks(self, puzzle: Puzzle, allowed_mask: int) -> list[int]:
        geo = self.geometry
        full = geo.full_mask
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
        type_masks = {t: geo.type_masks(t) for t in needed}
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
                        mask &= full & ~tm[0]
                    elif kind == "adjacent":
                        mask &= tm[1]
                    elif kind == "not_adjacent":
                        mask &= full & ~tm[1]
                    elif kind == "room_has_object":
                        mask &= tm[2]
                    else:  # room_not_has_object
                        mask &= full & ~tm[2]
            masks.append(mask & full)
        return masks

    # -- C clues: pairwise constraints checked on assignment ------------

    def _parse_c_clues(self, puzzle: Puzzle) -> None:
        index = {pid: i for i, pid in enumerate(self.people)}
        by_person: list[list[tuple[int, int, int, int]]] = \
            [[] for _ in range(self.n_people)]
        for clue in puzzle.clues:
            kind = clue.get("kind")
            if kind not in _C_KINDS:
                continue
            p1, p2 = clue.get("person"), clue.get("person2")
            i = index.get(p1) if isinstance(p1, str) else None
            j = index.get(p2) if isinstance(p2, str) else None
            if i is None or j is None:
                continue
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
        n_rooms = self.geometry.n_rooms
        n_people = self.n_people
        # per-room capacity implied by the upper-bound clues (eq/le/lt):
        # a room can never hold more than cap people
        cap = [n_people + 1] * (n_rooms + 1)
        # per-room lower bound: the room must eventually hold >= need people
        need = [0] * (n_rooms + 1)
        no_empty = False
        for clue in puzzle.clues:
            kind = clue.get("kind")
            if kind == "room_count":
                room, k, op = clue.get("room"), clue.get("count"), clue.get("op")
                code = _OP_CODES.get(op) if isinstance(op, str) else None
                if (isinstance(room, int) and isinstance(k, int)
                        and code is not None and 1 <= room <= n_rooms):
                    d1.append((room, code, k))
                    if code in (_OP_EQ, _OP_LE):
                        room_cap = k
                    elif code == _OP_LT:
                        room_cap = k - 1
                    else:
                        room_cap = n_people + 1
                    if room_cap < cap[room]:
                        cap[room] = room_cap
                    room_need = 0
                    if code in (_OP_EQ, _OP_GE):
                        room_need = k
                    elif code == _OP_GT:
                        room_need = k + 1
                    if room_need > need[room]:
                        need[room] = room_need
            elif kind == "no_empty_rooms":
                no_empty = True
        self.d1 = d1
        self.room_cap = cap
        self.d_lower_list = tuple((rid, need[rid])
                                  for rid in range(1, n_rooms + 1) if need[rid])
        self.no_empty = no_empty

    def _restrict_victim_mask(self) -> None:
        """Static restrictions of the victim's candidate cells.

        The murder room always holds exactly two people (the victim and one
        suspect), so a room whose clue-implied capacity is below two or
        whose required population is above two cannot be the murder room.
        With ``no_empty_rooms`` every room needs an occupant, and a room no
        suspect can enter must hold the victim — there can be at most one
        such room.  All of this only removes cells that no solution uses.
        """
        geo = self.geometry
        base = self.base
        n_rooms = geo.n_rooms
        victim_mask = base[self.victim_idx]
        ok_rooms = 0
        no_suspect_rooms = 0
        for rid in range(1, n_rooms + 1):
            cells = geo.room_cells[rid]
            if not cells:
                continue
            if self.room_cap[rid] >= 2 \
                    and all(need <= 2 for room, need in self.d_lower_list
                            if room == rid):
                ok_rooms |= cells
            if self.no_empty \
                    and not any(base[s] & cells for s in self.suspects):
                no_suspect_rooms |= cells
        if no_suspect_rooms:
            victim_mask &= no_suspect_rooms  # the victim must cover one
        victim_mask &= ok_rooms
        base[self.victim_idx] = victim_mask

    # -- bounds propagation over C clues --------------------------------

    def _propagate_c_clues(self) -> None:
        """Shrink the per-person candidate masks to their C-clue support.

        For every C clue between persons i and j, a candidate cell x of i
        survives only if some candidate y of j is compatible with it
        (correct row/col order, room equality/inequality).  Iterated to a
        fixpoint this is bounds consistency on the binary C constraints:
        every removed cell belongs to no solution, so the solution set and
        the deterministic enumeration order are unchanged.  This is what
        keeps uniqueness proofs affordable on lightly-clued puzzles, which
        the greedy clue probing (SPEC §6 step 5) creates by the hundred.
        """
        c_clues = self.c_clues
        if not any(c_clues):
            return
        base = self.base
        geo = self.geometry
        full = geo.full_mask
        w = geo.w
        rows_le = geo.rows_at_most
        cols_le = geo.cols_at_most
        colm = geo.col_mask
        room_cells = geo.room_cells
        n_rooms = geo.n_rooms
        for _ in range(8):  # fixpoint, bounded (masks only shrink)
            changed = False
            for i, checks in enumerate(c_clues):
                mi = base[i]
                if not mi or not checks:
                    continue
                for (j, rs, cs, rr) in checks:
                    mj = base[j]
                    if not mj:
                        continue
                    new = mi
                    if rs:
                        # rows are monotone in the bit index, so the lowest
                        # / highest set bits carry the min / max row
                        if rs > 0:    # row(i) > row(j): need row above j's min
                            lo = ((mj & -mj).bit_length() - 1) // w
                            new = mi & ~rows_le[lo]
                        else:         # row(i) < row(j): below j's max
                            hi = (mj.bit_length() - 1) // w
                            new = mi & (rows_le[hi - 1] if hi else 0)
                    if new and cs:
                        # columns are NOT monotone in the bit index: scan
                        if cs > 0:    # col(i) > col(j): above j's min column
                            lo = 0
                            while not mj & colm[lo]:
                                lo += 1
                            new = new & ~cols_le[lo]
                        else:         # col(i) < col(j): below j's max column
                            hi = w - 1
                            while not mj & colm[hi]:
                                hi -= 1
                            new = new & (cols_le[hi - 1] if hi else 0)
                    if new and rr:
                        rooms_j = [rid for rid in range(1, n_rooms + 1)
                                   if room_cells[rid] & mj]
                        if rr > 0:    # same room: i stays in j's rooms
                            sup = 0
                            for rid in rooms_j:
                                sup |= room_cells[rid]
                            new &= sup
                        elif len(rooms_j) == 1:
                            # different room: j occupies a single candidate
                            # room, so i must avoid it
                            new &= full & ~room_cells[rooms_j[0]]
                    if new != mi:
                        base[i] = new
                        mi = new
                        changed = True
            if not changed:
                return
        # masks are monotone shrinking; 8 passes exceed any practical chain

    # -- search ---------------------------------------------------------

    def iter_solutions(self) -> Iterator[dict[str, Cell]]:
        """Yield every solution; the victim is placed first, then the search
        branches on which suspect is in the victim's room."""
        geo = self.geometry
        v = self.victim_idx
        w = geo.w
        full = geo.full_mask
        room_id_of = geo.room_id_of
        room_cells = geo.room_cells
        row_of = geo.row_of
        col_of = geo.col_of
        rows_le = geo.rows_at_most
        cols_le = geo.cols_at_most
        c_clues = self.c_clues
        victim_mask = self.base[v]
        v_clues = c_clues[v]

        def fold_one(m: int, rs: int, cs: int, rr: int) -> int:
            """Fold one C-clue direction toward the victim's fixed cell into
            a partner mask (identity when the victim is unreferenced)."""
            if m and rs:
                if rs > 0:      # row(v) > row(q): q above v's row
                    m = m & (rows_le[vrow - 1] if vrow else 0)
                else:           # row(v) < row(q): q below v's row
                    m = m & ~rows_le[vrow]
            if m and cs:
                if cs > 0:      # col(v) > col(q): q left of v's col
                    m = m & (cols_le[vcol - 1] if vcol else 0)
                else:           # col(v) < col(q): q right of v's col
                    m = m & ~cols_le[vcol]
            if m and rr:
                if rr > 0:      # same room as v
                    m = m & vroom_mask
                else:           # different room from v
                    m = m & v_not_room
            return m

        while victim_mask:
            vb = victim_mask & -victim_mask
            victim_mask ^= vb
            vcell = vb.bit_length() - 1
            vrow = row_of[vcell]
            vcol = col_of[vcell]
            vroom = room_id_of[vcell]
            room_m = room_cells[vroom] if vroom else 0
            not_room = full & ~room_m
            vroom_mask = room_m
            v_not_room = not_room
            masked = [b & not_room for b in self.base]
            # the victim's cell is fixed here, and the dfs fold loop skips
            # assigned partners — fold the victim's C clues into the masks
            # of exactly the partners they reference
            for (j, rs, cs, rr) in v_clues:
                masked[j] = fold_one(masked[j], rs, cs, rr)
            for killer in self.suspects:
                kmask = self.base[killer] & room_m
                if not kmask:
                    continue
                if v_clues:
                    # bases[killer] is overwritten below, so the killer's
                    # own mask needs the victim entries aimed at it
                    for (j, rs, cs, rr) in v_clues:
                        if j == killer:
                            kmask = fold_one(kmask, rs, cs, rr)
                    if not kmask:
                        continue
                bases = masked.copy()
                bases[killer] = kmask
                bases[v] = vb
                yield from self._search(bases, vcell, w)

    def count_solutions(self, limit: int = 2) -> int:
        """Count solutions with early exit once ``limit`` have been found."""
        if limit <= 0:
            return 0
        count = 0
        for _ in self.iter_solutions():
            count += 1
            if count >= limit:
                break
        return count

    def _search(self, bases: list[int], vcell: int, w: int) -> \
            Iterator[dict[str, Cell]]:
        """MRV backtracking below a fixed victim placement."""
        geo = self.geometry
        n = self.n_people
        full = geo.full_mask
        room_id_of = geo.room_id_of
        row_mask = geo.row_mask
        col_mask = geo.col_mask
        row_of = geo.row_of
        col_of = geo.col_of
        c_clues = self.c_clues
        d1 = self.d1
        d_lower_list = self.d_lower_list
        room_cap = self.room_cap
        no_empty = self.no_empty
        n_rooms = geo.n_rooms
        people = self.people
        room_cells = geo.room_cells
        rows_le = geo.rows_at_most
        cols_le = geo.cols_at_most

        assigned = [-1] * n
        assigned[self.victim_idx] = vcell
        counts = [0] * (n_rooms + 1)
        blocked_rows = row_mask[row_of[vcell]]
        blocked_cols = col_mask[col_of[vcell]]
        capped = 0  # rooms that reached their clue-implied capacity
        for rid in range(1, n_rooms + 1):
            if room_cap[rid] <= 0:
                capped |= room_cells[rid]
        victim_room = room_id_of[vcell]
        counts[victim_room] = 1
        if counts[victim_room] == room_cap[victim_room]:
            capped |= room_cells[victim_room]
        assigned_count = 1
        remaining = n - 1

        def dfs():
            nonlocal assigned_count, remaining, blocked_rows, blocked_cols
            nonlocal capped
            if assigned_count == n:
                for (room, op, k) in d1:
                    if not _d1_ok(counts[room], op, k):
                        return
                if no_empty and counts.count(0) > 1:
                    return  # counts[0] is always 0 (rooms are 1-based)
                yield {people[i]: (c // w, c % w)
                       for i, c in enumerate(assigned)}
                return
            for room, need in d_lower_list:
                if need - counts[room] > remaining:
                    return
            if no_empty and counts.count(0) - 1 > remaining:
                return
            avail = full & ~blocked_rows & ~blocked_cols & ~capped
            best_p = -1
            best_cnt = full.bit_count() + 1  # > any candidate count
            best_mask = 0
            for p, b in enumerate(bases):
                if assigned[p] >= 0:
                    continue
                m = b & avail
                cnt = m.bit_count()
                if cnt < best_cnt:
                    best_cnt, best_p, best_mask = cnt, p, m
                    if cnt == 0:
                        return
            if d_lower_list:
                # every room with an unmet lower bound must still be
                # reachable by enough unassigned people
                for room, need in d_lower_list:
                    lacking = need - counts[room]
                    if lacking <= 0:
                        continue
                    rc = room_cells[room]
                    able = 0
                    for p, b in enumerate(bases):
                        if assigned[p] < 0 and b & avail & rc:
                            able += 1
                    if able < lacking:
                        return
            p = best_p
            c_checks = c_clues[p]
            m = best_mask
            while m:
                b = m & -m
                m ^= b
                x = b.bit_length() - 1
                room = room_id_of[x]
                # forward propagation: fold p's fixed cell into the masks of
                # every unassigned C-clue partner (partners already assigned
                # folded their cell into base[p] when they were placed)
                xrow = row_of[x]
                xcol = col_of[x]
                # one save per partner: several C clues may point to the same
                # j, and only the first (original) mask must be restored
                saved = {}
                dead = False
                for (j, rs, cs, rr) in c_checks:
                    if assigned[j] >= 0:
                        continue
                    old = bases[j]
                    new = old
                    if rs:
                        if rs > 0:    # row(p) > row(q): q above p's row
                            new = old & (rows_le[xrow - 1] if xrow else 0)
                        else:         # row(p) < row(q): q below p's row
                            new = old & ~rows_le[xrow]
                    if new and cs:
                        if cs > 0:    # col(p) > col(q): q left of p's col
                            new = new & (cols_le[xcol - 1] if xcol else 0)
                        else:         # col(p) < col(q): q right of p's col
                            new = new & ~cols_le[xcol]
                    if new and rr:
                        if rr > 0:    # same room as p
                            new = new & room_cells[room]
                        else:         # different room from p
                            new = new & ~room_cells[room]
                    if new != old:
                        if j not in saved:
                            saved[j] = old
                        bases[j] = new
                        if not new:
                            dead = True
                            break
                if dead:
                    for j, old in saved.items():
                        bases[j] = old
                    continue
                assigned[p] = x
                assigned_count += 1
                remaining -= 1
                counts[room] += 1
                room_full = counts[room] == room_cap[room]
                if room_full:
                    capped |= room_cells[room]
                blocked_rows |= row_mask[xrow]
                blocked_cols |= col_mask[xcol]
                yield from dfs()
                blocked_cols &= ~col_mask[xcol]
                blocked_rows &= ~row_mask[xrow]
                if room_full:
                    capped &= ~room_cells[room]
                counts[room] -= 1
                remaining += 1
                assigned_count -= 1
                assigned[p] = -1
                for j, old in saved.items():
                    bases[j] = old

        yield from dfs()
