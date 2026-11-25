# Murdoku — Architecture & Contracts (v1)

Single source of truth for **technical** contracts: stack, module APIs, data formats.
Game rules live in `SPEC.md` (Russian) — if SPEC and this file disagree on *game rules*,
SPEC wins; report the discrepancy to the orchestrator instead of silently picking one.

## 0. Stages

| Stage | Scope | Depends on |
|---|---|---|
| 1 | `backend/murdoku/model.py`, `backend/murdoku/solver.py` + tests + bench | — |
| 2 | `backend/murdoku/clues.py`, `backend/murdoku/generator.py` + tests | 1 |
| 3 | `backend/murdoku/server/` (`app.py`, `tokens.py`) + tests | 1 (contracts only) |
| 4 | `frontend/` (static SPA, mock API mode) | contracts only |
| 5 | Integration, e2e, polish | 1–4 |

Agents never `git commit` — the orchestrator reviews and commits.

## 1. Stack

- Python >= 3.12 (3.14 in this env). Core (model/solver/generator/clues): **stdlib only**.
- Server: **Starlette + uvicorn** (no pydantic), tokens via `cryptography` Fernet.
- Frontend: **vanilla JS ES-modules**, no build step, served by the backend as static files.
- Backend tests: pytest. Frontend pure-logic tests: `node --test`.
- venv lives at repo root: `.venv/` (project installed editable: `.venv/bin/pip install -e 'backend[dev]'`).
  Run backend tests: `cd backend && ../.venv/bin/python -m pytest -q`.

## 2. Repository layout

```
backend/
  pyproject.toml
  murdoku/
    __init__.py
    model.py          # stage 1: object registry, dataclasses, validation, (de)serialization
    solver.py         # stage 1: count_solutions / solutions
    clues.py          # stage 2: enumeration of true clues + greedy pruning
    generator.py      # stage 2: full pipeline
    server/
      __init__.py
      app.py          # stage 3: Starlette app, routes, static mount, __main__ entry
      tokens.py       # stage 3: Fernet token make/read
  tests/              # pytest
  scripts/
    bench_solver.py   # stage 1 benchmark
frontend/
  index.html
  styles.css
  js/
    main.js           # app state, wiring, DOM
    api.js            # fetch wrappers, mock switch (?mock=1)
    mock.js           # in-browser mock of the API (UI development / offline demo)
    board.js          # board rendering, drag&drop, clicks
    clues.js          # clueToText + pluralization + person inflection (pure, DOM-free)
    portraits.js      # portrait derivation from portrait_seed (pure, DOM-free)
  tests/              # node --test for pure-logic modules (*.test.mjs)
```

## 3. Domain model (`murdoku/model.py`)

```python
Cell = tuple[int, int]          # (r, c); r=0 top row, c=0 left column

@dataclass(frozen=True)
class ObjectTypeDef:
    id: str          # registry key, see table below
    cls: str         # "full" | "partial"
    size: int        # 1, or 2 for bed (always exactly 2)
    mergeable: bool  # visual merging only (table, carpet)

OBJECT_TYPES: dict[str, ObjectTypeDef]   # insertion order = registry order
OBJECT_TYPE_IDS: tuple[str, ...]

@dataclass(frozen=True)
class Room:
    id: int                       # 1..R, dense, sorted by corner cell (SPEC §1)
    cells: frozenset[Cell]
    name: str = ""                # display nominative ("Спальня"); "" = unnamed
    forms: dict = ...             # {"gen", "prep"}; display metadata only
    @property
    def corner(self) -> Cell      # min (r, c) lexicographic

@dataclass(frozen=True)
class ObjectInstance:
    id: str                       # "obj_1".. (dense in generation order)
    type: str                     # key in OBJECT_TYPES
    cells: frozenset[Cell]        # bed: 2 orthogonally adjacent cells, same room

@dataclass(frozen=True)
class Person:
    id: str                       # "suspect_1".. "suspect_{N-1}", victim id == "victim"
    name: str                     # real Russian name (curated pool) or legacy placeholder
    portrait_seed: int            # 0 .. 2**32-1
    gender: str = ""              # "" | "m" | "f"
    forms: dict = ...             # {"gen", "prep"}; display metadata only

@dataclass(frozen=True)
class Puzzle:
    width: int
    height: int
    rooms: tuple[Room, ...]           # sorted by id
    objects: tuple[ObjectInstance, ...]
    people: tuple[Person, ...]        # suspects in numeric order, victim LAST
    clues: tuple[dict, ...]           # plain dicts, SPEC §4 clue format

    # derived helpers (lru_cache-friendly, pure):
    def playable_cells(self) -> frozenset[Cell]          # union of room cells
    def room_of(self, cell: Cell) -> Room | None
    def object_at(self, cell: Cell) -> ObjectInstance | None
    def allowed_cells(self) -> frozenset[Cell]           # playable minus full-object cells
    def suspect_ids(self) -> list[str]                   # ["suspect_1", ...]
    def people_ids(self) -> list[str]                    # suspects then "victim"
    def validate(self) -> None                           # raises PuzzleValidationError(ValueError)
    def to_dict(self) -> dict                            # SPEC §4 JSON
    @classmethod
    def from_dict(cls, d: dict) -> "Puzzle"              # strict, validating
```

