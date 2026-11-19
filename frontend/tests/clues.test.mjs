// Tests for clueToText / peopleForm / personGenitive (ARCHITECTURE.md §5).
import test from 'node:test';
import assert from 'node:assert/strict';
import { clueToText, peopleForm, personGenitive } from '../js/clues.js';

const PEOPLE = new Map([
  ['suspect_1', { id: 'suspect_1', name: 'Подозреваемый_1' }],
  ['suspect_2', { id: 'suspect_2', name: 'Подозреваемый_2' }],
  ['suspect_3', { id: 'suspect_3', name: 'Подозреваемый_3' }],
  ['victim', { id: 'victim', name: 'Убитый' }],
]);

function text(clue) { return clueToText(clue, PEOPLE); }

test('A-class templates (on / not_on / adjacent / not_adjacent)', () => {
  assert.equal(text({ kind: 'on', person: 'suspect_1', object_type: 'bed' }),
    'Подозреваемый_1 был на кровати');
  assert.equal(text({ kind: 'not_on', person: 'suspect_1', object_type: 'carpet' }),
    'Подозреваемый_1 был не на ковре');
  assert.equal(text({ kind: 'adjacent', person: 'suspect_1', object_type: 'wardrobe' }),
    'Подозреваемый_1 был рядом со шкафом');
  assert.equal(text({ kind: 'not_adjacent', person: 'suspect_1', object_type: 'wardrobe' }),
    'Подозреваемый_1 был не рядом со шкафом');
});

test('B-class templates (room_has_object / room_not_has_object)', () => {
  assert.equal(text({ kind: 'room_has_object', person: 'suspect_2', object_type: 'table' }),
    'Подозреваемый_2 был в комнате, где есть стол');
  assert.equal(text({ kind: 'room_not_has_object', person: 'suspect_2', object_type: 'table' }),
    'Подозреваемый_2 был в комнате, где нет стола');
});

test('C-class templates (directions)', () => {
  assert.equal(text({ kind: 'south', person: 'suspect_1', person2: 'suspect_2' }),
    'Подозреваемый_1 был южнее Подозреваемого_2');
  assert.equal(text({ kind: 'north', person: 'suspect_1', person2: 'suspect_2' }),
    'Подозреваемый_1 был севернее Подозреваемого_2');
  assert.equal(text({ kind: 'east', person: 'suspect_1', person2: 'victim' }),
    'Подозреваемый_1 был восточнее Убитого');
  assert.equal(text({ kind: 'west', person: 'suspect_2', person2: 'suspect_3' }),
    'Подозреваемый_2 был западнее Подозреваемого_3');
});

test('C-class templates (same_room / not_same_room)', () => {
  assert.equal(text({ kind: 'same_room', person: 'suspect_1', person2: 'suspect_2' }),
    'Подозреваемый_1 и Подозреваемый_2 были в одной комнате');
  assert.equal(text({ kind: 'not_same_room', person: 'suspect_1', person2: 'suspect_2' }),
    'Подозреваемый_1 и Подозреваемый_2 были в разных комнатах');
});

test('D1 templates: all six operators', () => {
  assert.equal(text({ kind: 'room_count', room: 3, count: 2, op: 'eq' }),
    'В комнате_3 было ровно 2 человека');
  assert.equal(text({ kind: 'room_count', room: 1, count: 2, op: 'ne' }),
    'В комнате_1 было не 2 человека');
  assert.equal(text({ kind: 'room_count', room: 4, count: 1, op: 'gt' }),
    'В комнате_4 было более 1 человека');
  assert.equal(text({ kind: 'room_count', room: 2, count: 2, op: 'ge' }),
    'В комнате_2 было не менее 2 человек');
  assert.equal(text({ kind: 'room_count', room: 5, count: 2, op: 'lt' }),
    'В комнате_5 было менее 2 человек');
  assert.equal(text({ kind: 'room_count', room: 6, count: 2, op: 'le' }),
    'В комнате_6 было не более 2 человек');
});

test('D2 template', () => {
  assert.equal(text({ kind: 'no_empty_rooms' }), 'Пустых комнат не было');
});

