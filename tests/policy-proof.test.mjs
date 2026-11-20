/** Real circuit constraint checks; no wallet signing or network submission. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { buildWitness, statementFor } from '../proofs/policy-input.mjs';

const require = createRequire(import.meta.url);
const calculator = await require('../.tavrel-proofs/payment_policy_js/witness_calculator.js')(
  await readFile('.tavrel-proofs/payment_policy_js/payment_policy.wasm'));
const payment = { amount_units: '2', recipient: '0x' + '12'.repeat(32), sender: '0x' + '34'.repeat(32), approval_hash: '0x' + '56'.repeat(32) };
const snapshot = { recipients: [payment.recipient, '0x' + '78'.repeat(32)], cap_units: '7', task_available_units: '10', account_available_units: '20' };
const genesis = '0xff7fe5a610f15fe7a0c52f94f86313fb7db7d3786e7f8acf2b66c11d5be7c242';

test('valid committed policy satisfies actual circuit and public commitment', async () => {
  const { witness, claim, statement } = buildWitness(payment, snapshot, genesis);
  const values = await calculator.calculateWitness(witness, true);
  assert.equal(values[1].toString(), statement);
  assert.equal(statement, statementFor(JSON.parse(JSON.stringify(claim))));
});
test('unknown recipient is rejected before proving', () => {
  assert.throws(() => buildWitness({ ...payment, recipient: '0x' + 'ab'.repeat(32) }, snapshot, genesis));
});
test('production SHA-256 review hashes use the same exact bytes as prefixed hashes', async () => {
  const encoded = buildWitness({ ...payment, approval_hash: payment.approval_hash.slice(2) }, snapshot, genesis);
  assert.equal(encoded.claim.approval_hash, payment.approval_hash);
  assert.equal(encoded.statement, buildWitness(payment, snapshot, genesis).statement);
  const values = await calculator.calculateWitness(encoded.witness, true);
  assert.equal(values[1].toString(), encoded.statement);
});
test('cap and each remaining allowance reject overflow in the actual circuit', async () => {
  for (const field of ['cap_units', 'task_available_units', 'account_available_units']) {
    const { witness } = buildWitness(payment, { ...snapshot, [field]: '1' }, genesis);
    await assert.rejects(calculator.calculateWitness(witness, true));
  }
});
test('zero amount and a changed recipient cannot satisfy the original witness', async () => {
  const { witness } = buildWitness(payment, snapshot, genesis);
  await assert.rejects(calculator.calculateWitness({ ...witness, amount: '0' }, true));
  const changed = { ...witness, recipient: ['1', '2'] };
  const values = await calculator.calculateWitness(changed, true);
  assert.notEqual(values[1].toString(), statementFor(buildWitness(payment, snapshot, genesis).claim));
});
test('noncanonical public amounts and field-wrap aliases are rejected', () => {
  const { claim } = buildWitness(payment, snapshot, genesis);
  for (const value of ['0', '02', '-2', String(2n ** 128n), '21888242871839275222246405745257275088548364400416034343698204186575808495619']) {
    assert.throws(() => statementFor({ ...claim, amount_units: value }));
  }
  for (const value of ['00', '-1', '21888242871839275222246405745257275088548364400416034343698204186575808495617']) {
    assert.throws(() => statementFor({ ...claim, policy_commitment: value }));
  }
  for (const key of ['cap_units', 'task_available_units', 'account_available_units']) {
    assert.throws(() => buildWitness(payment, { ...snapshot, [key]: String(2n ** 128n) }, genesis));
  }
});
test('sender, recipient, amount, review and chain bind distinct public statements', () => {
  const { claim, statement } = buildWitness(payment, snapshot, genesis);
  for (const key of ['sender', 'recipient', 'approval_hash', 'genesis_hash']) {
    assert.notEqual(statementFor({ ...claim, [key]: '0x' + 'ab'.repeat(32) }), statement);
  }
  assert.notEqual(statementFor({ ...claim, amount_units: '3' }), statement);
});