Registry (ids are English; RU display forms are a frontend concern, see §5):

| id | RU (nominative) | class | size | mergeable |
|---|---|---|---|---|
| `table` | стол | full | 1 | yes |
| `tv` | телевизор | full | 1 | no |
| `wardrobe` | шкаф | full | 1 | no |
| `fridge` | холодильник | full | 1 | no |
| `bed` | кровать | partial | 2 | no |
| `carpet` | ковёр | partial | 1 | yes |
| `armchair` | кресло | partial | 1 | no |
| `sofa` | диван | partial | 1 | no |

`validate()` checks (raise `PuzzleValidationError` with a descriptive message):
- dimensions ≥ 1; room/object cells inside bounds;
- room cell sets pairwise disjoint; room ids dense 1..R and ordered by corner;
  each room orthogonally connected (SPEC §1 — room = maximal connected cell set);
- objects: known type; cells pairwise disjoint across all objects; all cells of an
  instance in one room; bed == 2 orth-adjacent cells; object ids dense `obj_i`;
- people: ≥ 3; suspect ids `suspect_1..suspect_{N-1}` in order; exactly one `victim`
  last; portrait_seed in `0..2**32-1`; names are non-empty and pairwise distinct
  (format is free — real names or legacy placeholders); `gender ∈ {"", "m", "f"}`;
  `forms` maps a subset of {gen, prep} to non-empty strings; room names are
  distinct when non-empty;
- clues: kind in the whitelist; only the allowed fields present with correct types;
  referenced room id / person ids / object_type exist; `person != person2`;
  `count >= 0`; `op ∈ {eq,ne,gt,ge,lt,le}`.

Clue `kind` whitelist (exact strings):
`on, not_on, adjacent, not_adjacent, room_has_object, room_not_has_object,
adjacent_gender, south, north, east, west, same_room, not_same_room,
room_count, no_empty_rooms`.

Clue dict fields: `person`, `person2` (person ids), `object_type` (registry id),
`gender` (`"m"`/`"f"`, only `adjacent_gender`), `room` (int room id), `count` (int),
`op` (str). `no_empty_rooms` has no extra fields.

`adjacent_gender` semantics (SPEC §4 B3): the person's room holds ANOTHER person
of the given gender — any person counts (victim included, both for truth and for
emission; its gender is public knowledge, and the clue never names the victim by
id). Same-room, not orth-adjacent cells: two people can never occupy
orth-adjacent cells because the distinct-rows/cols rule forbids sharing a row or
column. For suspect-only rooms the full set already contains the stronger
same_room clue, so the emission's genuinely new information is exactly the
murder-room hints (victim-only rooms).

## 4. Puzzle JSON

Exactly as SPEC §4: `{"width", "height", "rooms": [{"id", "cells": [{"r","c"}],
"name"?, "forms"?}], "objects": [{"id","type","cells":[...]}],
"people": [{"id","name","portrait_seed", "gender"?, "forms"?}], "clues": [...]}`.
Cell lists sorted by (r, c) for deterministic output. No solution in it.

## 5. Russian clue text (frontend `js/clues.js`, pure functions)

```js
clueToText(clue, /* map person_id -> person */, /* optional map room_id -> room */)
    -> string   // no trailing period
peopleForm(k)      // "человек" | "человека" | "человек"  (1; 2–4; 5+; 11–14 → человек)
personGenitive(name) // legacy heuristic decline ("Подозреваемый_3" -> "Подозреваемого_3")
```

