// Tests for the in-browser mock API: endpoint contract (SPEC §7) and sample
// puzzle consistency (all clues true, rules hold, exactly one solution).
import test from 'node:test';
import assert from 'node:assert/strict';
import { fetchPuzzle, checkAnswer, revealSolution, SAMPLE_SOLUTION } from '../js/mock.js';

const FULL_TYPES = new Set(['table', 'tv', 'wardrobe', 'fridge']);
const OPS = {
  eq: (a, k) => a === k, ne: (a, k) => a !== k, gt: (a, k) => a > k,
  ge: (a, k) => a >= k, lt: (a, k) => a < k, le: (a, k) => a <= k,
};

const { puzzle } = await fetchPuzzle('medium');

const playable = new Set();
const roomOfCell = new Map();
const roomIds = new Set();
for (const room of puzzle.rooms) {
  roomIds.add(room.id);
  for (const c of room.cells) {
    playable.add(`${c.r},${c.c}`);
    roomOfCell.set(`${c.r},${c.c}`, room.id);
  }
}
const objAt = new Map();
const objCells = new Map(); // type -> [[r, c], ...]
for (const o of puzzle.objects) {
  for (const c of o.cells) {
    objAt.set(`${c.r},${c.c}`, o.type);
    if (!objCells.has(o.type)) objCells.set(o.type, []);
    objCells.get(o.type).push([c.r, c.c]);
  }
}
const roomsWith = (t) => new Set(puzzle.rooms
  .filter((r) => r.cells.some((c) => objAt.get(`${c.r},${c.c}`) === t)).map((r) => r.id));

const adjacent = (a, b) => Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]) === 1;

/** Truth of one clue for a placement Map(person_id -> [r, c]). */
function clueIsTrue(clue, placement) {
  const cellOf = (id) => placement.get(id);
  const roomOfPerson = (id) => roomOfCell.get(cellOf(id).join(','));
  const objHere = (id) => objAt.get(cellOf(id).join(','));
  // Same-room «рядом» (SPEC §4): the instance must be adjacent AND in the
  // person's own room.
  const nearObj = (id, t) => (objCells.get(t) || []).some(
    (x) => adjacent(x, cellOf(id)) && roomOfCell.get(x.join(',')) === roomOfPerson(id),
  ) && objHere(id) !== t;
  const counts = {};
  for (const [id, cell] of placement) {
    const r = roomOfCell.get(cell.join(','));
    counts[r] = (counts[r] || 0) + 1;
  }
  switch (clue.kind) {
    case 'on': return objHere(clue.person) === clue.object_type;
    case 'not_on': return objHere(clue.person) !== clue.object_type;
    case 'adjacent': return nearObj(clue.person, clue.object_type);
    case 'not_adjacent': return !nearObj(clue.person, clue.object_type);
    case 'room_has_object': return roomsWith(clue.object_type).has(roomOfPerson(clue.person));
    case 'room_not_has_object': return !roomsWith(clue.object_type).has(roomOfPerson(clue.person));
    // adjacent_gender: same-room semantics — another person of the given
    // gender in the person's own room (any person counts, victim included)
    case 'adjacent_gender': {
      const room = roomOfPerson(clue.person);
      const genderOf = (id) => {
        const p = puzzle.people.find((x) => x.id === id);
        return p ? p.gender : null;
      };
      return [...placement.keys()].some((id) => id !== clue.person
        && genderOf(id) === clue.gender
        && roomOfPerson(id) === room);
    }
    case 'south': return cellOf(clue.person)[0] > cellOf(clue.person2)[0];
    case 'north': return cellOf(clue.person)[0] < cellOf(clue.person2)[0];
    case 'east': return cellOf(clue.person)[1] > cellOf(clue.person2)[1];
    case 'west': return cellOf(clue.person)[1] < cellOf(clue.person2)[1];
    case 'same_room': return roomOfPerson(clue.person) === roomOfPerson(clue.person2);
    case 'not_same_room': return roomOfPerson(clue.person) !== roomOfPerson(clue.person2);
    case 'room_count': return OPS[clue.op](counts[clue.room] || 0, clue.count);
    case 'no_empty_rooms': return roomIds.size === Object.keys(counts).length;
    default: throw new Error('unknown kind ' + clue.kind);
  }
}

