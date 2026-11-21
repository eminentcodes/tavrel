import { test } from 'node:test';
import assert from 'node:assert/strict';
import { request } from '../frontend/src/api.js';

test('empty POST responses show a connection error and do not repeat actions', async () => {
  let calls = 0;
  const original = globalThis.fetch;
  globalThis.fetch = async () => { calls++; return new Response('', { status: 200 }); };
  try { await assert.rejects(request('/v1/auth/verify', 'POST', {}), /connection was interrupted/); assert.equal(calls, 1); }
  finally { globalThis.fetch = original; }
});

test('an empty read can retry once without repeating a mutation', async () => {
  let calls = 0;
  const original = globalThis.fetch;
  globalThis.fetch = async () => ++calls === 1 ? new Response('') : new Response(JSON.stringify({ ok: true, result: { authenticated: false } }));
  try { assert.deepEqual(await request('/v1/auth/status'), { authenticated: false }); assert.equal(calls, 2); }
  finally { globalThis.fetch = original; }
});

test('cancelled sign-in HTTP requests pass cancellation to fetch without retry', async () => {
  const original = globalThis.fetch; const controller = new AbortController(); let calls = 0;
  globalThis.fetch = (path, options) => {
    calls++;
    return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(options.signal.reason), { once: true }));
  };
  try {
    const pending = request('/v1/auth/verify', 'POST', {}, { signal: controller.signal });
    controller.abort();
    await assert.rejects(pending, { name: 'AbortError' });
    assert.equal(calls, 1);
    await assert.rejects(request('/v1/auth/challenge', 'POST', {}, { signal: controller.signal }), { name: 'AbortError' });
    assert.equal(calls, 1);
  } finally { globalThis.fetch = original; }
});
