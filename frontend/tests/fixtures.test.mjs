// Contract loop backend -> frontend (stage 5): the fixtures in
// fixtures/ are real puzzles produced by the backend generator
// (backend/scripts/export_clue_fixtures.py). Every clue of every fixture
// must render through clueToText to a non-empty Russian string, and the
// shared morphology helpers (personGenitive / peopleForm) must behave per
// ARCHITECTURE §5.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { clueToText, peopleForm, personGenitive } from '../js/clues.js';

const FIXTURE_DIR = fileURLToPath(new URL('./fixtures/', import.meta.url));
const FIXTURES = ['easy_seed_1.json', 'medium_seed_1.json'];

const KNOWN_KINDS = new Set([
  'on', 'not_on', 'adjacent', 'not_adjacent',
  'room_has_object', 'room_not_has_object',
  'south', 'north', 'east', 'west',
  'same_room', 'not_same_room', 'room_count', 'no_empty_rooms',
]);
const KNOWN_OBJECT_TYPES = new Set([
  'table', 'tv', 'wardrobe', 'fridge', 'bed', 'carpet', 'armchair', 'sofa',
]);
const CYRILLIC = /[Ѐ-ӿ]/;
// prepositional case per ARCHITECTURE §5 (for the exact-template check)
const PREP_FORM = {
  table: 'столе', tv: 'телевизоре', wardrobe: 'шкафу', fridge: 'холодильнике',
  bed: 'кровати', carpet: 'ковре', armchair: 'кресле', sofa: 'диване',
};

function loadFixture(name) {
  const puzzle = JSON.parse(readFileSync(FIXTURE_DIR + name, 'utf8'));
  const peopleMap = new Map(puzzle.people.map((p) => [p.id, p]));
  const roomsMap = new Map(puzzle.rooms.map((r) => [r.id, r]));
  return { puzzle, peopleMap, roomsMap };
}

function renderAll(puzzle, peopleMap, roomsMap) {
  return puzzle.clues.map((clue) => {
    let text;
    try {
      text = clueToText(clue, peopleMap, roomsMap);
    } catch (err) {
      throw new Error(
        `clueToText threw on ${JSON.stringify(clue)}: ${err.message}`);
    }
    return { clue, text };
  });
}

for (const name of FIXTURES) {
  test(`fixture ${name}: SPEC §4 shape from the backend generator`, () => {
    const { puzzle, peopleMap } = loadFixture(name);
    for (const key of ['width', 'height', 'rooms', 'objects', 'people', 'clues']) {
      assert.ok(key in puzzle, `missing key ${key}`);
    }
    assert.ok(puzzle.width >= 1 && puzzle.height >= 1);
    assert.ok(puzzle.rooms.length >= 1, 'at least one room');
    assert.ok(puzzle.people.length >= 3, 'at least 3 people');
    assert.ok(puzzle.clues.length >= 1, 'at least one clue');
    // people: suspects in numeric order, victim last
    const ids = puzzle.people.map((p) => p.id);
    assert.deepEqual(ids.slice(0, -1),
      ids.slice(0, -1).map((_, i) => `suspect_${i + 1}`));
    assert.equal(ids[ids.length - 1], 'victim');
    // every referenced id/type/room in clues exists in the puzzle
    const roomIds = new Set(puzzle.rooms.map((r) => r.id));
    for (const clue of puzzle.clues) {
      assert.ok(KNOWN_KINDS.has(clue.kind), `known kind: ${clue.kind}`);
      if (clue.person !== undefined) assert.ok(peopleMap.has(clue.person));
      if (clue.person2 !== undefined) assert.ok(peopleMap.has(clue.person2));
      if (clue.object_type !== undefined) {
        assert.ok(KNOWN_OBJECT_TYPES.has(clue.object_type),
          `known object type: ${clue.object_type}`);
      }
      if (clue.room !== undefined) assert.ok(roomIds.has(clue.room));
    }
    // object types on the board are all known to the frontend registry
    for (const obj of puzzle.objects) {
      assert.ok(KNOWN_OBJECT_TYPES.has(obj.type), `known type: ${obj.type}`);
    }
  });

  test(`fixture ${name}: every clue renders to non-empty Russian text`, () => {
    const { puzzle, peopleMap, roomsMap } = loadFixture(name);
    for (const { clue, text } of renderAll(puzzle, peopleMap, roomsMap)) {
      assert.equal(typeof text, 'string');
      assert.ok(text.length > 0, `non-empty text for ${JSON.stringify(clue)}`);
      assert.match(text, CYRILLIC, `Cyrillic in ${JSON.stringify(clue)}`);
      assert.ok(!text.includes('undefined'), `no 'undefined' leak: ${text}`);
      assert.ok(!text.includes('null'), `no 'null' leak: ${text}`);
      assert.ok(!text.endsWith('.'), `no trailing period (ARCH §5): ${text}`);
    }
  });

  test(`fixture ${name}: names carry gender and explicit case forms`, () => {
    const { puzzle, roomsMap } = loadFixture(name);
    const names = puzzle.people.map((p) => p.name);
    assert.equal(new Set(names).size, names.length, 'distinct people names');
    for (const person of puzzle.people) {
      assert.ok(['m', 'f'].includes(person.gender), `gender: ${person.name}`);
      assert.ok(person.forms && person.forms.gen && person.forms.prep,
        `forms: ${person.name}`);
    }
    const roomNames = puzzle.rooms.map((r) => r.name);
    assert.equal(new Set(roomNames).size, roomNames.length, 'distinct room names');
    for (const room of puzzle.rooms) {
      assert.ok(room.name, `room ${room.id} named`);
      assert.equal(roomsMap.get(room.id).forms.prep, room.forms.prep);
    }
  });

  test(`fixture ${name}: person/direction clue text matches templates`, () => {
    const { puzzle, peopleMap, roomsMap } = loadFixture(name);
    const suspect1 = puzzle.people.find((p) => p.id === 'suspect_1');
    const suspect2 = puzzle.people.find((p) => p.id === 'suspect_2');
    const objType = puzzle.objects[0].type;
    const was1 = suspect1.gender === 'f' ? 'была' : 'был';
    assert.equal(
      clueToText({ kind: 'south', person: suspect1.id, person2: suspect2.id },
        peopleMap, roomsMap),
      `${suspect1.name} ${was1} южнее ${suspect2.forms.gen}`);
    assert.equal(
      clueToText({ kind: 'same_room', person: suspect1.id, person2: suspect2.id },
        peopleMap, roomsMap),
      `${suspect1.name} и ${suspect2.name} были в одной комнате`);
    assert.equal(
      clueToText({ kind: 'on', person: suspect1.id, object_type: objType },
        peopleMap, roomsMap),
      `${suspect1.name} ${was1} на ${PREP_FORM[objType]}`);
  });
}

