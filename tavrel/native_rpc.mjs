/** Native Volta RPC operations. Signing keys always remain in the browser wallet. */
import { ApiPromise, HttpProvider } from '@polkadot/api';
import { decodeAddress, encodeAddress, signatureVerify, blake2AsU8a, cryptoWaitReady } from '@polkadot/util-crypto';
import { u8aToHex, hexToU8a } from '@polkadot/util';
import { readFileSync } from 'node:fs';
import { verifyPayloadSignature } from './native_signing.mjs';

const input = readFileSync(0, 'utf8');
if (input.length > 100000) throw new Error('Request too large.');
const args = JSON.parse(input);
const deadline = setTimeout(() => { process.stderr.write('Network check timed out.\n'); process.exit(2); }, 40000);
let api;
const account = value => u8aToHex(decodeAddress(value.toString()));
const diagnostic = stage => { if (process.env.TAVREL_RPC_DIAGNOSTIC === '1') process.stderr.write(stage + '\n'); };
function transfer(tx, expected) {
  if (tx.method.section !== 'balances' || tx.method.method !== 'transferKeepAlive' || tx.method.args.length !== 2 ||
      account(tx.method.args[0]) !== expected.recipient || tx.method.args[1].toString() !== expected.amount_units ||
      (tx.isSigned && account(tx.signer) !== expected.sender)) throw new Error('Signed transaction does not match this payment.');
}
try {
  diagnostic('RPC request parsed');
  api = await ApiPromise.create({ provider: new HttpProvider('https://volta-rpc.zkverify.io'), noInitWarn: true });
  diagnostic('API connected');
  if (api.genesisHash.toHex() !== args.genesis_hash) throw new Error('The connected chain is not the approved Volta network.');
  const properties = JSON.parse(JSON.stringify((await api.rpc.system.properties()).toJSON()));
  const symbol = Array.isArray(properties.tokenSymbol) ? properties.tokenSymbol[0] : properties.tokenSymbol;
  const decimals = Array.isArray(properties.tokenDecimals) ? properties.tokenDecimals[0] : properties.tokenDecimals;
  if (symbol !== 'tVFY' || Number(decimals) !== 18) throw new Error('Unexpected native token: ' + JSON.stringify(properties));
  diagnostic('Network and token checked');
  const head = await api.rpc.chain.getFinalizedHead();
  const height = (await api.rpc.chain.getHeader(head)).number.toNumber();
  diagnostic('Finalized head checked');
  let result;
  if (args.action === 'quote') {
    const tx = api.tx.balances.transferKeepAlive(args.payment.recipient, args.payment.amount_units);
    const [info, state, nonce] = await Promise.all([tx.paymentInfo(args.payment.sender),
      api.query.system.account(args.payment.sender), api.rpc.system.accountNextIndex(args.payment.sender)]);
    diagnostic('Fee, balance, nonce checked');
    const fee = BigInt(info.partialFee.toString());
    const free = BigInt(state.data.free.toString());
    const frozen = BigInt((state.data.frozen ?? state.data.miscFrozen ?? 0).toString());
    const minimum = BigInt(api.consts.balances.existentialDeposit.toString());
    const protectedAmount = frozen > minimum ? frozen : minimum;
    const available = free > protectedAmount ? free - protectedAmount : 0n;
    const era = api.createType('ExtrinsicEra', { current: height, period: 64 });
    const payload = api.createType('SignerPayload', {
      address: encodeAddress(args.payment.sender, 251), blockHash: head.toHex(), blockNumber: height,
      era, genesisHash: api.genesisHash, method: tx.method,
      nonce, runtimeVersion: api.runtimeVersion, signedExtensions: api.registry.signedExtensions,
      tip: 0, version: tx.version,
    }).toPayload();
    result = { fee_units: String(fee), free_units: String(free), transferable_units: String(available),
      enough_funds: available >= BigInt(args.payment.amount_units) + fee, nonce: nonce.toString(),
      finalized_height: height, expires_height: era.asMortalEra.death(height),
      genesis_hash: api.genesisHash.toHex(), call_hex: tx.method.toHex(), payload };
  } else if (args.action === 'inspect' || args.action === 'submit') {
    let tx;
    if (args.action === 'inspect') {
      await cryptoWaitReady();
      const quote = args.quote;
      if (quote.genesis_hash !== api.genesisHash.toHex() || height >= quote.expires_height ||
          quote.payload.specVersion !== api.runtimeVersion.specVersion.toHex() ||
          quote.payload.transactionVersion !== api.runtimeVersion.transactionVersion.toHex()) throw new Error('Signing review expired or the runtime changed. Get a fresh fee review.');
      if ((await api.rpc.chain.getBlockHash(quote.finalized_height)).toHex() !== quote.payload.blockHash) throw new Error('Signing checkpoint does not match finalized chain history.');
      if (!await verifyPayloadSignature(api.registry, quote.payload, args.signature, args.payment.sender)) throw new Error('The signature does not authorize the reviewed payment payload.');
      tx = api.tx.balances.transferKeepAlive(args.payment.recipient, args.payment.amount_units);
      if (tx.method.toHex() !== quote.payload.method) throw new Error('Payment call changed since fee review.');
      tx.addSignature(quote.payload.address, args.signature, quote.payload);
      if (args.signed_hex && api.createType('Extrinsic', args.signed_hex).toHex() !== tx.toHex()) throw new Error('Wallet changed the reviewed transaction.');
    } else tx = api.createType('Extrinsic', args.signed_hex);
    if (!tx.isSigned) throw new Error('A wallet-signed transaction is required.');
    transfer(tx, args.payment);
    result = { tx_hash: tx.hash.toHex(), signed_hex: tx.toHex(), nonce: tx.nonce.toString(), finalized_height: height };
    if (args.action === 'submit') {
      try {
        const hash = await api.rpc.author.submitExtrinsic(tx);
        if (hash.toHex() !== result.tx_hash) throw new Error('Submission returned an unexpected transaction hash.');
        result.submitted = true;
      } catch (error) {
        // Pool ambiguity never releases a hold or manufactures settlement.
        result.submitted = false;
        result.error = error.message;
      }
    }
  } else if (args.action === 'scan') {
    result = { payments: [] };
    const blocks = new Map();
    for (const payment of args.payments) {
      const start = Math.max(0, payment.scan_height);
      const end = Math.min(height, start + 15, payment.expires_height);
      let receipt = null;
      for (let number = start; number <= end; number++) {
        if (!blocks.has(number)) {
          const hash = await api.rpc.chain.getBlockHash(number);
          const block = await api.rpc.chain.getBlock(hash);
          blocks.set(number, { hash, block });
        }
        const { hash, block } = blocks.get(number);
        const index = block.block.extrinsics.findIndex(tx => tx.hash.toHex() === payment.tx_hash);
        if (index < 0) continue;
        const tx = block.block.extrinsics[index];
        if (!tx.isSigned) throw new Error('Finalized transfer has no wallet signature.');
        transfer(tx, payment);
        const at = await api.at(hash);
        const events = (await at.query.system.events()).filter(row => row.phase.isApplyExtrinsic && row.phase.asApplyExtrinsic.toNumber() === index);
        const success = events.some(row => row.event.section === 'system' && row.event.method === 'ExtrinsicSuccess');
        const movement = events.find(row => row.event.section === 'balances' && row.event.method === 'Transfer' &&
          account(row.event.data[0]) === payment.sender && account(row.event.data[1]) === payment.recipient &&
          row.event.data[2].toString() === payment.amount_units);
        const fee = events.find(row => row.event.section === 'transactionPayment' && row.event.method === 'TransactionFeePaid');
        const failure = events.find(row => row.event.section === 'system' && row.event.method === 'ExtrinsicFailed');
        receipt = { tx_hash: payment.tx_hash, block_hash: hash.toHex(), block_number: number, extrinsic_index: index,
          genesis_hash: api.genesisHash.toHex(), finality_verified: true, success: success && !!movement,
          sender: payment.sender, recipient: payment.recipient, amount_units: payment.amount_units,
          fee_units: fee ? fee.event.data[1].toString() : null,
          error: success && movement ? null : failure ? failure.event.data[0].toString() : 'Matching successful transfer event was not found.' };
        break;
      }
      result.payments.push({ payment_id: payment.payment_id, tx_hash: payment.tx_hash,
        scan_height: end >= start ? end + 1 : start, receipt,
        expired: !receipt && height >= payment.expires_height && end >= payment.expires_height,
        finalized_height: height, genesis_hash: api.genesisHash.toHex() });
    }
  } else throw new Error('Unknown network operation.');
  process.stdout.write(JSON.stringify({ ok: true, result }) + '\n');
} catch (error) {
  process.stdout.write(JSON.stringify({ ok: false, error: error.message }) + '\n');
  process.exitCode = 2;
} finally { clearTimeout(deadline); if (api) await api.disconnect(); }
