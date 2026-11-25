// Tests for main.js game logic that does not need a real DOM: the murder-room
// accusation derived from the user's placements (SPEC §3 rule 4).
import test from 'node:test';
import assert from 'node:assert/strict';

const { __test } = await import('../js/main.js');
const { state, derivedAccusation } = __test;

// two rooms; room 2 is the potential murder room
const PUZZLE = {
  people: [
    { id: 'suspect_1', name: 'Подозреваемый_1' },
    { id: 'suspect_2', name: 'Подозреваемый_2' },
    { id: 'victim', name: 'Убитый' },
  ],
  rooms: [
    { id: 1, cells: [{ r: 0, c: 0 }, { r: 0, c: 1 }] },
    { id: 2, cells: [{ r: 1, c: 0 }, { r: 1, c: 1 }, { r: 1, c: 2 }] },
  ],
};

const saved = { ...state };
const savedPlacements = state.placements;

test('derivedAccusation: exactly one suspect with the victim -> that suspect', () => {
  state.puzzle = PUZZLE;
  state.placements = new Map([
    ['suspect_1', { r: 0, c: 0 }],
    ['suspect_2', { r: 1, c: 1 }],
    ['victim', { r: 1, c: 0 }],
  ]);
  assert.equal(derivedAccusation(), 'suspect_2');
});

test('derivedAccusation: no suspect in the victim room -> null', () => {
  state.puzzle = PUZZLE;
  state.placements = new Map([
    ['suspect_1', { r: 0, c: 1 }],
    ['suspect_2', { r: 0, c: 0 }],
    ['victim', { r: 1, c: 2 }],
  ]);
  assert.equal(derivedAccusation(), null);
});

test('derivedAccusation: two suspects with the victim -> null (ambiguous)', () => {
  state.puzzle = PUZZLE;
  state.placements = new Map([
    ['suspect_1', { r: 1, c: 1 }],
    ['suspect_2', { r: 1, c: 2 }],
    ['victim', { r: 1, c: 0 }],
  ]);
  assert.equal(derivedAccusation(), null);
});

test('derivedAccusation: not everyone placed -> null', () => {
  state.puzzle = PUZZLE;
  state.placements = new Map([
    ['suspect_1', { r: 1, c: 1 }],
    ['victim', { r: 1, c: 0 }],
  ]);
  assert.equal(derivedAccusation(), null);
});

test('derivedAccusation: no puzzle -> null', () => {
  state.puzzle = null;
  assert.equal(derivedAccusation(), null);
});

test.afterEach(() => {
  Object.assign(state, saved);
  state.placements = savedPlacements;
});
