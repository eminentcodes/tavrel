/** Generate and independently verify a real local FFLONK artifact. No chain calls. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { writeFile } from 'node:fs/promises';
import { statementFor } from '../proofs/policy-input.mjs';

const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
const reference = bundle => 'sha256:' + createHash('sha256').update(JSON.stringify(canonical({ claim: bundle.claim,
  proof: bundle.proof, publicSignals: bundle.publicSignals, verification_key_sha256: bundle.verification_key_sha256 }))).digest('hex');
async function call(input) {
  const child = spawn(process.execPath, ['tavrel/policy_proof.mjs'], { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
  let output = ''; let errors = '';
  child.stdout.on('data', chunk => { output += chunk; });
  child.stderr.on('data', chunk => { errors += chunk; });
  child.stdin.end(JSON.stringify(input));
  const timer = setTimeout(() => child.kill(), 240000);
  const code = await new Promise((resolve, reject) => { child.on('exit', resolve); child.on('error', reject); });
  clearTimeout(timer);
  if (!output) throw new Error(`Proof process returned no result (${code}): ${errors}`);
  return JSON.parse(output);
}
const payment = { recipient: '0x' + '12'.repeat(32), sender: '0x' + '34'.repeat(32),
  amount_units: '20000000000000000', approval_hash: '0x' + '56'.repeat(32) };
const snapshot = { recipients: [payment.recipient], cap_units: '30000000000000000',
  task_available_units: '100000000000000000', account_available_units: '100000000000000000' };
const genesis_hash = '0xff7fe5a610f15fe7a0c52f94f86313fb7db7d3786e7f8acf2b66c11d5be7c242';
console.log('Generating a real proof from isolated test instructions.');
const generated = await call({ action: 'generate', payment, snapshot, genesis_hash });
assert.equal(generated.ok, true, generated.error);
const bundle = generated.result;
const checks = [];
async function verify(name, value, expected) {
  const result = await call({ action: 'verify', bundle: value });
  assert.equal(result.ok, expected, name + ': ' + result.error);
  checks.push({ name, passed: true });
}
await verify('valid generated artifact', bundle, true);
await verify('SQLite/download object-key ordering', canonical(bundle), true);
for (const key of ['amount_units', 'recipient', 'sender', 'approval_hash', 'genesis_hash']) {
  const changed = structuredClone(bundle);
  changed.claim[key] = key === 'amount_units' ? '21000000000000000' : '0x' + 'ab'.repeat(32);
  changed.publicSignals = [statementFor(changed.claim)];
  changed.reference = reference(changed);
  await verify(`altered ${key}, with recalculated commitment and reference`, changed, false);
}
const alteredProof = structuredClone(bundle);
alteredProof.proof.polynomials.C1[0] = '1';
alteredProof.reference = reference(alteredProof);
await verify('altered proof, with recalculated reference', alteredProof, false);
for (const key of ['cap_units', 'task_available_units', 'account_available_units']) {
  const result = await call({ action: 'generate', payment, snapshot: { ...snapshot, [key]: '1' }, genesis_hash });
  assert.equal(result.ok, false, 'overflow: ' + key);
  checks.push({ name: 'overflow: ' + key, passed: true });
}
const unknown = await call({ action: 'generate', payment: { ...payment, recipient: '0x' + 'ab'.repeat(32) }, snapshot, genesis_hash });
assert.equal(unknown.ok, false);
checks.push({ name: 'recipient outside approved tree', passed: true });
await writeFile('artifacts/payment-policy-proof.json', JSON.stringify(canonical(bundle), null, 2) + '\n');
await writeFile('artifacts/policy-proof-check.json', JSON.stringify({ observed_at: new Date().toISOString(),
  scope: 'Real local FFLONK proof with isolated test payment instructions; no transaction or settlement', checks,
  reference: bundle.reference, protocol: bundle.protocol, n_public: bundle.publicSignals.length,
  source: 'artifacts/payment-policy-proof.json', zkverify_transaction: null, funds_spent: 0 }, null, 2) + '\n');
console.log(`${checks.length} actual FFLONK generation/verification checks passed. ${bundle.reference}`);
