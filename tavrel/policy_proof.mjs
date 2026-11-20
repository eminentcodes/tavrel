/** Real local FFLONK proof generation/verification. Never signs or broadcasts. */
import { readFileSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { fflonk } from 'snarkjs';
import { buildWitness, statementFor } from '../proofs/policy-input.mjs';

const input = JSON.parse(readFileSync(0, 'utf8'));
const directory = resolve('.tavrel-proofs');
const keyDirectory = input.action === 'verify' ? resolve('proofs') : directory;
const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
const referenceHash = value => hash(canonical(value));
try {
  const manifest = JSON.parse(await readFile(resolve(keyDirectory, 'manifest.json'), 'utf8'));
  const vk = JSON.parse(await readFile(resolve(keyDirectory, 'verification_key.json'), 'utf8'));
  if (referenceHash(vk) !== manifest.verification_key_sha256 || vk.nPublic !== 1 || vk.protocol !== 'fflonk') throw new Error('The verification key does not match the compiled circuit.');
  const sourceHash = createHash('sha256').update((await readFile('proofs/payment_policy.circom', 'utf8')).replace(/\r\n/g, '\n')).digest('hex');
  if (sourceHash !== manifest.circuit_sha256) throw new Error('Rebuild the proving key after changing the circuit.');
  let bundle;
  if (input.action === 'generate') {
    const { witness, claim, statement } = buildWitness(input.payment, input.snapshot, input.genesis_hash);
    const { proof, publicSignals } = await fflonk.fullProve(witness,
      resolve(directory, 'payment_policy_js/payment_policy.wasm'), resolve(directory, 'payment_policy.zkey'));
    if (publicSignals.length !== 1 || publicSignals[0] !== statement || !await fflonk.verify(vk, publicSignals, proof)) throw new Error('The generated proof did not verify.');
    const reference = referenceHash({ claim, proof, publicSignals, verification_key_sha256: manifest.verification_key_sha256 });
    bundle = { protocol: 'fflonk', claim, proof, publicSignals, verification_key: vk,
      verification_key_sha256: manifest.verification_key_sha256, circuit_sha256: sourceHash,
      reference: 'sha256:' + reference, locally_verified: true, zkverify_transaction: null,
      meaning: 'Recipient membership and exact amount within the committed cap and remaining allowances. This proves the supplied commitment; it does not certify settlement or independently authenticate the policy snapshot.' };
  } else if (input.action === 'verify') {
    bundle = input.bundle;
    const reference = referenceHash({ claim: bundle.claim, proof: bundle.proof, publicSignals: bundle.publicSignals,
      verification_key_sha256: manifest.verification_key_sha256 });
    if (bundle.verification_key_sha256 !== manifest.verification_key_sha256 || referenceHash(bundle.verification_key) !== manifest.verification_key_sha256 ||
        bundle.circuit_sha256 !== sourceHash || bundle.reference !== 'sha256:' + reference || bundle.publicSignals.length !== 1 ||
        bundle.publicSignals[0] !== statementFor(bundle.claim) || !await fflonk.verify(vk, bundle.publicSignals, bundle.proof)) throw new Error('Policy proof verification failed.');
    bundle = { valid: true, reference: bundle.reference, claim: bundle.claim, verified_by: 'Pinned local FFLONK verifier', zkverify_transaction: null };
  } else throw new Error('Unknown proof operation.');
  process.stdout.write(JSON.stringify({ ok: true, result: bundle }) + '\n');
  process.exit(0);
} catch (error) {
  process.stdout.write(JSON.stringify({ ok: false, error: error.message }) + '\n');
  process.exit(2);
}