test('object declensions match ARCHITECTURE §5 table for all 8 types', () => {
  const forms = {
    table:     { nom: 'стол',        prep: 'столе',        instr: 'со столом',       gen: 'стола' },
    tv:        { nom: 'телевизор',   prep: 'телевизоре',   instr: 'с телевизором',   gen: 'телевизора' },
    wardrobe:  { nom: 'шкаф',        prep: 'шкафу',        instr: 'со шкафом',       gen: 'шкафа' },
    fridge:    { nom: 'холодильник', prep: 'холодильнике', instr: 'с холодильником', gen: 'холодильника' },
    bed:       { nom: 'кровать',     prep: 'кровати',      instr: 'с кроватью',      gen: 'кровати' },
    carpet:    { nom: 'ковёр',       prep: 'ковре',        instr: 'с ковром',        gen: 'ковра' },
    armchair:  { nom: 'кресло',      prep: 'кресле',       instr: 'с креслом',       gen: 'кресла' },
    sofa:      { nom: 'диван',       prep: 'диване',       instr: 'с диваном',       gen: 'дивана' },
  };
  for (const [type, f] of Object.entries(forms)) {
    const P = 'Подозреваемый_1';
    assert.equal(text({ kind: 'on', person: 'suspect_1', object_type: type }),
      `${P} был на ${f.prep}`, `on/${type}`);
    assert.equal(text({ kind: 'adjacent', person: 'suspect_1', object_type: type }),
      `${P} был рядом ${f.instr}`, `adjacent/${type}`);
    assert.equal(text({ kind: 'room_has_object', person: 'suspect_1', object_type: type }),
      `${P} был в комнате, где есть ${f.nom}`, `room_has_object/${type}`);
    assert.equal(text({ kind: 'room_not_has_object', person: 'suspect_1', object_type: type }),
      `${P} был в комнате, где нет ${f.gen}`, `room_not_has_object/${type}`);
  }
});

test('peopleForm pluralization (1; 2–4; 5+; 11–14)', () => {
  assert.equal(peopleForm(1), 'человек');
  assert.equal(peopleForm(2), 'человека');
  assert.equal(peopleForm(3), 'человека');
  assert.equal(peopleForm(4), 'человека');
  assert.equal(peopleForm(5), 'человек');
  assert.equal(peopleForm(9), 'человек');
  assert.equal(peopleForm(11), 'человек');
  assert.equal(peopleForm(12), 'человек');
  assert.equal(peopleForm(14), 'человек');
  assert.equal(peopleForm(21), 'человек');
  assert.equal(peopleForm(22), 'человека');
  assert.equal(peopleForm(24), 'человека');
  assert.equal(peopleForm(111), 'человек');
  assert.equal(peopleForm(122), 'человека');
  assert.equal(peopleForm(0), 'человек');
});

test('D1 comparative operators use the genitive noun (SPEC §4 examples)', () => {
  assert.equal(text({ kind: 'room_count', room: 4, count: 1, op: 'gt' }),
    'В комнате_4 было более 1 человека');
  assert.equal(text({ kind: 'room_count', room: 4, count: 1, op: 'le' }),
    'В комнате_4 было не более 1 человека');
  assert.equal(text({ kind: 'room_count', room: 4, count: 11, op: 'ge' }),
    'В комнате_4 было не менее 11 человек');
  assert.equal(text({ kind: 'room_count', room: 4, count: 3, op: 'lt' }),
    'В комнате_4 было менее 3 человек');
});

test('personGenitive', () => {
  assert.equal(personGenitive('Подозреваемый_3'), 'Подозреваемого_3');
  assert.equal(personGenitive('Убитый'), 'Убитого');
});

test('clueToText has no trailing period', () => {
  for (const clue of [
    { kind: 'on', person: 'suspect_1', object_type: 'bed' },
    { kind: 'no_empty_rooms' },
    { kind: 'room_count', room: 3, count: 2, op: 'eq' },
    { kind: 'south', person: 'suspect_1', person2: 'suspect_2' },
  ]) {
    assert.ok(!text(clue).endsWith('.'), JSON.stringify(clue));
  }
});

test('clueToText throws on unknown kind / person / object type', () => {
  assert.throws(() => text({ kind: 'wat' }));
  assert.throws(() => text({ kind: 'on', person: 'alien', object_type: 'bed' }));
  assert.throws(() => clueToText({ kind: 'on', person: 'suspect_1', object_type: 'sauna' }, PEOPLE));
});
