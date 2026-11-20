pragma circom 2.1.6;
include "circomlib/circuits/poseidon.circom";
include "circomlib/circuits/comparators.circom";
include "circomlib/circuits/bitify.circom";

// One public commitment, as required by zkVerify's FFLONK verifier.
// Recipient membership and remaining allowances stay private.
template PaymentPolicy() {
    signal input amount;
    signal input recipient[2];
    signal input sender[2];
    signal input review[2];
    signal input genesis[2];
    signal input cap;
    signal input taskAvailable;
    signal input accountAvailable;
    signal input siblings[3];
    signal input directions[3];
    signal output statement;

    component amountBits = Num2Bits(128);
    amountBits.in <== amount;
    component nonzero = IsZero();
    nonzero.in <== amount;
    nonzero.out === 0;
    component capBits = Num2Bits(128);
    component taskBits = Num2Bits(128);
    component accountBits = Num2Bits(128);
    capBits.in <== cap;
    taskBits.in <== taskAvailable;
    accountBits.in <== accountAvailable;
    component withinCap = LessEqThan(128);
    component withinTask = LessEqThan(128);
    component withinAccount = LessEqThan(128);
    withinCap.in[0] <== amount; withinCap.in[1] <== cap;
    withinTask.in[0] <== amount; withinTask.in[1] <== taskAvailable;
    withinAccount.in[0] <== amount; withinAccount.in[1] <== accountAvailable;
    withinCap.out === 1;
    withinTask.out === 1;
    withinAccount.out === 1;

    // Public-claim verification decodes each address/hash into two uint128
    // halves and recomputes the statement. Poseidon binds those exact halves;
    // extra private range checks on them do not strengthen the claim.
    component leaf = Poseidon(2);
    leaf.inputs[0] <== recipient[0]; leaf.inputs[1] <== recipient[1];
    signal path[4];
    path[0] <== leaf.out;
    component nodes[3];
    for (var level = 0; level < 3; level++) {
        directions[level] * (directions[level] - 1) === 0;
        nodes[level] = Poseidon(2);
        nodes[level].inputs[0] <== path[level] + directions[level] * (siblings[level] - path[level]);
        nodes[level].inputs[1] <== siblings[level] + directions[level] * (path[level] - siblings[level]);
        path[level + 1] <== nodes[level].out;
    }
    component policy = Poseidon(4);
    policy.inputs[0] <== path[3];
    policy.inputs[1] <== cap;
    policy.inputs[2] <== taskAvailable;
    policy.inputs[3] <== accountAvailable;
    component claim = Poseidon(10);
    claim.inputs[0] <== policy.out; claim.inputs[1] <== amount;
    claim.inputs[2] <== recipient[0]; claim.inputs[3] <== recipient[1];
    claim.inputs[4] <== sender[0]; claim.inputs[5] <== sender[1];
    claim.inputs[6] <== review[0]; claim.inputs[7] <== review[1];
    claim.inputs[8] <== genesis[0]; claim.inputs[9] <== genesis[1];
    statement <== claim.out;
}
component main = PaymentPolicy();
