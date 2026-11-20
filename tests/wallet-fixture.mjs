// Deterministic signing fixtures for authentication tests. Never used by the product.
import { blake2AsU8a, cryptoWaitReady, sr25519PairFromSeed, sr25519Sign } from '@polkadot/util-crypto';
import { stringToU8a, u8aToHex, u8aWrapBytes } from '@polkadot/util';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const args = JSON.parse(input);
await cryptoWaitReady();
const pair = sr25519PairFromSeed(blake2AsU8a('Tavrel test fixture only: ' + (args.label || 'operator')));
process.stdout.write(JSON.stringify({ account: u8aToHex(pair.publicKey),
  signature: args.message ? u8aToHex(sr25519Sign(u8aWrapBytes(stringToU8a(args.message)), pair)) : null }) + '\n');
