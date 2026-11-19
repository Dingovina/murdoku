// Tests for portrait derivation (SPEC §4 / ARCHITECTURE §5).
import test from 'node:test';
import assert from 'node:assert/strict';
import { portraitOf, suspectNumber } from '../js/portraits.js';

test('suspect: hue = seed % 360, initial П{n}', () => {
  const p = portraitOf({ id: 'suspect_1', name: 'Подозреваемый_1', portrait_seed: 1234567 });
  assert.equal(p.hue, 1234567 % 360);
  assert.equal(p.initial, 'П1');
  assert.equal(p.bg, `hsl(${1234567 % 360}, 70%, 45%)`);
  assert.equal(p.isVictim, false);
});

test('suspect_2 initial uses its number', () => {
  const p = portraitOf({ id: 'suspect_2', name: 'Подозреваемый_2', portrait_seed: 42 });
  assert.equal(p.initial, 'П2');
  assert.equal(p.hue, 42);
});

test('seed 0 is valid (hue 0)', () => {
  const p = portraitOf({ id: 'suspect_1', name: 'Подозреваемый_1', portrait_seed: 0 });
  assert.equal(p.hue, 0);
  assert.equal(p.bg, 'hsl(0, 70%, 45%)');
});

test('victim: near-black circle with skull', () => {
  const p = portraitOf({ id: 'victim', name: 'Убитый', portrait_seed: 7654321 });
  assert.equal(p.isVictim, true);
  assert.equal(p.initial, '☠');
  assert.equal(p.emoji, '☠');
  assert.equal(p.hue, 7654321 % 360);
});

test('suspectNumber parsing', () => {
  assert.equal(suspectNumber('suspect_1'), 1);
  assert.equal(suspectNumber('suspect_12'), 12);
  assert.equal(suspectNumber('victim'), null);
});
