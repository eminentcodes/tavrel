import test from 'node:test';
import assert from 'node:assert/strict';
import { installedWallets, rememberWallet, walletAccounts, walletProvider, signPayment, walletRequest } from '../frontend/src/wallet.js';

const address = '0x' + '12'.repeat(32);
const storage = new Map();
globalThis.sessionStorage = {
  setItem: (key, value) => storage.set(key, value),
  getItem: key => storage.get(key) ?? null,
  removeItem: key => storage.delete(key),
};
globalThis.window = { injectedWeb3: {} };

test('selected wallet connects without waiting for another installed extension', async () => {
  let otherRequests = 0; let selectedRequests = 0;
  window.injectedWeb3 = {
    'subwallet-test': { enable: async () => { selectedRequests++; return { accounts: { get: async () => [{ address, name: 'Native account', type: 'sr25519' }] } }; } },
    talisman: { enable: () => { otherRequests++; return new Promise(() => {}); } },
  };
  assert.deepEqual(installedWallets().map(wallet => wallet.name), ['SubWallet', 'Talisman']);
  const accounts = await walletAccounts('subwallet-test');
  assert.equal(accounts[0].meta.name, 'Native account');
  assert.equal(accounts[0].meta.source, 'subwallet-test');
  await walletAccounts('subwallet-test');
  assert.equal(selectedRequests, 1);
  assert.equal(otherRequests, 0);
});

test('unsupported Ethereum and malformed accounts are excluded from native sign-in', async () => {
  window.injectedWeb3 = { nativeOnly: { enable: async () => ({ accounts: { get: async () => [
    { address: '0x' + '34'.repeat(20), type: 'ethereum' },
    { address: 'bad address' }, { address, type: 'ed25519' },
  ] } }) } };
  assert.deepEqual((await walletAccounts('nativeOnly')).map(account => account.address), [address]);
});

test('wallet access rejection can be retried', async () => {
  let attempts = 0;
  window.injectedWeb3 = { retryWallet: { enable: async () => {
    if (++attempts === 1) throw new Error('Access rejected');
    return { accounts: { get: async () => [{ address }] } };
  } } };
  await assert.rejects(walletProvider('retryWallet'), /Access rejected/);
  assert.equal((await walletAccounts('retryWallet')).length, 1);
  assert.equal(attempts, 2);
});

test('payment signing uses the selected wallet and preserves the exact payload', async () => {
  const signed = []; let requests = 0;
  window.injectedWeb3 = { paymentWallet: { connect: async () => {
    requests++;
    return { accounts: { get: async () => [{ address }] }, signer: {
      signPayload: async payload => { signed.push(payload); return { signature: '0xsignature', signedTransaction: '0xtransaction' }; },
    } };
  } } };
  rememberWallet('paymentWallet');
  const payload = { method: '0x1234', nonce: '0x02', genesisHash: '0xgenesis', era: '0xera' };
  assert.deepEqual(await signPayment(payload, address), { signature: '0xsignature', signed_hex: '0xtransaction' });
  assert.deepEqual(signed, [{ ...payload, address }]);
  await assert.rejects(signPayment(payload, '0x' + '34'.repeat(32)), /sender/);
  assert.equal(signed.length, 1);
  assert.equal(requests, 1);
  rememberWallet(null);
  await assert.rejects(signPayment(payload, address), /Connect your wallet again/);
});

test('SubWallet requests native account access through its documented enable API', async () => {
  const requests = []; let connectCalls = 0;
  window.injectedWeb3['subwallet-native'] = {
    enable: async (...args) => { requests.push(args); return { accounts: { get: async () => [{ address }] } }; },
    connect: () => { connectCalls++; return new Promise(() => {}); },
  };
  assert.equal((await walletAccounts('subwallet-native')).length, 1);
  assert.deepEqual(requests, [['Tavrel', { accountAuthType: 'substrate' }]]);
  assert.equal(connectCalls, 0);
});

test('new connect-style wallets work even when enable is a rejecting compatibility shim', async () => {
  let shimCalls = 0;
  window.injectedWeb3['new-style'] = {
    enable: () => { shimCalls++; throw new Error('Only connect is supported'); },
    connect: async () => ({ accounts: { get: async () => [{ address }] } }),
  };
  assert.equal((await walletAccounts('new-style')).length, 1);
  assert.equal(shimCalls, 0);
});

test('hung authorization expires, ignores a late provider, and retries only on request', async () => {
  let attempts = 0; let finishOld;
  const oldProvider = { accounts: { get: async () => [{ address, name: 'Old provider' }] } };
  window.injectedWeb3.expiringWallet = { enable: () => {
    if (++attempts === 1) return new Promise(resolve => { finishOld = resolve; });
    return Promise.resolve({ accounts: { get: async () => [{ address, name: 'New provider' }] } });
  } };
  await assert.rejects(walletProvider('expiringWallet', { timeoutMs: 15 }), /did not respond/);
  assert.equal(attempts, 1);
  finishOld(oldProvider);
  assert.equal((await walletAccounts('expiringWallet'))[0].meta.name, 'New provider');
  assert.equal(attempts, 2);
});

test('cancelling authorization clears a pending provider without starting another prompt', async () => {
  const controller = new AbortController(); let attempts = 0; let finish;
  window.injectedWeb3.cancelWallet = { enable: () => { attempts++; return new Promise(resolve => { finish = resolve; }); } };
  const pending = walletProvider('cancelWallet', { signal: controller.signal });
  controller.abort();
  await assert.rejects(pending, { name: 'AbortError' });
  assert.equal(attempts, 1);
  finish({ accounts: { get: async () => [{ address }] } });
  window.injectedWeb3.cancelWallet.enable = async () => { attempts++; return { accounts: { get: async () => [{ address }] } }; };
  assert.equal((await walletAccounts('cancelWallet')).length, 1);
  assert.equal(attempts, 2);
});

test('a hanging account list cannot leave the connection loading indefinitely', async () => {
  let requests = 0;
  window.injectedWeb3.hungAccounts = { enable: async () => {
    requests++;
    return { accounts: { get: requests === 1 ? () => new Promise(() => {}) : async () => [{ address }] } };
  } };
  await assert.rejects(walletAccounts('hungAccounts', { timeoutMs: 15 }), /did not respond/);
  assert.equal(requests, 1);
  assert.equal((await walletAccounts('hungAccounts')).length, 1);
  assert.equal(requests, 2);
});

test('an already cancelled wallet operation never invokes the extension', async () => {
  let calls = 0;
  await assert.rejects(walletRequest(() => { calls++; }, { signal: AbortSignal.abort() }), { name: 'AbortError' });
  assert.equal(calls, 0);
});
