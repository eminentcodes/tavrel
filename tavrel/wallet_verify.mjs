/** Native Substrate signature verification. Reads only public authentication data. */
import { cryptoWaitReady, signatureVerify } from '@polkadot/util-crypto';
import { stringToU8a } from '@polkadot/util';

let input = '';
for await (const chunk of process.stdin) {
  input += chunk;
  if (input.length > 8192) process.exit(2);
}
try {
  const { message, signature, account } = JSON.parse(input);
  await cryptoWaitReady();
  const result = signatureVerify(stringToU8a(message), signature, account);
  process.stdout.write(JSON.stringify({ valid: result.isValid, crypto: result.crypto }) + '\n');
} catch {
  process.stdout.write(JSON.stringify({ valid: false }) + '\n');
}
