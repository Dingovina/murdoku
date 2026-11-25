// In-browser mock of the backend API (UI development / offline demo).
// Implements the SPEC §7 check contract faithfully; logical uniqueness of the
// sample puzzle is NOT guaranteed. Active only via ?mock=1 (see api.js).

// Hand-crafted 6x6 sample: 5 rooms (ids 1..5, corner order) + void strip in the
// bottom-left; objects include a bed and a mergeable table pair (obj_1/obj_2).
const SAMPLE_PUZZLE = {
  width: 6,
  height: 6,
  rooms: [
    { id: 1, name: 'Спальня', forms: { gen: 'спальни', prep: 'спальне' }, cells: [{ r: 0, c: 0 }, { r: 0, c: 1 }, { r: 0, c: 2 }, { r: 1, c: 0 }, { r: 1, c: 1 }, { r: 1, c: 2 }] },
    { id: 2, name: 'Гостиная', forms: { gen: 'гостиной', prep: 'гостиной' }, cells: [{ r: 0, c: 3 }, { r: 0, c: 4 }, { r: 0, c: 5 }, { r: 1, c: 3 }, { r: 1, c: 4 }, { r: 1, c: 5 }] },
    { id: 3, name: 'Столовая', forms: { gen: 'столовой', prep: 'столовой' }, cells: [{ r: 2, c: 0 }, { r: 2, c: 1 }, { r: 3, c: 0 }, { r: 3, c: 1 }] },
    { id: 4, name: 'Кухня', forms: { gen: 'кухни', prep: 'кухне' }, cells: [{ r: 2, c: 2 }, { r: 2, c: 3 }, { r: 3, c: 2 }, { r: 3, c: 3 }] },
    { id: 5, name: 'Оранжерея', forms: { gen: 'оранжереи', prep: 'оранжерее' }, cells: [{ r: 2, c: 4 }, { r: 2, c: 5 }, { r: 3, c: 4 }, { r: 3, c: 5 }, { r: 4, c: 4 }, { r: 4, c: 5 }, { r: 5, c: 4 }, { r: 5, c: 5 }] },
  ],
  // Void: (4,0..3), (5,0..3) — covered by no room.
  objects: [
    { id: 'obj_1', type: 'table', cells: [{ r: 0, c: 1 }] },
    { id: 'obj_2', type: 'table', cells: [{ r: 0, c: 2 }] },
    { id: 'obj_3', type: 'bed', cells: [{ r: 1, c: 0 }, { r: 1, c: 1 }] },
    { id: 'obj_4', type: 'tv', cells: [{ r: 0, c: 4 }] },
    { id: 'obj_5', type: 'sofa', cells: [{ r: 1, c: 3 }] },
    { id: 'obj_6', type: 'wardrobe', cells: [{ r: 2, c: 3 }] },
    { id: 'obj_7', type: 'carpet', cells: [{ r: 3, c: 2 }] },
    { id: 'obj_8', type: 'fridge', cells: [{ r: 2, c: 5 }] },
    { id: 'obj_9', type: 'armchair', cells: [{ r: 4, c: 4 }] },
    { id: 'obj_10', type: 'carpet', cells: [{ r: 5, c: 5 }] },
    // Blocks (2,1): without it suspect_2/victim could also sit at (2,1)/(3,0),
    // giving the sample a second solution.
    { id: 'obj_11', type: 'wardrobe', cells: [{ r: 2, c: 1 }] },
    // Same-room semantics: (2,0) and (3,1) have identical same-room object
    // neighbourhoods, so suspect_2/victim could swap there unnoticed. The
    // carpet under suspect_2 pins suspect_2 to (2,0) via the `on` clue.
    { id: 'obj_12', type: 'carpet', cells: [{ r: 2, c: 0 }] },
  ],
  people: [
    { id: 'suspect_1', name: 'Борис', gender: 'm', portrait_seed: 120483, forms: { gen: 'Бориса', prep: 'Борисе' } },
    { id: 'suspect_2', name: 'Анна', gender: 'f', portrait_seed: 3055571, forms: { gen: 'Анны', prep: 'Анне' } },
    { id: 'suspect_3', name: 'Фёдор', gender: 'm', portrait_seed: 77021544, forms: { gen: 'Фёдора', prep: 'Фёдоре' } },
    { id: 'suspect_4', name: 'Вера', gender: 'f', portrait_seed: 4289135632, forms: { gen: 'Веры', prep: 'Вере' } },
    { id: 'victim', name: 'Пётр', gender: 'm', portrait_seed: 3864129075, forms: { gen: 'Петра', prep: 'Петре' } },
  ],
  clues: [
    { kind: 'on', person: 'suspect_4', object_type: 'armchair' },
    { kind: 'on', person: 'suspect_3', object_type: 'sofa' },
    { kind: 'not_on', person: 'suspect_1', object_type: 'carpet' },
    // Same-room semantics: suspect_2's cell (2,0) touches the bed cell (1,0)
    // only across the room 1/room 3 wall, so the clue is a negation.
    { kind: 'not_adjacent', person: 'suspect_2', object_type: 'bed' },
    { kind: 'on', person: 'suspect_2', object_type: 'carpet' },
    { kind: 'not_adjacent', person: 'suspect_1', object_type: 'bed' },
    { kind: 'room_has_object', person: 'suspect_1', object_type: 'tv' },
    { kind: 'room_not_has_object', person: 'suspect_2', object_type: 'tv' },
    { kind: 'south', person: 'suspect_2', person2: 'suspect_1' },
    { kind: 'north', person: 'suspect_1', person2: 'suspect_3' },
    { kind: 'east', person: 'suspect_1', person2: 'suspect_3' },
    { kind: 'west', person: 'suspect_4', person2: 'suspect_1' },
    { kind: 'not_same_room', person: 'suspect_1', person2: 'suspect_2' },
    { kind: 'same_room', person: 'suspect_1', person2: 'suspect_3' },
    { kind: 'room_count', room: 3, count: 2, op: 'eq' },
    { kind: 'room_count', room: 1, count: 0, op: 'eq' },
    { kind: 'room_count', room: 5, count: 1, op: 'ge' },
  ],
};

