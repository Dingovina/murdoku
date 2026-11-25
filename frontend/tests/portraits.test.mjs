// Tests for portrait derivation (SPEC §4 / ARCHITECTURE §5).
import test from 'node:test';
import assert from 'node:assert/strict';
import { portraitOf, portraitSvg, PORTRAIT_CATALOGS, suspectNumber } from '../js/portraits.js';

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

// --- composite portraits ---

test('portraitSvg: deterministic per portrait_seed', () => {
  const person = { id: 'suspect_1', name: 'Подозреваемый_1', portrait_seed: 1234567 };
  assert.equal(portraitSvg(person), portraitSvg(person));
});

test('portraitSvg: different seeds yield different faces (usually)', () => {
  const a = portraitSvg({ id: 'suspect_1', name: 'x', portrait_seed: 1 });
  const b = portraitSvg({ id: 'suspect_2', name: 'y', portrait_seed: 3055571 });
  assert.notEqual(a, b);
});

test('portraitSvg: parts come from the catalogs', () => {
  const seenHairColors = new Set();
  const seenCollarMarks = ['c3.5', 'c3 -5.5', 'x="15" y="31.5"'];
  const seenCollars = new Set();
  for (const seed of [0, 1, 42, 3055571, 4289135632, 7, 99, 1234567]) {
    const svg = portraitSvg({ id: 'suspect_1', name: 'x', portrait_seed: seed });
    assert.ok(svg.startsWith('<svg'), 'svg markup');
    assert.ok(PORTRAIT_CATALOGS.skin.some((c) => svg.includes(`fill="${c}"`)),
      'skin tone from catalog, seed ' + seed);
    // bald heads have no hair fill, so colors are asserted across the batch
    for (const color of PORTRAIT_CATALOGS.hairColor) {
      if (svg.includes(`fill="${color}"`)) seenHairColors.add(color);
    }
    for (const mark of seenCollarMarks) {
      if (svg.includes(mark)) seenCollars.add(mark);
    }
  }
  assert.ok(seenHairColors.size >= 3, 'several hair colors occur across seeds');
  assert.ok(seenCollars.size === seenCollarMarks.length, 'all collar shapes occur');
});

test('portraitSvg: victim keeps the plain skull (empty svg)', () => {
  assert.equal(portraitSvg({ id: 'victim', name: 'Убитый', portrait_seed: 1 }), '');
});
