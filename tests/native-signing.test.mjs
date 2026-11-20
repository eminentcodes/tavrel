/** Offline keys and stored public metadata; never signs/submits through live RPC. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { TypeRegistry } from '@polkadot/types';
import { blake2AsU8a, cryptoWaitReady, sr25519PairFromSeed, sr25519Sign } from '@polkadot/util-crypto';
import { u8aToHex } from '@polkadot/util';
import { verifyPayloadSignature } from '../tavrel/native_signing.mjs';

await cryptoWaitReady();
const pair = sr25519PairFromSeed(blake2AsU8a('Offline transaction-signature fixture only'));
const payload = JSON.parse(await readFile('artifacts/native-rpc-check.json', 'utf8')).payload;
const registry = new TypeRegistry();
registry.setSignedExtensions(payload.signedExtensions);
const bytes = registry.createType('ExtrinsicPayload', payload, { version: payload.version }).toU8a({ method: true });
const signature = '0x01' + u8aToHex(sr25519Sign(bytes.length > 256 ? blake2AsU8a(bytes) : bytes, pair)).slice(2);
const sender = u8aToHex(pair.publicKey);

test('native signature authorizes the exact stored signing payload', async () => {
  assert.equal(await verifyPayloadSignature(registry, payload, signature, sender), true);
});
test('changes to call, nonce, mortality, genesis, runtime version, or tip invalidate authorization', async () => {
  for (const [key, value] of [['method', payload.method.slice(0, -2) + '08'], ['nonce', '0x00000001'],
    ['era', '0x0500'], ['genesisHash', '0x' + 'aa'.repeat(32)], ['specVersion', '0x00000001'],
    ['transactionVersion', '0x00000002'], ['tip', '0x00000000000000000000000000000001']]) {
    assert.equal(await verifyPayloadSignature(registry, { ...payload, [key]: value }, signature, sender), false, key);
  }
});
test('another account cannot authorize the stored sender', async () => {
  assert.equal(await verifyPayloadSignature(registry, payload, signature, '0x' + 'bb'.repeat(32)), false);
});