Names and inflection (ideas.md v2): the puzzle JSON carries `gender` and explicit
`forms` {gen, prep} for people and `name`/`forms` for rooms; `clueToText` prefers
them (`была` for `gender === "f"`; «южнее Дарьи»; «В спальне было…») and falls back
to the legacy placeholders/heuristics when the fields are absent. Rooms never get
a capital letter mid-sentence («В» is the capitalized word).

Object RU forms (used by templates):

| id | nom (где есть …) | prep (был на …) | instr (рядом с/со …) | gen (нет …) |
|---|---|---|---|---|
| table | стол | столе | со столом | стола |
| tv | телевизор | телевизоре | с телевизором | телевизора |
| wardrobe | шкаф | шкафу | со шкафом | шкафа |
| fridge | холодильник | холодильнике | с холодильником | холодильника |
| bed | кровать | кровати | с кроватью | кровати |
| carpet | ковёр | ковре | с ковром | ковра |
| armchair | кресло | кресле | с креслом | кресла |
| sofa | диван | диване | с диваном | дивана |

Templates (P = person name, Q = personGenitive(person2)):

| kind | text |
|---|---|
| on | `{P} был на {prep}` |
| not_on | `{P} был не на {prep}` |
| adjacent | `{P} был рядом {instr}` (instr already includes с/со) |
| not_adjacent | `{P} был не рядом {instr}` |
| adjacent_gender | `{P} был/была рядом с мужчиной/женщиной` (verb agrees with gender) |
| room_has_object | `{P} был в комнате, где есть {nom}` |
| room_not_has_object | `{P} был в комнате, где нет {gen}` |
| south / north / east / west | `{P} был южнее / севернее / восточнее / западнее {Q}` |
| same_room | `{P} и {P2} были в одной комнате` |
| not_same_room | `{P} и {P2} были в разных комнатах` |
| room_count | `В комнате_{room} было {op} {count} {noun}` — op: eq `ровно`, ne `не`, gt `более`, ge `не менее`, lt `менее`, le `не более`. Noun: for eq/ne use `peopleForm(count)`; for gt/ge/lt/le use the **genitive** form (`человека` when count%10==1 and count%100!=11, else `человек`) — per SPEC §4 D1: «более 1 человека», «не менее 2 человек» |
| no_empty_rooms | `Пустых комнат не было` |

Portraits (`js/portraits.js`, pure): `hue = portrait_seed % 360`. Suspect chip: a
pastel circle `hsl(hue, 45%, 82%)` filled with a composite SVG portrait assembled
from `portrait_seed` via a deterministic PRNG (mulberry32): skin tone, hair form +
color, glasses (35%), beard (30%), collar (3 shapes; collar colors are hue-derived
from `portrait_seed`, like the chip background). Victim: near-black circle with
`☠` (no SVG).
`clueListToTexts` renders the clue list, merging consecutive same-person
adjacent / not_adjacent clues into one sentence («рядом со столом и с креслом»);
merging is display-only.

## 6. Solver (`murdoku/solver.py`)

```python
def solutions(puzzle: Puzzle, limit: int) -> Iterator[dict[str, Cell]]
def count_solutions(puzzle: Puzzle, limit: int = 2) -> int
```

- Enforces ALL of SPEC §3 (one cell per person, distinct rows, distinct cols, no full
  objects, murder room) plus every clue. Semantics notes:
  - «рядом с O» — person's cell has an orth-adjacent cell containing an instance of O
    AND that instance cell lies in the same room as the person's cell (same-room
    semantics, SPEC §4) AND the person's own cell does not contain an instance of O
    (applies to both bed cells). `adj` is orth-only, a cell is not adjacent to itself.
  - `adjacent_gender` — the person's room holds another person of the given gender
    (same room; verified exactly at complete assignments, plus a sound optimistic
    static prune over rooms that some gender-g person could still occupy).
  - D-counters count **all** people incl. the victim.
  - Murder room = victim's room: exactly one suspect there (all other suspects outside).
- Algorithm: backtracking with MRV; **place the victim first** (murder-room pruning
  applies immediately after); row/col usage bitmasks; per-person cell masks precomputed
  from that person's A/B clues; C/D-clues checked on assignment events; `no_empty_rooms`
  and `adjacent_gender` verified at complete assignments. Deterministic iteration order.
