/** Native Substrate signature verification. Reads only public authentication data. */
import { cryptoWaitReady, signatureVerify } from '@polkadot/util-crypto';
import { stringToU8a } from '@polkadot/util';
import { createInterface } from 'node:readline';

await cryptoWaitReady();
function verify(input) {
  try {
    const { message, signature, account } = input;
    const result = signatureVerify(stringToU8a(message), signature, account);
    return { valid: result.isValid, crypto: result.crypto };
  } catch { return { valid: false }; }
}
if (process.argv.includes('--serve')) {
  process.stdout.write(JSON.stringify({ ready: true }) + '\n');
  for await (const line of createInterface({ input: process.stdin, crlfDelay: Infinity })) {
    if (line.length > 8192) process.exit(2);
    try {
      const input = JSON.parse(line);
      process.stdout.write(JSON.stringify({ id: input.id, ...verify(input) }) + '\n');
    } catch { process.stdout.write(JSON.stringify({ valid: false }) + '\n'); }
  }
} else {
  let input = '';
  for await (const chunk of process.stdin) {
    input += chunk;
    if (input.length > 8192) process.exit(2);
  }
  try { process.stdout.write(JSON.stringify(verify(JSON.parse(input))) + '\n'); }
  catch { process.stdout.write(JSON.stringify({ valid: false }) + '\n'); }
}
