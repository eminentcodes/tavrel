import test from 'node:test';
import assert from 'node:assert/strict';
import { authenticateWallet } from '../frontend/src/wallet-login.js';

const address = '0x' + '56'.repeat(32);
const account = source => ({ address, meta: { source } });
globalThis.window = { injectedWeb3: {} };

async function withGateway(work) {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (path, options) => {
    calls.push({ path, body: JSON.parse(options.body) });
    return new Response(JSON.stringify({ ok: true, result: path.endsWith('/challenge')
      ? { message: 'Exact sign-in message', challenge_id: 'challenge' } : { authenticated: true, account: address } }));
  };
  try { await work(calls); } finally { globalThis.fetch = original; }
}

test('a cancelled sign-in ignores a late signature and never verifies it', async () => {
  await withGateway(async calls => {
    let finishSign; let started;
    const waiting = new Promise(resolve => { started = resolve; });
    window.injectedWeb3.cancelLogin = { enable: async () => ({ accounts: { get: async () => [] }, signer: {
      signRaw: () => new Promise(resolve => { finishSign = resolve; started(); }),
    } }) };
    const controller = new AbortController();
    const login = authenticateWallet(account('cancelLogin'), { signal: controller.signal });
    await waiting;
    controller.abort();
    await assert.rejects(login, { name: 'AbortError' });
    finishSign({ signature: 'late-signature' });
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(calls.map(call => call.path), ['/v1/auth/challenge']);
  });
});

test('a sign request times out without automatically verifying or repeating it', async () => {
  await withGateway(async calls => {
    let requests = 0; let authorizations = 0;
    window.injectedWeb3.timeoutLogin = { enable: async () => {
      authorizations++;
      return { accounts: { get: async () => [] }, signer: {
        signRaw: () => { requests++; return requests === 1 ? new Promise(() => {}) : Promise.resolve({ signature: 'fresh-signature' }); },
      } };
    } };
    await assert.rejects(authenticateWallet(account('timeoutLogin'), { timeoutMs: 15 }), /sign-in request timed out/);
    assert.equal(requests, 1);
    assert.deepEqual(calls.map(call => call.path), ['/v1/auth/challenge']);
    assert.equal((await authenticateWallet(account('timeoutLogin'))).authenticated, true);
    assert.equal(authorizations, 2);
    assert.equal(requests, 2);
    assert.deepEqual(calls.map(call => call.path), ['/v1/auth/challenge', '/v1/auth/challenge', '/v1/auth/verify']);
  });
});

test('a successful login signs the exact challenge and verifies once', async () => {
  await withGateway(async calls => {
    const signed = []; const progress = [];
    window.injectedWeb3.goodLogin = { enable: async () => ({ accounts: { get: async () => [] }, signer: {
      signRaw: async payload => { signed.push(payload); return { signature: 'valid-signature' }; },
    } }) };
    assert.deepEqual(await authenticateWallet(account('goodLogin'), { onProgress: value => progress.push(value) }), { authenticated: true, account: address });
    assert.deepEqual(signed, [{ address, type: 'bytes', data: '0x' + Buffer.from('Exact sign-in message').toString('hex') }]);
    assert.deepEqual(calls, [
      { path: '/v1/auth/challenge', body: { address } },
      { path: '/v1/auth/verify', body: { challenge_id: 'challenge', signature: 'valid-signature' } },
    ]);
    assert.deepEqual(progress, ['Preparing sign-in', 'Confirm in your wallet', 'Verifying signature']);
  });
});
