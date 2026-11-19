// Board rendering/interaction tests against a minimal DOM stub (Node has no
// browser here). Covers walls, badge, merge bbox, bed span, drop guards,
// misplaced outline, marks and the interaction lock.
import test from 'node:test';
import assert from 'node:assert/strict';

// --- minimal DOM stub ---

class ClassList {
  constructor() { this.s = new Set(); }
  add(...cs) { cs.forEach((c) => this.s.add(c)); }
  remove(...cs) { cs.forEach((c) => this.s.delete(c)); }
  toggle(c, force) {
    const want = force === undefined ? !this.s.has(c) : Boolean(force);
    if (want) this.s.add(c); else this.s.delete(c);
    return want;
  }
  contains(c) { return this.s.has(c); }
}

class FakeEl {
  constructor(tag) {
    this.tagName = tag;
    this.parentNode = null;
    this.classList = new ClassList();
    this.dataset = {};
    this.style = {};
    this.listeners = {};
    this.textContent = '';
    this.hidden = false;
    this.title = '';
    this._children = [];
    Object.defineProperty(this, 'children', { get: () => this._children });
    Object.defineProperty(this, 'innerHTML', {
      set() { this._children.length = 0; },
      get() { return ''; },
    });
  }
  get className() { return [...this.classList.s].join(' '); }
  set className(v) { this.classList.s.clear(); for (const c of String(v).split(/\s+/)) if (c) this.classList.add(c); }
  appendChild(el) { el.parentNode = this; this._children.push(el); return el; }
  remove() {
    if (this.parentNode) {
      const i = this.parentNode._children.indexOf(this);
      if (i >= 0) this.parentNode._children.splice(i, 1);
      this.parentNode = null;
    }
  }
  addEventListener(t, fn) { (this.listeners[t] ??= []).push(fn); }
  removeEventListener(t, fn) {
    const arr = this.listeners[t];
    if (arr) { const i = arr.indexOf(fn); if (i >= 0) arr.splice(i, 1); }
  }
  querySelector(sel) {
    const name = sel.slice(1);
    return this._children.find((c) => c.classList.contains(name)) || null;
  }
  closest(sel) {
    const name = sel.slice(1);
    let el = this;
    while (el) {
      if (el.classList.contains(name)) return el;
      el = el.parentNode;
    }
    return null;
  }
  click() { (this.listeners.click ?? []).forEach((fn) => fn({ stopPropagation() {} })); }
  fire(type, ev) { (this.listeners[type] ?? []).forEach((fn) => fn(ev)); }
}

globalThis.document = {
  createElement: (t) => new FakeEl(t),
  body: new FakeEl('body'),
  elementFromPoint: () => null,
  getElementById: () => null,
};

const { Board } = await import('../js/board.js');
const { fetchPuzzle, SAMPLE_SOLUTION } = await import('../js/mock.js');
const { puzzle } = await fetchPuzzle('medium');

function makeBoard(handlers = {}) {
  return new Board(new FakeEl('div'), puzzle, handlers);
}
const cellOf = (board, r, c) => board.cellEl(r, c);
const classes = (el) => [...el.classList.s];
const person = (id) => puzzle.people.find((p) => p.id === id);

// --- rendering ---

test('renders only playable cells; voids are absent', () => {
  const board = makeBoard();
  assert.equal(board.cellEls.size, 28, '28 playable cells on the 6x6 sample');
  assert.equal(cellOf(board, 4, 0), null, 'void cell');
  assert.equal(cellOf(board, 5, 3), null, 'void cell');
});

test('walls: board edges, room boundaries and voids; none inside a room', () => {
  const board = makeBoard();
  // (0,0): top/left board edges
  assert.deepEqual(classes(cellOf(board, 0, 0)).filter((c) => c.startsWith('wall'))
    .sort(), ['wall-left', 'wall-top']);
  // (1,0): bottom is room 3, right neighbor (1,1) is same room 1
  const w10 = classes(cellOf(board, 1, 0)).filter((c) => c.startsWith('wall'));
  assert.ok(w10.includes('wall-bottom'));
  assert.ok(!w10.includes('wall-top'));
  assert.ok(!w10.includes('wall-right'));
  // (4,5): right edge (same room below, so no wall-bottom)
  const w45 = classes(cellOf(board, 4, 5)).filter((c) => c.startsWith('wall'));
  assert.ok(w45.includes('wall-right'));
  assert.ok(!w45.includes('wall-bottom'));
  // (5,5): right and bottom edges of the board
  const w55 = classes(cellOf(board, 5, 5)).filter((c) => c.startsWith('wall'));
  assert.ok(w55.includes('wall-right') && w55.includes('wall-bottom'));
  // (3,1): neighbor (4,1) is void -> wall
  assert.ok(classes(cellOf(board, 3, 1)).includes('wall-bottom'));
});