- Performance: `count_solutions` on a dense 9×9 N=9 puzzle with a few hundred clues
  — target < 100 ms typical (SPEC §5). `scripts/bench_solver.py` prints measured times.

## 7. Clues & generator (`murdoku/clues.py`, `murdoku/generator.py`)

```python
# clues.py
def enumerate_true_clues(puzzle: Puzzle, solution: Mapping[str, Cell]) -> list[dict]
    # deterministic order (sort key: kind order as in SPEC §4, person number, object
    # type id, gender, room id, count, op index); only clue domains from SPEC §6
    # step 5: A/B per suspect × type present on the field; B3 adjacent_gender per
    # suspect × gender present among the other suspects of the room; C1 ordered
    # pairs, C2/C3 unordered; D1 room × op × k ∈ 0..N (true combos only); D2 global
    # if true.
def prune_clues(puzzle: Puzzle, clues: list[dict], rng: random.Random) -> list[dict]
    # two-pass greedy thinning (one rng stream): pass 1 shuffles and probes only the
    # directional C1 clues, pass 2 the rest; drop a clue if count_solutions(puzzle
    # without it, limit=2) == 1; returns the locally-minimal set; caller asserts final
    # count == 1. Directionals are probed first, so kept sets rarely contain any
    # (SPEC §6 step 5).

# generator.py
@dataclass
class GenerationResult:
    puzzle: Puzzle
    solution: dict[str, Cell]   # full placement, incl. victim & killer
    meta: dict                  # {"seed", "difficulty", "generation_ms", "clue_count", ...}

def generate(seed: int, difficulty: str) -> GenerationResult
```

- Difficulty params per SPEC §6 table; the **rooms range counts rooms including
  voids** (playable rooms = drawn value minus `x`); `x ∈ {0,1}` (void rooms) is
  chosen first, `R + x` regions grown, then `x` removed. **People count = board
  size** (one person per row/column — ideas.md; makes the victim-lock check
  automatic).
- Generation invariants (attempt rejected otherwise, ideas.md): every playable
  room holds ≥ 1 object instance; every suspect appears in ≥ 1 kept clue.
- One `random.Random(seed)` for the whole pipeline; ≤ 50 attempts per step; on
  exhaustion restart the outer attempt (same RNG), ≤ 40 outer attempts.
- Objects: pick class first (P(full) = 0.4), then a uniform type within the class
  (bed only reachable via the partial branch); distinct cells; bed = random cell +
  random orth neighbor in the same room.
- Murder room: a room with ≥ 2 allowed cells in distinct rows AND distinct cols.
- Determinism: same seed ⇒ same puzzle bytes.

## 8. Server (`murdoku/server/`)

- `GET /api/puzzle?difficulty={easy|medium|hard|expert}[&seed=N]` →
  `200 {"puzzle": {...}, "token": "..."}`; default difficulty `medium`;
  unknown difficulty or bad seed → `400 {"error": "..."}`.
  Generation failure (`GenerationError`) → `503 {"error": "..."}` (same JSON shape,
  SPEC §7): a request WITHOUT `seed` silently re-seeds with fresh random seeds up to
  `GENERATION_RETRIES = 5` attempts before answering 503; a request WITH an explicit
  seed makes exactly one attempt (the seed is never replaced — same seed ⇒ same
  puzzle bytes).
- `POST /api/check` body `{"token", "placements": [{"person_id","r","c"}...], "accusation"}`:
  - `400 {"error"}` on: bad JSON / missing fields / invalid token / placements not
    covering exactly all people ids exactly once / non-int coords / accusation not a
    suspect id.
  - `200 {"won": true, "solution": {person_id: [r, c]}}` — placements match solution
    AND accusation == killer id.
  - `200 {"won": false, "misplaced_person_id": "..."}` — first wrong placement in
    order `suspect_1..suspect_{N-1}, victim` (exactly one id).
  - `200 {"won": false, "correct_accusation": false}` — all placements correct,
    accusation wrong.
- Token: Fernet, key = `urlsafe_b64encode(sha256(MURDOKU_SECRET).digest())`;
  payload `{"game_id": uuid4-hex, "difficulty": str, "seed": int, "solution":
  {pid: [r,c]}, "killer_id": suspect-id, "puzzle": <SPEC §4 puzzle dict>}` —
  `/api/check` is stateless, so the killer id travels in the token (the server has
  no puzzle there to recompute rooms); the embedded puzzle dict enables
  alternative-solution validation for placements that differ from the embedded
  solution. Tokens without `"puzzle"` (pre-feature) fall back to exact-match only.
  `MURDOKU_SECRET` required; if unset and `MURDOKU_DEV=1` → random per-process key +
  stderr warning (tokens die on restart); if unset otherwise → refuse to start.
