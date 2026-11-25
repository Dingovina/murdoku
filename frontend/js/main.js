// App state, wiring, DOM. Placement rules and API calls live here.

import { fetchPuzzle, checkAnswer, revealSolution } from './api.js';
import { clueToText } from './clues.js';
import { Board } from './board.js';

const DIFFICULTY_DEFAULT = 'medium';

const state = {
  puzzle: null,
  token: null,
  board: null,
  placements: new Map(), // person_id -> {r, c}
  marks: new Set(),      // "r,c" marked as "no one here"
  busy: false,
  solved: false,
};

function $(id) { return document.getElementById(id); }

function personById(id) {
  return state.puzzle ? state.puzzle.people.find((p) => p.id === id) : null;
}

/** Board interactions are ignored while a request/load is in flight or solved. */
function canInteract() {
  return !state.busy && !state.solved && Boolean(state.puzzle && state.board);
}

// Test hooks (unused in the browser flow; lets node --test reach the guards).
export const __test = { state, canInteract, clearBoard };

function suspects() {
  return state.puzzle ? state.puzzle.people.filter((p) => p.id !== 'victim') : [];
}

function allPlaced() {
  return state.puzzle && state.placements.size === state.puzzle.people.length;
}

// --- init ---

function init() {
  if ($('mock-hint') && window.location.search.includes('mock=1')) {
    $('mock-hint').hidden = false;
  }
  $('new-game') && $('new-game').addEventListener('click', newGame);
  $('overlay-new-game') && $('overlay-new-game').addEventListener('click', () => {
    hideOverlay();
    newGame();
  });
  $('accuse') && $('accuse').addEventListener('click', accuse);
  $('accusation') && $('accusation').addEventListener('input', updateControls);
  $('clear-board') && $('clear-board').addEventListener('click', clearBoard);
  $('show-solution') && $('show-solution').addEventListener('click', giveUp);
  newGame();
}

// --- game lifecycle ---

async function newGame() {
  if (state.busy) return;
  state.busy = true;
  hideOverlay();
  setStatus('Загрузка пазла…');
  setControlsEnabled(false);
  try {
    const difficulty = ($('difficulty') && $('difficulty').value) || DIFFICULTY_DEFAULT;
    const { puzzle, token } = await fetchPuzzle(difficulty);
    state.puzzle = puzzle;
    state.token = token;
    state.placements = new Map();
    state.marks = new Set();
    state.solved = false;
    renderBoard();
    renderClues();
    renderPalette();
    setStatus('Разместите всех людей и укажите убийцу.');
  } catch (err) {
    setStatus('Не удалось загрузить пазл: ' + err.message, true);
  } finally {
    state.busy = false;
    setControlsEnabled(true);
    updateControls();
  }
}

function setControlsEnabled(enabled) {
  if ($('difficulty')) $('difficulty').disabled = !enabled;
  if ($('new-game')) $('new-game').disabled = !enabled;
  if ($('accuse')) $('accuse').disabled = !enabled || !canAccuse();
  if ($('clear-board')) $('clear-board').disabled = !enabled || !hasBoardProgress();
  if ($('show-solution')) $('show-solution').disabled = !enabled;
}

function renderBoard() {
  const container = $('board');
  if (!container) return;
  state.board = new Board(container, state.puzzle, {
    onDrop: tryPlace,
    onPlacedClick: returnToPalette,
    onCellClick: toggleMark,
    canDrag: (personId) => canInteract() && !state.placements.has(personId),
  });
}

function renderClues() {
  const list = $('clues');
  if (!list) return;
  list.innerHTML = '';
  const peopleMap = new Map(state.puzzle.people.map((p) => [p.id, p]));
  for (const clue of state.puzzle.clues) {
    const li = document.createElement('li');
    let text;
    try {
      text = clueToText(clue, peopleMap);
    } catch (err) {
      text = 'Неизвестная подсказка (' + err.message + ')';
    }
    li.textContent = text;
    list.appendChild(li);
  }
}

function renderPalette() {
  const palette = $('palette');
  if (!palette || !state.board) return;
  palette.innerHTML = '';
  for (const person of state.puzzle.people) {
    palette.appendChild(state.board.makePaletteChip(person));
  }
  refreshPaletteChips();

  const datalist = $('suspect-names');
  if (datalist) {
    datalist.innerHTML = '';
    for (const p of suspects()) {
      const option = document.createElement('option');
      option.value = p.name;
      datalist.appendChild(option);
    }
  }
}

function refreshPaletteChips() {
  const palette = $('palette');
  if (!palette || !state.board) return;
  for (const chip of palette.querySelectorAll('.chip')) {
    const id = chip.dataset.personId;
    chip.classList.toggle('chip--placed', state.placements.has(id));
  }
}

// --- board interactions ---

/** Drop a palette chip onto (r, c); silently ignored on illegal targets. */
function tryPlace(personId, r, c) {
  const board = state.board;
  if (!canInteract()) return;
  if (state.placements.has(personId)) return;
  if (!board.canDropAt(r, c)) return;    // void / full object / occupied
  state.placements.set(personId, { r, c });
  board.setMark(r, c, false);
  state.marks.delete(`${r},${c}`);
  board.placePerson(r, c, personById(personId));
  board.clearMisplaced();
  refreshPaletteChips();
  updateControls();
}

/** Click a placed portrait -> back to the palette. */
function returnToPalette(personId) {
  const board = state.board;
  if (!canInteract()) return;
  const pos = state.placements.get(personId);
  if (!pos) return;
  state.placements.delete(personId);
  board.removePerson(personId);
  board.clearMisplaced();
  refreshPaletteChips();
  updateControls();
}

