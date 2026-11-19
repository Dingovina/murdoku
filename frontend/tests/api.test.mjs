// Tests for api.js pure behavior: mock switch (?mock=1), seed param handling,
// error-body mapping. window/fetch are stubbed; no real network.
import test from 'node:test';
import assert from 'node:assert/strict';
import { fetchPuzzle, checkAnswer } from '../js/api.js';

const realFetch = globalThis.fetch;
const realWindow = globalThis.window;

function useWindow(search) {
  globalThis.window = { location: { search } };
}

let calls = [];
function stubFetch(respond) {
  calls = [];
  globalThis.fetch = async (url, opts) => {
    calls.push({ url: String(url), opts });
    return respond(url, opts);
  };
}

test.afterEach(() => {
  globalThis.fetch = realFetch;
  globalThis.window = realWindow;
});

test('mock mode (?mock=1) never calls fetch and serves the sample puzzle', async () => {
  useWindow('?mock=1');
  stubFetch(() => { throw new Error('fetch must not be called in mock mode'); });
  const { puzzle, token } = await fetchPuzzle('easy');
  assert.equal(puzzle.width, 6);
  assert.ok(token.length > 0);
  await assert.rejects(
    () => checkAnswer('garbage-token', [{ person_id: 'suspect_1', r: 0, c: 5 }], 'suspect_1'),
    (err) => err.status === 400,
  );
  assert.equal(calls.length, 0);
});

test('no window / no mock param -> real endpoint GET /api/puzzle', async () => {
  globalThis.window = undefined;
  stubFetch(() => ({ ok: true, status: 200, json: async () => ({ ok: 1 }) }));
  const body = await fetchPuzzle('medium');
  assert.deepEqual(body, { ok: 1 });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/puzzle?difficulty=medium');
});

test('seed is appended only when provided', async () => {
  globalThis.window = undefined;
  stubFetch(() => ({ ok: true, status: 200, json: async () => ({}) }));
  await fetchPuzzle('hard', 42);
  assert.equal(calls[0].url, '/api/puzzle?difficulty=hard&seed=42');
  await fetchPuzzle('hard', '7');
  assert.equal(calls[1].url, '/api/puzzle?difficulty=hard&seed=7');
  await fetchPuzzle('easy', null);
  await fetchPuzzle('easy', '');
  assert.equal(calls[2].url, '/api/puzzle?difficulty=easy');
  assert.equal(calls[3].url, '/api/puzzle?difficulty=easy');
});

test('mock=1 inside another param value also activates mock mode', async () => {
  // documents current behavior: literal substring match on the query string
  useWindow('?x=1&mock=1');
  stubFetch(() => { throw new Error('fetch must not be called'); });
  await fetchPuzzle('easy');
  assert.equal(calls.length, 0);
});

test('checkAnswer posts JSON body to /api/check', async () => {
  globalThis.window = undefined;
  stubFetch(() => ({ ok: true, status: 200, json: async () => ({ won: true }) }));
  const result = await checkAnswer('tok', [{ person_id: 'victim', r: 1, c: 2 }], 'suspect_1');
  assert.deepEqual(result, { won: true });
  const { url, opts } = calls[0];
  assert.equal(url, '/api/check');
  assert.equal(opts.method, 'POST');
  assert.equal(opts.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(opts.body), {
    token: 'tok',
    placements: [{ person_id: 'victim', r: 1, c: 2 }],
    accusation: 'suspect_1',
  });
});

test('error body {error} is mapped to the thrown message', async () => {
  globalThis.window = undefined;
  stubFetch(() => ({ ok: false, status: 400, json: async () => ({ error: 'bad seed' }) }));
  await assert.rejects(() => fetchPuzzle('nope'), (err) => err.message === 'bad seed');
  await assert.rejects(() => checkAnswer('t', [], 'suspect_1'),
    (err) => err.message === 'bad seed');
});

test('non-JSON error body falls back to "HTTP <status>"', async () => {
  globalThis.window = undefined;
  stubFetch(() => ({
    ok: false, status: 500,
    json: async () => { throw new TypeError('Unexpected token'); },
  }));
  await assert.rejects(() => fetchPuzzle('easy'), (err) => err.message === 'HTTP 500');
  await assert.rejects(() => checkAnswer('t', [], 'x'), (err) => err.message === 'HTTP 500');
});