test('room number badge sits on the room corner cell only', () => {
  const board = makeBoard();
  const badge = (el) => {
    const b = el._children.find((c) => c.classList.contains('room-badge'));
    return b ? b.textContent : null;
  };
  assert.equal(badge(cellOf(board, 0, 0)), '1');
  assert.equal(badge(cellOf(board, 1, 1)), null, 'non-corner cell of room 1');
  assert.equal(badge(cellOf(board, 2, 4)), '5', 'corner of room 5');
});

test('mergeable table pair renders as one icon over the union bbox', () => {
  const board = makeBoard();
  const multi = board.container._children.filter((el) => el.classList.contains('obj--multi'));
  const table = multi.find((el) => el.style.gridColumn === '2 / span 2');
  assert.ok(table, 'table icon spans (0,1)-(0,2)');
  assert.equal(table.style.gridRow, '1 / span 1');
});

test('bed renders as one icon across both cells', () => {
  const board = makeBoard();
  const multi = board.container._children.filter((el) => el.classList.contains('obj--multi'));
  const bed = multi.find((el) => el.style.gridColumn === '1 / span 2');
  assert.ok(bed, 'bed icon spans two columns');
  assert.equal(bed.style.gridRow, '2 / span 1');
});

test('full object covers the cell and is not clickable; partial cell stays clickable', () => {
  const board = makeBoard();
  const tv = cellOf(board, 0, 4);
  assert.ok(classes(tv).includes('cell--full'));
  assert.ok(tv._children.some((c) => c.classList.contains('obj--full')));
  assert.equal((tv.listeners.click ?? []).length, 0, 'no click handler on a full cell');
  const sofa = cellOf(board, 1, 3);
  assert.ok(classes(sofa).includes('cell--partial'));
  assert.equal((sofa.listeners.click ?? []).length, 1);
});

test('room tint is hsl(id*47 % 360, 45%, 88%)', () => {
  const board = makeBoard();
  assert.equal(cellOf(board, 0, 0).style.background, 'hsl(47, 45%, 88%)');
  assert.equal(cellOf(board, 2, 4).style.background, `hsl(${(5 * 47) % 360}, 45%, 88%)`);
});

// --- placement guards ---

test('canDropAt rejects voids, full objects and occupied cells', () => {
  const board = makeBoard();
  assert.equal(board.canDropAt(4, 0), false, 'void');
  assert.equal(board.canDropAt(0, 4), false, 'tv (full object)');
  assert.equal(board.canDropAt(0, 1), false, 'merged table cell (full)');
  assert.equal(board.canDropAt(1, 3), true, 'sofa cell (partial) is allowed');
  assert.equal(board.canDropAt(2, 2), true, 'free cell');
  board.placePerson(2, 2, person('suspect_1'));
  assert.equal(board.canDropAt(2, 2), false, 'occupied');
  assert.equal(board.canDropAt(3, 1), true);
});

// --- people chips, misplaced outline, marks ---

test('placePerson / removePerson / misplaced outline', () => {
  const board = makeBoard();
  board.placePerson(0, 5, person('suspect_1'));
  const chip = cellOf(board, 0, 5)._children.find((c) => c.classList.contains('chip'));
  assert.ok(chip, 'chip rendered');
  assert.equal(chip.title, 'Подозреваемый_1');
  board.setMisplaced('suspect_1', true);
  assert.ok(chip.classList.contains('chip--misplaced'));
  board.clearMisplaced();
  assert.ok(!chip.classList.contains('chip--misplaced'));
  board.removePerson('suspect_1');
  assert.equal(board.chipByPerson.size, 0);
  assert.equal(board.chipCell.size, 0);
});

test('red ✕ mark toggles per cell', () => {
  const board = makeBoard();
  board.setMark(2, 2, true);
  assert.ok(cellOf(board, 2, 2).querySelector('.mark'));
  board.setMark(2, 2, false);
  assert.equal(cellOf(board, 2, 2).querySelector('.mark'), null);
});

test('placed chip click routes to onPlacedClick and not onCellClick', () => {
  const placed = [];
  const cells = [];
  const board = makeBoard({
    onPlacedClick: (id) => placed.push(id),
    onCellClick: (r, c) => cells.push([r, c]),
  });
  board.placePerson(0, 5, person('victim'));
  const chip = cellOf(board, 0, 5)._children.find((c) => c.classList.contains('chip'));
  assert.ok(chip.classList.contains('chip--victim'), 'victim chip styled');
  chip.click();
  assert.deepEqual(placed, ['victim']);
  assert.deepEqual(cells, [], 'cell click suppressed by stopPropagation');
});

