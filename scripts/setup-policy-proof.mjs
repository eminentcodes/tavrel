/** Compile a reproducible FFLONK key from the published multi-party SRS. */
import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { spawn } from 'node:child_process';
import { fflonk, zKey, powersOfTau } from 'snarkjs';

const directory = resolve('.tavrel-proofs');
const source = resolve('proofs/payment_policy.circom');
const ptau = resolve(process.argv.slice(2).find(arg => !arg.startsWith('--')) || '.cache/ppot_0080_16.ptau');
const verifyCeremony = process.argv.includes('--verify-ceremony');
const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
const hash = createHash('blake2b512');
for await (const bytes of createReadStream(ptau)) hash.update(bytes);
const expected = hash.digest('hex');
const sourceHash = createHash('sha256').update(await readFile(ptau)).digest('hex');
if (sourceHash !== 'ed3622a7c79b0b49aadd134ebbc5b77df8c8c59bccebdfd0d9bf2c1a51561cf9') throw new Error('The SRS does not match the pinned official PSE ceremony file.');
console.log('Pinned official PSE SRS checksum verified.');
if (verifyCeremony) {
  console.log('Rechecking the full ceremony, including the expensive beacon computation. This can take hours.');
  if (!await powersOfTau.verify(ptau, { info: console.log, debug() {}, warn: console.warn, error: console.error })) throw new Error('The SRS ceremony verification failed.');
}
await mkdir(directory, { recursive: true });
await new Promise((resolveDone, reject) => {
  const child = spawn(process.execPath, [resolve('scripts/compile-policy-proof.mjs')], { windowsHide: true, stdio: 'inherit' });
  child.on('error', reject); child.on('exit', code => code === 0 ? resolveDone() : reject(new Error('Circuit compilation failed.')));
});
console.log('Deriving the circuit key from the pinned published ceremony.');
await fflonk.setup(resolve(directory, 'payment_policy.r1cs'), ptau, resolve(directory, 'payment_policy.zkey'));
const key = await zKey.exportVerificationKey(resolve(directory, 'payment_policy.zkey'));
await writeFile(resolve(directory, 'verification_key.json'), JSON.stringify(key, null, 2) + '\n');
await writeFile(resolve(directory, 'manifest.json'), JSON.stringify({ protocol: 'fflonk',
  circuit_sha256: createHash('sha256').update((await readFile(source, 'utf8')).replace(/\r\n/g, '\n')).digest('hex'),
  srs_blake2b512: expected, srs_sha256: sourceHash, srs_source: 'https://pse-trusted-setup-ppot.s3.eu-central-1.amazonaws.com/pot28_0080/ppot_0080_16.ptau',
  ceremony_reverified: verifyCeremony,
  verification_key_sha256: createHash('sha256').update(JSON.stringify(canonical(key))).digest('hex'),
  n_public: key.nPublic }, null, 2) + '\n');
console.log('Policy proof artifacts are ready in .tavrel-proofs.');
process.exit(0);
