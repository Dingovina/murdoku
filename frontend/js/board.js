// Board rendering + Pointer Events drag & drop. DOM-only logic; placement
// rules (occupied/full/void) are decided by main.js via handlers.

import { portraitOf } from './portraits.js';

// Object type registry: emoji icons and mergeability (SPEC §2).
const OBJECT_ICONS = {
  table: '🍽️',
  tv: '📺',
  wardrobe: '🚪',
  fridge: '❄️',
  bed: '🛏️',
  carpet: '🟫',
  armchair: '🪑',
  sofa: '🛋️',
};
const MERGEABLE = new Set(['table', 'carpet']);

export class Board {
  /**
   * @param {HTMLElement} container
   * @param {object} puzzle SPEC §4 puzzle JSON
   * @param {{onDrop?: Function, onPlacedClick?: Function, onCellClick?: Function,
   *          canDrag?: Function}} handlers
   */
  constructor(container, puzzle, handlers = {}) {
    this.container = container;
    this.puzzle = puzzle;
    this.handlers = handlers;
    this.locked = false;
    this.cellEls = new Map(); // "r,c" -> element
    this.chipByPerson = new Map(); // person_id -> chip element
    this.chipCell = new Map(); // person_id -> {r, c} (occupied cells)
    this.ghost = null;
    this._computeDerived();
    this.render();
  }

  _computeDerived() {
    const { width, height, rooms, objects } = this.puzzle;
    this.playable = new Set();
    this.roomOfCell = new Map();
    this.roomCorners = new Map(); // room id -> "r,c"
    for (const room of rooms) {
      for (const cell of room.cells) {
        const k = key(cell.r, cell.c);
        this.playable.add(k);
        this.roomOfCell.set(k, room.id);
        const corner = this.roomCorners.get(room.id);
        if (!corner || cell.r < corner.r || (cell.r === corner.r && cell.c < corner.c)) {
          this.roomCorners.set(room.id, cell);
        }
      }
    }
    this.objectAt = new Map(); // "r,c" -> object
    this.fullAt = new Set();
    for (const obj of objects) {
      const full = isFullType(obj.type);
      for (const cell of obj.cells) {
        const k = key(cell.r, cell.c);
        this.objectAt.set(k, obj);
        if (full) this.fullAt.add(k);
      }
    }
    this.width = width;
    this.height = height;
  }

  isPlayable(r, c) { return this.playable.has(key(r, c)); }
  isFullObject(r, c) { return this.fullAt.has(key(r, c)); }

  /** True when a person chip currently stands on (r, c). */
  isOccupied(r, c) {
    for (const pos of this.chipCell.values()) {
      if (pos.r === r && pos.c === c) return true;
    }
    return false;
  }

  /** Placement guard: void / full-object / occupied cells reject drops.
   *  (Whether the dragged person is already placed is main.js's concern.) */
  canDropAt(r, c) {
    return this.isPlayable(r, c) && !this.isFullObject(r, c) && !this.isOccupied(r, c);
  }

  cellEl(r, c) { return this.cellEls.get(key(r, c)) || null; }

  render() {
    this.container.innerHTML = '';
    this.cellEls.clear();
    this.chipByPerson.clear();
    this.chipCell.clear();
    this.container.style.gridTemplateColumns = `repeat(${this.width}, var(--cell))`;
    this.container.style.gridTemplateRows = `repeat(${this.height}, var(--cell))`;

    for (let r = 0; r < this.height; r++) {
      for (let c = 0; c < this.width; c++) {
        if (!this.isPlayable(r, c)) continue; // voids are not rendered
        const el = this._buildCell(r, c);
        this.container.appendChild(el);
        this.cellEls.set(key(r, c), el);
      }
    }
    this._renderObjects();
  }

  _buildCell(r, c) {
    const el = document.createElement('div');
    el.className = 'cell';
    el.dataset.r = String(r);
    el.dataset.c = String(c);
    el.style.gridRow = String(r + 1);
    el.style.gridColumn = String(c + 1);
    const roomId = this.roomOfCell.get(key(r, c));
    el.style.background = `hsl(${(roomId * 47) % 360}, 45%, 88%)`;
    this._applyWalls(el, r, c);

    const corner = this.roomCorners.get(roomId);
    if (corner && corner.r === r && corner.c === c) {
      const badge = document.createElement('span');
      badge.className = 'room-badge';
      badge.textContent = String(roomId);
      el.appendChild(badge);
    }

    if (!isFullType((this.objectAt.get(key(r, c)) || {}).type)) {
      el.addEventListener('click', () => {
        if (!this.locked) this.handlers.onCellClick && this.handlers.onCellClick(r, c);
      });
    }
    return el;
  }