test('all clue kinds of the SPEC catalog render on real fixture data', () => {
  // Anchored to real ids from the medium fixture, so the whole SPEC §4
  // catalog is exercised even when the fixtures' own clue sets cover a
  // smaller subset of kinds.
  const { puzzle, peopleMap, roomsMap } = loadFixture('medium_seed_1.json');
  const roomId = puzzle.rooms[0].id;
  const roomPrep = puzzle.rooms[0].forms.prep; // "балконе" (lowercase)
  const s1 = puzzle.people.find((p) => p.id === 'suspect_1').id;
  const s2 = puzzle.people.find((p) => p.id === 'suspect_2').id;
  const objType = puzzle.objects[0].type;
  const clues = [
    { kind: 'on', person: s1, object_type: objType },
    { kind: 'not_on', person: s1, object_type: objType },
    { kind: 'adjacent', person: s1, object_type: objType },
    { kind: 'not_adjacent', person: s1, object_type: objType },
    { kind: 'room_has_object', person: s1, object_type: objType },
    { kind: 'room_not_has_object', person: s1, object_type: objType },
    { kind: 'south', person: s1, person2: s2 },
    { kind: 'north', person: s1, person2: s2 },
    { kind: 'east', person: s1, person2: s2 },
    { kind: 'west', person: s1, person2: s2 },
    { kind: 'same_room', person: s1, person2: s2 },
    { kind: 'not_same_room', person: s1, person2: s2 },
    { kind: 'room_count', room: roomId, count: 2, op: 'eq' },
    { kind: 'no_empty_rooms' },
  ];
  const rendered = clues.map((clue) => (
    { clue, text: clueToText(clue, peopleMap, roomsMap) }));
  for (const { clue, text } of rendered) {
    assert.ok(text.length > 0, `non-empty for ${clue.kind}`);
    assert.match(text, CYRILLIC, `Cyrillic for ${clue.kind}`);
    assert.ok(!/undefined|\[object/.test(text), `sane text for ${clue.kind}: ${text}`);
  }
  // spot checks on the D1 template incl. pluralization agreement
  assert.equal(clueToText({ kind: 'room_count', room: roomId, count: 1, op: 'eq' }, peopleMap, roomsMap),
    `В ${roomPrep} было ровно 1 человек`);
  assert.equal(clueToText({ kind: 'room_count', room: roomId, count: 2, op: 'eq' }, peopleMap, roomsMap),
    `В ${roomPrep} было ровно 2 человека`);
  assert.equal(clueToText({ kind: 'room_count', room: roomId, count: 5, op: 'eq' }, peopleMap, roomsMap),
    `В ${roomPrep} было ровно 5 человек`);
  assert.equal(clueToText({ kind: 'room_count', room: roomId, count: 1, op: 'gt' }, peopleMap, roomsMap),
    `В ${roomPrep} было более 1 человека`);
  assert.equal(clueToText({ kind: 'room_count', room: roomId, count: 2, op: 'ge' }, peopleMap, roomsMap),
    `В ${roomPrep} было не менее 2 человек`);
});

test('morphology spot checks: personGenitive and peopleForm', () => {
  assert.equal(personGenitive('Подозреваемый_1'), 'Подозреваемого_1');
  assert.equal(personGenitive('Подозреваемый_13'), 'Подозреваемого_13');
  assert.equal(personGenitive('Убитый'), 'Убитого');
  assert.equal(peopleForm(1), 'человек');
  assert.equal(peopleForm(2), 'человека');
  assert.equal(peopleForm(4), 'человека');
  assert.equal(peopleForm(5), 'человек');
  assert.equal(peopleForm(11), 'человек');
  assert.equal(peopleForm(12), 'человек');
  assert.equal(peopleForm(14), 'человек');
  assert.equal(peopleForm(21), 'человек');
  assert.equal(peopleForm(22), 'человека');
});