// All clues above are true for this placement; suspect_2 is the killer
// (the only suspect in the victim's room 3).
export const SAMPLE_SOLUTION = {
  suspect_1: [0, 5],
  suspect_2: [2, 0],
  suspect_3: [1, 3],
  suspect_4: [4, 4],
  victim: [3, 1],
};

const DIFFICULTIES = ['easy', 'medium', 'hard', 'expert'];

// --- opaque token: base64(JSON{game_id, difficulty, solution}) ---

function encodeToken(payload) {
  const bytes = new TextEncoder().encode(JSON.stringify(payload));
  let bin = '';
  bytes.forEach((b) => { bin += String.fromCharCode(b); });
  return btoa(bin);
}

function decodeToken(token) {
  const bin = atob(String(token));
  const bytes = Uint8Array.from(bin, (ch) => ch.charCodeAt(0));
  return JSON.parse(new TextDecoder().decode(bytes));
}

function apiError(status, message) {
  const err = new Error(message);
  err.status = status;
  return err;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * GET /api/puzzle?difficulty=...[&seed=N] — mock. Seed is accepted and ignored
 * (a single embedded sample is served).
 */
export async function fetchPuzzle(difficulty, seed) {
  await sleep(120);
  if (!DIFFICULTIES.includes(difficulty)) {
    throw apiError(400, 'Неизвестная сложность: ' + difficulty);
  }
  if (seed !== undefined && seed !== null && seed !== '' && !/^-?\d+$/.test(String(seed))) {
    throw apiError(400, 'Некорректный seed');
  }
  return {
    puzzle: SAMPLE_PUZZLE,
    token: encodeToken({
      game_id: 'mock_' + Math.random().toString(16).slice(2),
      difficulty,
      solution: SAMPLE_SOLUTION,
    }),
  };
}

/**
 * POST /api/check — mock, exact contract per SPEC §7 / ARCHITECTURE §8.
 */
export async function checkAnswer(token, placements, accusation) {
  await sleep(120);
  if (token === undefined || token === null || token === '') {
    throw apiError(400, 'Отсутствует токен');
  }
  let payload;
  try {
    payload = decodeToken(token);
  } catch {
    throw apiError(400, 'Недействительный токен');
  }
  if (!Array.isArray(placements)) {
    throw apiError(400, 'placements должен быть массивом');
  }
  const peopleIds = Object.keys(SAMPLE_SOLUTION);
  const seen = new Map();
  for (const p of placements) {
    if (!p || typeof p !== 'object' || typeof p.person_id !== 'string') {
      throw apiError(400, 'Некорректная запись placements');
    }
    if (!Number.isInteger(p.r) || !Number.isInteger(p.c)) {
      throw apiError(400, 'Координаты должны быть целыми числами');
    }
    if (seen.has(p.person_id)) {
      throw apiError(400, 'Дубликат person_id: ' + p.person_id);
    }
    seen.set(p.person_id, [p.r, p.c]);
  }
  for (const id of peopleIds) {
    if (!seen.has(id)) {
      throw apiError(400, 'Не хватает размещения: ' + id);
    }
  }
  if (seen.size !== peopleIds.length) {
    throw apiError(400, 'placements покрывает не ровно всех людей');
  }
  if (typeof accusation !== 'string' || !/^suspect_\d+$/.test(accusation)
      || !peopleIds.includes(accusation)) {
    throw apiError(400, 'Обвинение должно быть id подозреваемого');
  }

  const solution = payload.solution;
  for (const id of peopleIds) { // suspects in numeric order, victim last
    const [r, c] = seen.get(id);
    const [sr, sc] = solution[id];
    if (r !== sr || c !== sc) {
      return { won: false, misplaced_person_id: id };
    }
  }
  const killer = sampleKiller();
  if (accusation !== killer) {
    return { won: false, correct_accusation: false };
  }
  return { won: true, solution };
}

/**
 * GET /api/solution?token=... — mock. The sample token carries the solution;
 * the killer is derived from the sample board (same as checkAnswer).
 */
export async function revealSolution(token) {
  await sleep(120);
  if (token === undefined || token === null || token === '') {
    throw apiError(400, 'Отсутствует токен');
  }
  let payload;
  try {
    payload = decodeToken(token);
  } catch {
    throw apiError(400, 'Недействительный токен');
  }
  if (!payload || typeof payload.solution !== 'object' || payload.solution === null) {
    throw apiError(400, 'Недействительный токен: нет решения');
  }
  return { solution: payload.solution, killer_id: sampleKiller() };
}

function sampleKiller() {
  // The only suspect in the victim's room.
  const roomOf = cellRoomMap();
  const victimRoom = roomOf.get(key(SAMPLE_SOLUTION.victim));
  for (let i = 1; ; i++) {
    const id = 'suspect_' + i;
    if (!(id in SAMPLE_SOLUTION)) break;
    if (roomOf.get(key(SAMPLE_SOLUTION[id])) === victimRoom) return id;
  }
  return null;
}

function key(cell) { return cell[0] + ',' + cell[1]; }

function cellRoomMap() {
  const map = new Map();
  for (const room of SAMPLE_PUZZLE.rooms) {
    for (const cell of room.cells) map.set(key([cell.r, cell.c]), room.id);
  }
  return map;
}