  /** Thick walls: board edge / voids / different rooms; thin line inside a room. */
  _applyWalls(el, r, c) {
    const here = this.roomOfCell.get(key(r, c));
    const sides = [
      ['top', r - 1, c],
      ['left', r, c - 1],
      ['bottom', r + 1, c],
      ['right', r, c + 1],
    ];
    for (const [side, nr, nc] of sides) {
      const neighborRoom = this.roomOfCell.get(key(nr, nc));
      if (neighborRoom !== here) el.classList.add(`wall-${side}`);
    }
  }

  _renderObjects() {
    const rendered = new Set(); // object ids already consumed by a group
    for (const obj of this.puzzle.objects) {
      if (rendered.has(obj.id)) continue;
      const group = this._mergeGroup(obj);
      group.forEach((o) => rendered.add(o.id));
      this._renderObjectGroup(group);
    }
  }

  /** Connected component of same-type same-room mergeable instances. */
  _mergeGroup(obj) {
    if (!MERGEABLE.has(obj.type)) return [obj];
    const roomOf = (cell) => this.roomOfCell.get(key(cell.r, cell.c));
    const group = [obj];
    const seen = new Set([obj.id]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const other of this.puzzle.objects) {
        if (seen.has(other.id) || other.type !== obj.type) continue;
        if (roomOf(other.cells[0]) !== roomOf(obj.cells[0])) continue;
        const touches = group.some((g) =>
          g.cells.some((a) => other.cells.some((b) => adjacent(a, b))));
        if (touches) {
          group.push(other);
          seen.add(other.id);
          grew = true;
        }
      }
    }
    return group;
  }

  _renderObjectGroup(group) {
    const cells = group.flatMap((o) => o.cells);
    const full = isFullType(group[0].type);
    const multi = group.length > 1 || cells.length > 1; // merged or bed

    if (!multi) {
      const host = this.cellEl(cells[0].r, cells[0].c);
      if (!host) return; // defensive: cell outside the grid
      const icon = this._buildIcon(group, multi, full);
      host.appendChild(icon);
      host.classList.add(full ? 'cell--full' : 'cell--partial');
      return;
    }

    // A merged union is rarely a rectangle: one big icon over the union
    // bounding box would visually cover the non-merged cells of L/T shapes,
    // so render one icon per rectangle of a decomposition of the actual
    // cell union instead (SPEC §2: merging is visual only).
    for (const rect of this._unionRectangles(cells)) {
      const icon = this._buildIcon(group, multi, full);
      icon.style.gridRow = `${rect.r + 1} / span ${rect.h}`;
      icon.style.gridColumn = `${rect.c + 1} / span ${rect.w}`;
      this.container.appendChild(icon);
    }
    if (full) {
      // covered cells still show the "no drop" hatch
      for (const cell of cells) {
        const host = this.cellEl(cell.r, cell.c);
        if (host) host.classList.add('cell--full');
      }
    }
  }

  /** One object icon element (class + glyph, no grid positioning). */
  _buildIcon(group, multi, full) {
    const icon = document.createElement('span');
    icon.className = 'obj' + (multi ? ' obj--multi' : '') + (full ? ' obj--full' : '');
    icon.textContent = OBJECT_ICONS[group[0].type] || '❓';
    if (group.length > 1) icon.title = 'Объединённый объект';
    return icon;
  }

  /**
   * Greedy maximal-rectangle decomposition of the union of cells. Every
   * rectangle lies inside the union (a non-union cell is never covered):
   * repeatedly take the top-left-most remaining cell, extend the rectangle
   * right along its row as far as the union allows, then down while the
   * whole strip stays inside the union.
   */
  _unionRectangles(cells) {
    const remaining = new Set(cells.map(({ r, c }) => key(r, c)));
    const rects = [];
    while (remaining.size) {
      const [r0, c0] = [...remaining]
        .map((k) => k.split(',').map(Number))
        .sort((a, b) => a[0] - b[0] || a[1] - b[1])[0];
      let w = 1;
      while (remaining.has(key(r0, c0 + w))) w++;
      let h = 1;
      let grows = true;
      while (grows) {
        for (let c = c0; c < c0 + w; c++) {
          if (!remaining.has(key(r0 + h, c))) {
            grows = false;
            break;
          }
        }
        if (grows) h++;
      }
      for (let r = r0; r < r0 + h; r++) {
        for (let c = c0; c < c0 + w; c++) remaining.delete(key(r, c));
      }
      rects.push({ r: r0, c: c0, w, h });
    }
    return rects;
  }

  // --- people ---

  /**
   * Render a person chip inside a cell.
   * @param {object} person {id, name, portrait_seed}
   */
  placePerson(r, c, person) {
    const host = this.cellEl(r, c);
    if (!host || this.chipByPerson.has(person.id)) return;
    const chip = this._buildChip(person, true);
    chip.addEventListener('click', (e) => {
      e.stopPropagation();
      if (!this.locked) this.handlers.onPlacedClick && this.handlers.onPlacedClick(person.id);
    });
    host.appendChild(chip);
    this.chipByPerson.set(person.id, chip);
    this.chipCell.set(person.id, { r, c });
  }

  removePerson(personId) {
    const chip = this.chipByPerson.get(personId);
    if (chip) {
      chip.remove();
      this.chipByPerson.delete(personId);
      this.chipCell.delete(personId);
      chip.classList.remove('chip--misplaced');
    }
  }

  hasPerson(personId) { return this.chipByPerson.has(personId); }

  setMark(r, c, marked) {
    const host = this.cellEl(r, c);
    if (!host) return;
    let mark = host.querySelector('.mark');
    if (marked && !mark) {
      mark = document.createElement('span');
      mark.className = 'mark';
      mark.textContent = '✕';
      host.appendChild(mark);
    } else if (!marked && mark) {
      mark.remove();
    }
  }

  setMisplaced(personId, misplaced) {
    const chip = this.chipByPerson.get(personId);
    if (chip) chip.classList.toggle('chip--misplaced', Boolean(misplaced));
  }

  clearMisplaced() {
    for (const chip of this.chipByPerson.values()) {
      chip.classList.remove('chip--misplaced');
    }
  }

  /** Show the server solution (win state); locks interactions. */
  showSolution(solution) {
    this.locked = true;
    for (const chip of this.chipByPerson.values()) chip.remove();
    this.chipByPerson.clear();
    this.chipCell.clear();
    for (const [personId, rc] of Object.entries(solution)) {
      const [r, c] = rc;
      const person = this.puzzle.people.find((p) => p.id === personId);
      if (person) this.placePerson(r, c, person);
    }
  }

  setLocked(locked) { this.locked = Boolean(locked); }

  /** Build a palette chip (portrait + name) and make it a drag source. */
  makePaletteChip(person) {
    const chip = this._buildChip(person, true);
    chip.classList.add('chip--palette');
    this.attachDragSource(chip, person);
    return chip;
  }

  /** Attach Pointer Events drag source (a palette chip). */
  attachDragSource(el, person) {
    el.addEventListener('pointerdown', (e) => {
      if (this.locked || (e.button !== undefined && e.button !== 0)) return;
      if (this.handlers.canDrag && !this.handlers.canDrag(person.id)) return;
      e.preventDefault();
      let moved = false;
      const startX = e.clientX;
      const startY = e.clientY;
      try { el.setPointerCapture(e.pointerId); } catch { /* detached */ }

      const onMove = (ev) => {
        if (!moved && Math.hypot(ev.clientX - startX, ev.clientY - startY) < 4) return;
        moved = true;
        this._showGhost(person, ev.clientX, ev.clientY);
      };
      const finish = (ev, drop) => {
        el.removeEventListener('pointermove', onMove);
        el.removeEventListener('pointerup', onUp);
        el.removeEventListener('pointercancel', onCancel);
        this._hideGhost();
        if (drop && moved) {
          const target = document.elementFromPoint(ev.clientX, ev.clientY);
          const cell = target && target.closest ? target.closest('.cell') : null;
          if (cell) {
            this.handlers.onDrop && this.handlers.onDrop(
              person.id, Number(cell.dataset.r), Number(cell.dataset.c));
          }
        }
      };
      const onUp = (ev) => finish(ev, true);
      const onCancel = () => finish(null, false);
      el.addEventListener('pointermove', onMove);
      el.addEventListener('pointerup', onUp);
      el.addEventListener('pointercancel', onCancel);
    });
  }

  _showGhost(person, x, y) {
    if (!this.ghost) {
      this.ghost = this._buildChip(person, false);
      this.ghost.classList.add('drag-ghost');
      document.body.appendChild(this.ghost);
    }
    this.ghost.style.left = `${x}px`;
    this.ghost.style.top = `${y}px`;
  }

  _hideGhost() {
    if (this.ghost) {
      this.ghost.remove();
      this.ghost = null;
    }
  }

  _buildChip(person, withName) {
    const p = portraitOf(person);
    const chip = document.createElement('div');
    chip.className = 'chip' + (p.isVictim ? ' chip--victim' : '');
    chip.dataset.personId = person.id;
    chip.title = person.name;
    const circle = document.createElement('span');
    circle.className = 'chip__circle';
    circle.style.background = p.bg;
    circle.style.color = p.fg;
    circle.textContent = p.initial;
    chip.appendChild(circle);
    if (withName) {
      const label = document.createElement('span');
      label.className = 'chip__name';
      label.textContent = person.name;
      chip.appendChild(label);
    }
    return chip;
  }
}

function key(r, c) { return `${r},${c}`; }

function adjacent(a, b) {
  return Math.abs(a.r - b.r) + Math.abs(a.c - b.c) === 1;
}

function isFullType(type) {
  // Full classes per SPEC §2: table, tv, wardrobe, fridge.
  return type === 'table' || type === 'tv' || type === 'wardrobe' || type === 'fridge';
}
