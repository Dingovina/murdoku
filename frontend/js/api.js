// API wrappers. Real endpoints by default; mock mode only with ?mock=1 in the URL.

import * as mock from './mock.js';

function useMock() {
  return typeof window !== 'undefined' && window.location
    && window.location.search.includes('mock=1');
}

/**
 * GET /api/puzzle?difficulty=...[&seed=N]
 * @returns {Promise<{puzzle: object, token: string}>}
 */
export async function fetchPuzzle(difficulty, seed) {
  if (useMock()) return mock.fetchPuzzle(difficulty, seed);
  const params = new URLSearchParams({ difficulty: String(difficulty) });
  if (seed !== undefined && seed !== null && seed !== '') {
    params.set('seed', String(seed));
  }
  const res = await fetch('/api/puzzle?' + params.toString());
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
  return body;
}

/**
 * POST /api/check
 * @returns {Promise<{won: boolean, ...}>}
 */
export async function checkAnswer(token, placements, accusation) {
  if (useMock()) return mock.checkAnswer(token, placements, accusation);
  const res = await fetch('/api/check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, placements, accusation }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
  return body;
}

/**
 * GET /api/solution?token=... — reveal the answer (the player gives up).
 * @returns {Promise<{solution: object, killer_id: string}>}
 */
export async function revealSolution(token) {
  if (useMock()) return mock.revealSolution(token);
  const params = new URLSearchParams({ token: String(token) });
  const res = await fetch('/api/solution?' + params.toString());
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
  return body;
}
