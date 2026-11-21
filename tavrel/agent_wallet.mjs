/** Offline generated-wallet derivation and signing. No network calls. */
import { readFileSync } from 'node:fs';
import { cryptoWaitReady, sr25519PairFromSeed, sr25519Sign, encodeAddress, blake2AsU8a } from '@polkadot/util-crypto';
import { TypeRegistry } from '@polkadot/types';
import { hexToU8a, u8aToHex, u8aConcat } from '@polkadot/util';
try {
  const raw = readFileSync(0, 'utf8');
  if (raw.length > 32768) throw new Error('Oversized signing request.');
  const input = JSON.parse(raw);
  if (!/^0x[0-9a-f]{64}$/.test(input.seed)) throw new Error('Invalid generated seed.');
  await cryptoWaitReady();
  const pair = sr25519PairFromSeed(hexToU8a(input.seed));
  const address = u8aToHex(pair.publicKey);
  let result = { address, wallet_address: encodeAddress(pair.publicKey, 251) };
  if (input.action === 'sign') {
    if (input.sender !== address || input.payload.genesisHash !== '0xff7fe5a610f15fe7a0c52f94f86313fb7db7d3786e7f8acf2b66c11d5be7c242') throw new Error('Signing account or network changed.');
    const registry = new TypeRegistry();
    registry.setSignedExtensions(input.payload.signedExtensions);
    const encoded = registry.createType('ExtrinsicPayload', input.payload, { version: input.payload.version }).toU8a({ method: true });
    const signature = sr25519Sign(encoded.length > 256 ? blake2AsU8a(encoded) : encoded, pair);
    result = { ...result, signature: u8aToHex(u8aConcat(new Uint8Array([1]), signature)) };
  } else if (input.action !== 'public') throw new Error('Unsupported operation.');
  process.stdout.write(JSON.stringify({ ok: true, result }));
} catch {
  // Never echo input, seed, payload, or dependency exceptions.
  process.stdout.write(JSON.stringify({ ok: false, error: 'The generated agent wallet could not complete this operation.' }));
  process.exitCode = 1;
}
