/** Read-only sponsor integration. No account, signing key, or transaction submission. */
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import { zkVerifySession } from 'zkverifyjs';
import { decodeAddress } from '@polkadot/util-crypto';
import { u8aToHex } from '@polkadot/util';

const outputPath = process.argv[2] || 'artifacts/zkverify-network-proof.json';
const recipient = '0xd43593c715fdd31c61141abd04a99fd6822c8558854ccde39a5684e7a56da27d';
const hardDeadline = setTimeout(() => {
  process.stderr.write('zkVerify read-only check exceeded its 45-second deadline.\n');
  process.exit(1);
}, 45_000);
let session;
try {
  session = await zkVerifySession.start().Volta().readOnly();
  const api = session.api;
  const [chainName, properties, genesis, finalized, runtimeVersion] = await Promise.all([
    api.rpc.system.chain(), api.rpc.system.properties(), api.rpc.chain.getBlockHash(0),
    api.rpc.chain.getFinalizedHead(), api.rpc.state.getRuntimeVersion(),
  ]);
  const native = JSON.parse(JSON.stringify(properties.toJSON()));
  if (native.tokenDecimals?.[0] !== 18 || native.tokenSymbol?.[0] !== 'tVFY') {
    throw new Error(`Connected chain properties do not match native Volta tVFY: ${JSON.stringify(native)}`);
  }
  if (typeof api.tx.balances?.transferKeepAlive !== 'function') {
    throw new Error('The connected runtime lacks balances.transferKeepAlive.');
  }
  const unsigned = api.tx.balances.transferKeepAlive(recipient, '1');
  const callHex = unsigned.method.toHex();
  const decoded = api.createType('Call', callHex);
  const decodedRecipient = u8aToHex(decodeAddress(decoded.args[0].toString()));
  if (decoded.section !== 'balances' || decoded.method !== 'transferKeepAlive' ||
      decoded.args[1].toString() !== '1' || decodedRecipient !== recipient ||
      decoded.toHex() !== callHex) {
    throw new Error('Unsigned native transfer did not round-trip against live runtime metadata: ' + JSON.stringify({
      section: decoded.section, method: decoded.method, amount: decoded.args[1].toString(),
      recipient: decodedRecipient, expected_recipient: recipient, call_hex_matches: decoded.toHex() === callHex,
      recipient_json: decoded.args[0].toJSON(), recipient_string: decoded.args[0].toString(),
      recipient_type: decoded.args[0].toRawType(),
    }));
  }
  const proof = {
    network: 'zkverify-volta', chain: chainName.toString(), sdk: 'zkverifyjs@3.4.0',
    observed_at: new Date().toISOString(), properties: native,
    genesis_hash: genesis.toHex(), finalized_head: finalized.toHex(),
    runtime: { spec_name: runtimeVersion.specName.toString(), spec_version: runtimeVersion.specVersion.toNumber() },
    unsigned_call: { pallet: 'balances', method: 'transferKeepAlive',
      recipient_account_id: recipient, amount_units: '1', call_hex: callHex,
      round_trip_verified: true },
    signing_performed: false, broadcast_performed: false, settlement_verified: false,
    zk_proof_submitted: false,
    note: 'Read-only live RPC and unsigned SCALE call construction. This is connectivity/metadata evidence, not payment or policy-proof evidence.',
  };
  await mkdir(dirname(outputPath), { recursive: true });
  await writeFile(outputPath, JSON.stringify(proof, null, 2) + '\n');
  process.stdout.write(JSON.stringify({ network: proof.network, chain: proof.chain,
    symbol: native.tokenSymbol, decimals: native.tokenDecimals,
    unsigned_native_transfer_verified: true, signing: false, broadcast: false,
    output: outputPath }, null, 2) + '\n');
} catch (error) {
  process.stderr.write(`zkVerify read-only verification failed: ${error.message}\n`);
  process.exitCode = 1;
} finally {
  clearTimeout(hardDeadline);
  if (session) await session.close();
}