test('locked board ignores clicks; showSolution renders the placement', () => {
  const placed = [];
  const cells = [];
  const board = makeBoard({
    onPlacedClick: (id) => placed.push(id),
    onCellClick: (r, c) => cells.push([r, c]),
  });
  board.showSolution(SAMPLE_SOLUTION);
  assert.equal(board.locked, true);
  assert.equal(board.chipByPerson.size, 5);
  cellOf(board, 2, 2).click();
  const chip = cellOf(board, 0, 5)._children.find((c) => c.classList.contains('chip'));
  chip.click();
  assert.deepEqual(cells, []);
  assert.deepEqual(placed, [], 'locked board ignores clicks');
});

// --- drag & drop ---

test('palette chip drag: pointerdown -> move -> up over a cell fires onDrop', () => {
  let dropped = null;
  const board = makeBoard({ onDrop: (id, r, c) => { dropped = [id, r, c]; }, canDrag: () => true });
  const chip = board.makePaletteChip(person('suspect_2'));
  const target = new FakeEl('div');
  target.classList.add('cell');
  target.dataset.r = '2';
  target.dataset.c = '0';
  document.elementFromPoint = () => target;
  const base = { button: 0, pointerId: 1, preventDefault() {} };
  chip.fire('pointerdown', { ...base, clientX: 10, clientY: 10 });
  chip.fire('pointermove', { ...base, clientX: 40, clientY: 60 });
  assert.ok(document.body._children.some((c) => c.classList.contains('drag-ghost')),
    'ghost follows the pointer');
  chip.fire('pointerup', { ...base, clientX: 40, clientY: 60 });
  assert.deepEqual(dropped, ['suspect_2', 2, 0]);
  assert.equal(document.body._children.filter((c) => c.classList.contains('drag-ghost')).length, 0,
    'ghost removed after drop');
});

test('drag with no cell under the pointer is a no-op; click without move does not drop', () => {
  let drops = 0;
  const board = makeBoard({ onDrop: () => { drops += 1; }, canDrag: () => true });
  const chip = board.makePaletteChip(person('suspect_1'));
  document.elementFromPoint = () => null;
  const base = { button: 0, pointerId: 1, preventDefault() {} };
  chip.fire('pointerdown', { ...base, clientX: 0, clientY: 0 });
  chip.fire('pointermove', { ...base, clientX: 30, clientY: 30 });
  chip.fire('pointerup', { ...base, clientX: 30, clientY: 30 });
  assert.equal(drops, 0);
  // no drag movement -> treated as a click, no drop attempt
  chip.fire('pointerdown', { ...base, clientX: 0, clientY: 0 });
  chip.fire('pointerup', { ...base, clientX: 1, clientY: 1 });
  assert.equal(drops, 0);
});

test('canDrag=false blocks the drag at pointerdown', () => {
  let drops = 0;
  const board = makeBoard({ onDrop: () => { drops += 1; }, canDrag: () => false });
  const chip = board.makePaletteChip(person('suspect_1'));
  const target = new FakeEl('div');
  target.classList.add('cell');
  target.dataset.r = '3';
  target.dataset.c = '3';
  document.elementFromPoint = () => target;
  const base = { button: 0, pointerId: 1, preventDefault() {} };
  chip.fire('pointerdown', { ...base, clientX: 0, clientY: 0 });
  chip.fire('pointermove', { ...base, clientX: 30, clientY: 30 });
  chip.fire('pointerup', { ...base, clientX: 30, clientY: 30 });
  assert.equal(drops, 0, 'drag never started');
  assert.equal(document.body._children.length, 0, 'no ghost created');
});

// --- main.js interaction guards (busy / solved) ---

test('main.js canInteract: false while busy or solved or without puzzle', async () => {
  const { __test } = await import('../js/main.js');
  const { state, canInteract } = __test;
  const saved = { ...state };
  try {
    state.puzzle = null;
    state.board = null;
    state.busy = false;
    state.solved = false;
    assert.equal(canInteract(), false, 'no puzzle loaded');
    state.puzzle = {};
    state.board = {};
    assert.equal(canInteract(), true);
    state.busy = true;
    assert.equal(canInteract(), false, 'request in flight');
    state.busy = false;
    state.solved = true;
    assert.equal(canInteract(), false, 'already solved');
  } finally {
    Object.assign(state, saved);
  }
});