/**
 * «Очистить поле»: every person back to the palette, all ✕ marks dropped.
 * @returns {boolean} true when something was actually cleared
 */
function clearBoard() {
  if (!canInteract()) return false;
  if (!hasBoardProgress()) return false;
  const board = state.board;
  for (const personId of [...state.placements.keys()]) {
    board.removePerson(personId);
  }
  state.placements.clear();
  dropAllMarks();
  board.clearMisplaced();
  refreshPaletteChips();
  updateControls();
  return true;
}

/** True when the board holds at least one placement or ✕ mark. */
function hasBoardProgress() {
  return state.placements.size > 0 || state.marks.size > 0;
}

/** Remove every ✕ mark from the board and the state. */
function dropAllMarks() {
  for (const key of state.marks) {
    const [r, c] = key.split(',').map(Number);
    state.board.setMark(r, c, false);
  }
  state.marks.clear();
}

/** Click an empty cell -> toggle the red «✕» («здесь никого»). */
function toggleMark(r, c) {
  const board = state.board;
  if (!canInteract()) return;
  if (placedAt(r, c) || board.isFullObject(r, c)) return;
  const k = `${r},${c}`;
  const marked = !state.marks.has(k);
  if (marked) state.marks.add(k); else state.marks.delete(k);
  board.setMark(r, c, marked);
  updateControls();
}

function placedAt(r, c) {
  for (const pos of state.placements.values()) {
    if (pos.r === r && pos.c === c) return true;
  }
  return false;
}

// --- accusation ---

/** Resolve the input text (trim, case-insensitive) to a suspect id or null. */
function resolveAccusation() {
  const input = $('accusation');
  if (!input) return null;
  const text = input.value.trim().toLowerCase();
  if (!text) return null;
  const match = suspects().find((p) => p.name.toLowerCase() === text);
  return match ? match.id : null;
}

function canAccuse() {
  return Boolean(state.puzzle) && allPlaced() && resolveAccusation() !== null;
}

/** Refresh the enable/disable state of every action button. */
function updateControls() {
  const accuse = $('accuse');
  if (accuse) accuse.disabled = state.busy || state.solved || !canAccuse();
  const clear = $('clear-board');
  if (clear) clear.disabled = !canInteract() || !hasBoardProgress();
  const reveal = $('show-solution');
  if (reveal) reveal.disabled = !canInteract();
}

/** «Показать решение»: give up, reveal the answer, end the game. */
async function giveUp() {
  if (!canInteract()) return;
  if (!window.confirm('Сдаться и показать решение?')) return;
  state.busy = true;
  setControlsEnabled(false);
  setStatus('Получаем решение…');
  try {
    const { solution, killer_id } = await revealSolution(state.token);
    dropAllMarks();
    applyReveal(solution);
    const killer = personById(killer_id);
    setStatus(`Убийца — ${killer ? killer.name : killer_id}. Решение показано.`);
  } catch (err) {
    setStatus('Не удалось получить решение: ' + err.message, true);
  } finally {
    state.busy = false;
    setControlsEnabled(true);
    updateControls();
  }
}

/** Render the reveal placement and end the game (only after a success). */
function applyReveal(solution) {
  state.board.showSolution(solution);
  // Keep the app state coherent with what the board now shows: everyone is
  // placed at the revealed solution, so palette chips all look placed.
  state.placements = new Map(Object.entries(solution).map(
    ([pid, rc]) => [pid, { r: rc[0], c: rc[1] }]));
  refreshPaletteChips();
  state.solved = true;
}

async function accuse() {
  if (state.busy || state.solved || !canAccuse()) return;
  const accusationId = resolveAccusation();
  if (accusationId === null) return; // do not send the request
  const placements = state.puzzle.people.map((p) => {
    const pos = state.placements.get(p.id);
    return { person_id: p.id, r: pos.r, c: pos.c };
  });
  state.busy = true;
  setControlsEnabled(false);
  setStatus('Проверяем…');
  try {
    const result = await checkAnswer(state.token, placements, accusationId);
    if (result.won) {
      state.solved = true;
      state.board.showSolution(result.solution);
      setStatus('');
      showOverlay(accusationId);
    } else if (result.misplaced_person_id) {
      state.board.clearMisplaced();
      state.board.setMisplaced(result.misplaced_person_id, true);
      const person = personById(result.misplaced_person_id);
      setStatus(`${person ? person.name : 'Человек'} не на своём месте.`);
    } else if (result.correct_accusation === false) {
      setStatus('Все люди на своих местах, но убийца указан неверно.');
    } else {
      setStatus('Проверка не пройдена.');
    }
  } catch (err) {
    setStatus('Ошибка проверки: ' + err.message, true);
  } finally {
    state.busy = false;
    setControlsEnabled(true);
    updateControls();
  }
}

// --- overlay / status ---

function showOverlay(killerId) {
  const overlay = $('overlay');
  const killer = personById(killerId);
  if ($('killer-name')) $('killer-name').textContent = killer ? killer.name : killerId;
  if (overlay) overlay.hidden = false;
}

function hideOverlay() {
  const overlay = $('overlay');
  if (overlay) overlay.hidden = true;
}

function setStatus(text, isError = false) {
  const status = $('status');
  if (!status) return;
  status.textContent = text;
  status.classList.toggle('status--error', Boolean(isError));
}

// Browser entry point only; node --test imports main.js for the test hooks
// (no `window` there, so init is skipped).
if (typeof window !== 'undefined') {
  init();
}