/** Personal (A/B) candidate mask for one person. */
function personalCells(personId) {
  const out = [];
  for (const k of playable) {
    if (FULL_TYPES.has(objAt.get(k))) continue;
    const cell = k.split(',').map(Number);
    const room = roomOfCell.get(k);
    let ok = true;
    for (const clue of puzzle.clues) {
      if (clue.person !== personId) continue;
      if (clue.kind === 'on' && !(objAt.get(k) === clue.object_type)) { ok = false; break; }
      if (clue.kind === 'not_on' && !(objAt.get(k) !== clue.object_type)) { ok = false; break; }
      if (clue.kind === 'adjacent' || clue.kind === 'not_adjacent') {
        const near = (objCells.get(clue.object_type) || []).some(
          (x) => adjacent(x, cell) && roomOfCell.get(x.join(',')) === room,
        ) && objAt.get(k) !== clue.object_type;
        if ((clue.kind === 'adjacent') !== near) { ok = false; break; }
      }
      if (clue.kind === 'room_has_object' && !roomsWith(clue.object_type).has(room)) { ok = false; break; }
      if (clue.kind === 'room_not_has_object' && roomsWith(clue.object_type).has(room)) { ok = false; break; }
    }
    if (ok) out.push(cell);
  }
  return out;
}

/** All placements satisfying rules (SPEC §3) and every clue. */
function findSolutions() {
  const people = puzzle.people.map((p) => p.id); // suspects then victim
  const solutions = [];
  const assign = new Map();
  const usedR = new Set();
  const usedC = new Set();
  const masks = new Map(people.map((id) => [id, personalCells(id)]));

  const cCluesOk = () => {
    for (const clue of puzzle.clues) {
      const two = ['south', 'north', 'east', 'west', 'same_room', 'not_same_room'];
      if (!two.includes(clue.kind)) continue;
      if (!assign.has(clue.person) || !assign.has(clue.person2)) continue;
      if (!clueIsTrue(clue, assign)) return false;
    }
    return true;
  };
  const completeOk = () => {
    // murder room: victim's room has exactly 2 people, exactly 1 of them a suspect
    const victimCell = assign.get('victim');
    const room = roomOfCell.get(victimCell.join(','));
    let inRoom = 0;
    let suspectsInRoom = 0;
    for (const [id, cell] of assign) {
      if (roomOfCell.get(cell.join(',')) === room) {
        inRoom += 1;
        if (id !== 'victim') suspectsInRoom += 1;
      }
    }
    if (inRoom !== 2 || suspectsInRoom !== 1) return false;
    for (const clue of puzzle.clues) {
      if (clue.kind === 'room_count' || clue.kind === 'no_empty_rooms'
          || clue.kind === 'adjacent_gender') {
        if (!clueIsTrue(clue, assign)) return false;
      }
    }
    return true;
  };

  const rec = (i) => {
    if (i === people.length) {
      if (completeOk()) solutions.push(new Map(assign));
      return;
    }
    const id = people[i];
    for (const cell of masks.get(id)) {
      if (usedR.has(cell[0]) || usedC.has(cell[1])) continue;
      assign.set(id, cell);
      usedR.add(cell[0]);
      usedC.add(cell[1]);
      if (cCluesOk()) rec(i + 1);
      assign.delete(id);
      usedR.delete(cell[0]);
      usedC.delete(cell[1]);
    }
  };
  rec(0);
  return solutions;
}

// --- puzzle / sample consistency ---

test('sample puzzle shape: 6x6, 5 rooms, bed + mergeable pair, 5 people, victim last', () => {
  assert.equal(puzzle.width, 6);
  assert.equal(puzzle.height, 6);
  assert.equal(puzzle.rooms.length, 5);
  const peopleIds = puzzle.people.map((p) => p.id);
  assert.deepEqual(peopleIds, ['suspect_1', 'suspect_2', 'suspect_3', 'suspect_4', 'victim']);
  assert.equal(puzzle.people.filter((p) => p.id === 'victim').length, 1);
  const types = puzzle.objects.map((o) => o.type);
  assert.ok(types.includes('bed') && types.includes('table'));
  const tables = puzzle.objects.filter((o) => o.type === 'table');
  assert.ok(tables.length >= 2, 'mergeable pair present');
  // bed occupies exactly 2 adjacent cells in one room
  const bed = puzzle.objects.find((o) => o.type === 'bed');
  assert.equal(bed.cells.length, 2);
  assert.ok(adjacent(bed.cells.map((c) => [c.r, c.c])[0], bed.cells.map((c) => [c.r, c.c])[1]));
  assert.equal(roomOfCell.get(`${bed.cells[0].r},${bed.cells[0].c}`),
    roomOfCell.get(`${bed.cells[1].r},${bed.cells[1].c}`));
  // voids: not covered by any room, <= 30% of the rectangle
  const voids = [];
  for (let r = 0; r < 6; r++) {
    for (let c = 0; c < 6; c++) {
      if (!playable.has(`${r},${c}`)) voids.push([r, c]);
    }
  }
  assert.ok(voids.length > 0 && voids.length <= Math.floor(0.3 * 36));
});