- Alternative wins (ideas.md): when placements differ from the token solution but
  satisfy ALL clues and SPEC §3 (`murdoku/clue_truth.py` — canonical evaluator;
  `Puzzle.from_dict` on the embedded dict) and the accusation equals the killer
  inferred from the USER's arrangement → `200 {"won": true, "solution": ...,
  "alternative": true}`; otherwise every legacy response is byte-identical.
  Such a win implies a generator/validation bug, so it is appended to
  `<MURDOKU_DATA_DIR>/alt_wins.jsonl` (default `data/`; IO errors are swallowed
  with a stderr warning and never affect the response).
- `GET /api/solution?token=...` → `200 {"solution": {pid: [r,c]}, "killer_id"}` —
  reveal endpoint (the player gives up); missing/invalid token or a token without
  solution/killer_id → `400 {"error"}`. Stateless: data comes from the token.
- Static: repo-root `frontend/` mounted at `/` (StaticFiles, html=True).
- Entry: `python -m murdoku.server` → uvicorn on `MURDOKU_HOST`/`MURDOKU_PORT`
  (default 127.0.0.1:8000). Out-of-field coords in placements are simply "wrong cells"
  (→ misplaced), not errors — only malformed types are 400.

## 9. Frontend behavior (SPEC §7 + amendments)

- `js/api.js`: `fetchPuzzle(difficulty, seed?)`, `checkAnswer(token, placements, accusation)`;
  mock mode active only with `?mock=1` (in-browser fake implementing the same contract,
  sample puzzle embedded in `js/mock.js` — uniqueness not guaranteed in the mock).
- Pure-logic modules (`clues.js`, `portraits.js`, and the pure parts of `api.js`) must
  be DOM-free and covered by `node --test` tests in `frontend/tests/`.
- Board: CSS grid `W×H`; voids not rendered; room = pastel tint `hsl(id*47 % 360, 45%, 88%)`;
  walls = thick borders between cells of different rooms / at borders / around voids;
  room number badge in the corner cell; objects = emoji icons (table 🍿→🍽️, tv 📺,
  wardrobe 🚪, fridge ❄️, bed 🛏️, carpet 🟫, armchair 🪑, sofa 🛋️ — agent may adjust);
  mergeable neighbors (table/carpet, same room) render as one bigger icon over their
  union; full objects cover the cell (no drop); bed icon on both cells.
- Drag & drop via Pointer Events (works for mouse/touch): palette chips are sources;
  drop ignored (no effects) on: occupied cell, full-object cell, void. Click a placed
  portrait → back to palette. Click an empty cell → red «✕» (никого нет), click again
  → remove. Misplaced person (after failed check) gets a red outline.
- Right panel: clue list (clueToText), palette (suspects + victim ☠), difficulty select
  (Легко/Средняя/Сложная/Эксперт), «Новая игра», accusation input with `<datalist>` of
  suspect names, «Обвинить» button — enabled only when all N people are placed AND the
  input resolves (trim + case-insensitive) to a suspect id; otherwise the request is
  not sent.
- Win: overlay «Дело раскрыто!» + killer name, board switched to the `solution` from
  the server response, button «Новая игра». Fail: stay on board, retry allowed.
- All UI text in Russian.

## 10. Testing & budgets

- Backend: unit tests per module + `scripts/bench_solver.py`; generator tests assert
  determinism (same seed ⇒ identical JSON), uniqueness (`count_solutions == 1` after
  pruning), difficulty parameter ranges, and expert-puzzle generation time
  (SPEC budget: < 3 s average — measure over ≥ 10 seeds; report actual numbers).
- Server: Starlette `TestClient` (httpx) with handcrafted puzzles + `tokens.make_token`;
  full e2e (generator → API → solver-simulated client) is stage 5 (orchestrator).

## 11. Conventions

- Code, identifiers, comments, docstrings — English. UI strings and RU clue text — Russian.
- No AI attribution lines in commit messages (user rule; orchestrator commits anyway).
- Deterministic output everywhere it can be (sorting, seeding, serialization).
