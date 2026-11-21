/** Real offline agent signatures over stored Volta metadata. No live transfers. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { TypeRegistry } from '@polkadot/types';
import { cryptoWaitReady, sr25519PairFromSeed, encodeAddress } from '@polkadot/util-crypto';
import { u8aToHex } from '@polkadot/util';
import { verifyPayloadSignature } from '../tavrel/native_signing.mjs';
await cryptoWaitReady();
const seed = new Uint8Array(32).fill(7);
const pair = sr25519PairFromSeed(seed);
const sender = u8aToHex(pair.publicKey);
const payload = { ...JSON.parse(await readFile('artifacts/native-rpc-check.json', 'utf8')).payload, address: encodeAddress(pair.publicKey, 251) };
const registry = new TypeRegistry();
registry.setSignedExtensions(payload.signedExtensions);
function operate(values) {
  const result = spawnSync(process.execPath, ['tavrel/agent_wallet.mjs'], { input: JSON.stringify({ seed: u8aToHex(seed), ...values }), encoding: 'utf8', windowsHide: true });
  assert.equal(result.stdout.includes(u8aToHex(seed)), false);
  return JSON.parse(result.stdout);
}
test('generated agent wallet signs the exact native payload', async () => {
  const result = operate({ action: 'sign', sender, payload });
  assert.equal(result.ok, true);
  assert.equal(await verifyPayloadSignature(registry, payload, result.result.signature, sender), true);
  assert.equal(await verifyPayloadSignature(registry, { ...payload, nonce: '0x00000001' }, result.result.signature, sender), false);
});
test('agent wallet refuses a different signing account or network', () => {
  assert.equal(operate({ action: 'sign', sender: '0x' + '22'.repeat(32), payload }).ok, false);
  assert.equal(operate({ action: 'sign', sender, payload: { ...payload, genesisHash: '0x' + '22'.repeat(32) } }).ok, false);
});
