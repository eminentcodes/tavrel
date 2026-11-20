import { poseidon2, poseidon4, poseidon10 } from 'poseidon-lite';

export function halves(value) {
  if (typeof value !== 'string' || !/^0x[0-9a-fA-F]{64}$/.test(value)) throw new Error('Use canonical 32-byte public account/hash values.');
  return [BigInt('0x' + value.slice(2, 34)), BigInt('0x' + value.slice(34))];
}
export function statementFor(claim) {
  if (typeof claim.amount_units !== 'string' || !/^[1-9][0-9]*$/.test(claim.amount_units) || BigInt(claim.amount_units) >= 2n ** 128n) throw new Error('The public amount must be a positive canonical uint128.');
  if (typeof claim.policy_commitment !== 'string' || !/^(0|[1-9][0-9]*)$/.test(claim.policy_commitment) || BigInt(claim.policy_commitment) >= 21888242871839275222246405745257275088548364400416034343698204186575808495617n) throw new Error('The policy commitment must be a canonical field element.');
  return poseidon10([BigInt(claim.policy_commitment), BigInt(claim.amount_units),
    ...halves(claim.recipient), ...halves(claim.sender), ...halves(claim.approval_hash), ...halves(claim.genesis_hash)]).toString();
}
export function buildWitness(payment, snapshot, genesisHash) {
  const reviewHash = typeof payment.approval_hash === 'string' && /^[0-9a-fA-F]{64}$/.test(payment.approval_hash)
    ? '0x' + payment.approval_hash : payment.approval_hash;
  for (const key of ['cap_units', 'task_available_units', 'account_available_units']) {
    const value = snapshot[key];
    if (typeof value !== 'string' || !/^(0|[1-9][0-9]*)$/.test(value) || BigInt(value) >= 2n ** 128n) throw new Error('Policy amounts must be canonical uint128 values.');
  }
  const recipients = [...new Set(snapshot.recipients)].sort();
  if (recipients.length > 8) throw new Error('Policy proofs support at most eight approved recipients.');
  let index = recipients.indexOf(payment.recipient);
  if (index < 0) throw new Error('Recipient is outside the committed permissions.');
  let leaves = Array.from({ length: 8 }, (_, i) => poseidon2(i < recipients.length ? halves(recipients[i]) : [0n, 0n]));
  const siblings = []; const directions = [];
  for (let level = 0; level < 3; level++) {
    siblings.push(leaves[index ^ 1].toString()); directions.push(String(index % 2));
    leaves = Array.from({ length: leaves.length / 2 }, (_, i) => poseidon2([leaves[i * 2], leaves[i * 2 + 1]]));
    index = Math.floor(index / 2);
  }
  const policyCommitment = poseidon4([leaves[0], BigInt(snapshot.cap_units), BigInt(snapshot.task_available_units), BigInt(snapshot.account_available_units)]).toString();
  const claim = { policy_commitment: policyCommitment, amount_units: payment.amount_units,
    recipient: payment.recipient, sender: payment.sender, approval_hash: reviewHash, genesis_hash: genesisHash };
  const witness = { amount: payment.amount_units, recipient: halves(payment.recipient).map(String),
    sender: halves(payment.sender).map(String), review: halves(reviewHash).map(String),
    genesis: halves(genesisHash).map(String), cap: snapshot.cap_units,
    taskAvailable: snapshot.task_available_units, accountAvailable: snapshot.account_available_units,
    siblings, directions };
  return { claim, witness, statement: statementFor(claim) };
}