test('every sample clue is true for SAMPLE_SOLUTION and the rules hold', () => {
  const placement = new Map(Object.entries(SAMPLE_SOLUTION));
  for (const clue of puzzle.clues) {
    assert.ok(clueIsTrue(clue, placement), 'false clue: ' + JSON.stringify(clue));
  }
  // distinct rows / cols, all on allowed cells
  const rows = new Set();
  const cols = new Set();
  for (const [id, [r, c]] of placement) {
    assert.ok(playable.has(`${r},${c}`), id + ' off the playable field');
    assert.ok(!FULL_TYPES.has(objAt.get(`${r},${c}`)), id + ' on a full object');
    rows.add(r);
    cols.add(c);
  }
  assert.equal(rows.size, placement.size);
  assert.equal(cols.size, placement.size);
});

test('sample puzzle has EXACTLY one solution (the embedded one)', () => {
  const solutions = findSolutions();
  assert.equal(solutions.length, 1, 'expected unique solution, got ' + solutions.length);
  const found = Object.fromEntries([...solutions[0]].map(([id, c]) => [id, c]));
  assert.deepEqual(found, SAMPLE_SOLUTION);
});

// --- endpoint contract ---

test('fetchPuzzle: valid difficulty returns puzzle + opaque token', async () => {
  const { puzzle: p, token } = await fetchPuzzle('expert', 123);
  assert.equal(p.width, 6);
  assert.equal(typeof token, 'string');
  assert.ok(token.length > 10);
});

test('fetchPuzzle: unknown difficulty / bad seed -> 400', async () => {
  await assert.rejects(() => fetchPuzzle('impossible'), (e) => e.status === 400);
  await assert.rejects(() => fetchPuzzle('easy', '12x'), (e) => e.status === 400);
});

test('checkAnswer: full win -> {won:true, solution}', async () => {
  const { token } = await fetchPuzzle('easy');
  const placements = Object.entries(SAMPLE_SOLUTION).map(([person_id, [r, c]]) =>
    ({ person_id, r, c }));
  const res = await checkAnswer(token, placements, 'suspect_2');
  assert.deepEqual(res, { won: true, solution: SAMPLE_SOLUTION });
});

test('checkAnswer: first misplaced wins the report (suspects before victim)', async () => {
  const { token } = await fetchPuzzle('easy');
  const base = (overrides) => Object.entries(SAMPLE_SOLUTION).map(([person_id, [r, c]]) => {
    const o = overrides[person_id];
    return { person_id, r: o ? o[0] : r, c: o ? o[1] : c };
  });
  const both = await checkAnswer(token, base({ suspect_3: [0, 0], victim: [3, 0] }), 'suspect_2');
  assert.deepEqual(both, { won: false, misplaced_person_id: 'suspect_3' });
  const onlyVictim = await checkAnswer(token, base({ victim: [3, 0] }), 'suspect_2');
  assert.deepEqual(onlyVictim, { won: false, misplaced_person_id: 'victim' });
});

test('checkAnswer: correct placement + wrong accusation', async () => {
  const { token } = await fetchPuzzle('easy');
  const placements = Object.entries(SAMPLE_SOLUTION).map(([person_id, [r, c]]) =>
    ({ person_id, r, c }));
  assert.deepEqual(await checkAnswer(token, placements, 'suspect_1'),
    { won: false, correct_accusation: false });
});

test('revealSolution: returns the embedded solution and the sample killer', async () => {
  const { token } = await fetchPuzzle('easy');
  const res = await revealSolution(token);
  assert.deepEqual(res.solution, SAMPLE_SOLUTION);
  // the killer is the only suspect in the victim's room 3
  assert.equal(res.killer_id, 'suspect_2');
});

test('revealSolution: 400 on missing / garbage token', async () => {
  await assert.rejects(() => revealSolution(undefined), (e) => e.status === 400);
  await assert.rejects(() => revealSolution('!!!not base64!!!'), (e) => e.status === 400);
});

test('checkAnswer: 400 on malformed requests', async () => {
  const { token } = await fetchPuzzle('easy');
  const good = Object.entries(SAMPLE_SOLUTION).map(([person_id, [r, c]]) =>
    ({ person_id, r, c }));
  const cases = [
    [() => checkAnswer(undefined, good, 'suspect_2'), 'missing token'],
    [() => checkAnswer('!!!not base64!!!', good, 'suspect_2'), 'invalid token'],
    [() => checkAnswer(token, 'nope', 'suspect_2'), 'placements not an array'],
    [() => checkAnswer(token, good.map((p) => ({ ...p, r: 1.5 })), 'suspect_2'), 'non-int coord'],
    [() => checkAnswer(token, good.slice(1), 'suspect_2'), 'missing person'],
    [() => checkAnswer(token, [...good, good[0]], 'suspect_2'), 'extra duplicate'],
    [() => checkAnswer(token, good, 'victim'), 'accusation is the victim'],
    [() => checkAnswer(token, good, 'Подозреваемый_2'), 'accusation is a name'],
    [() => checkAnswer(token, good, 'suspect_9'), 'accusation unknown id'],
  ];
  for (const [fn, label] of cases) {
    await assert.rejects(fn, (e) => e.status === 400, label);
  }
});
