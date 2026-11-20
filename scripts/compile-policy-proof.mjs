/** Use portable WASI paths; the circom2 CLI uses Windows path separators. */
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
const require = createRequire(import.meta.url);
const { CircomRunner, bindings } = require('circom2');
const directory = path.resolve('.tavrel-proofs');
fs.mkdirSync(directory, { recursive: true });
const circom = new CircomRunner({
  args: ['proofs/payment_policy.circom', '--r1cs', '--wasm', '--sym', '--O1', '-l', 'node_modules', '-o', '.tavrel-proofs'],
  env: {}, preopens: { '.': process.cwd() },
  bindings: { ...bindings, path, fs },
});
await circom.execute(fs.readFileSync(require.resolve('circom2/circom.wasm')));
// Circom emits CommonJS helpers inside this ESM repository.
fs.writeFileSync(path.join(directory, 'payment_policy_js/package.json'), '{"type":"commonjs"}\n');
