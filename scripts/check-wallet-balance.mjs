/** Read native Volta balances. No signing or transaction submission. */
import { ApiPromise, HttpProvider } from '@polkadot/api';
import { decodeAddress, encodeAddress } from '@polkadot/util-crypto';
import { u8aToHex } from '@polkadot/util';
const addresses = process.argv.slice(2);
if (!addresses.length || addresses.length > 5) throw new Error('Provide one to five public Substrate addresses.');
const deadline = setTimeout(() => process.exit(2), 45000);
let api;
try {
  const keys = addresses.map(address => decodeAddress(address));
  api = await ApiPromise.create({ provider: new HttpProvider('https://volta-rpc.zkverify.io'), noInitWarn: true });
  if (api.genesisHash.toHex() !== '0xff7fe5a610f15fe7a0c52f94f86313fb7db7d3786e7f8acf2b66c11d5be7c242') throw new Error('Unexpected chain.');
  const properties = (await api.rpc.system.properties()).toJSON();
  const head = await api.rpc.chain.getFinalizedHead();
  const at = await api.at(head);
  const results = await Promise.all(keys.map(async key => {
    const state = await at.query.system.account(key);
    const free = BigInt(state.data.free.toString());
    const whole = free / 10n ** 18n;
    const fraction = (free % (10n ** 18n)).toString().padStart(18, '0').replace(/0+$/, '');
    return { address: encodeAddress(key, 251), account_id: u8aToHex(key), free_tVFY: `${whole}${fraction ? '.' + fraction : ''}`, account: state.toJSON() };
  }));
  console.log(JSON.stringify({ observed_at: new Date().toISOString(), network: 'zkVerify Volta', properties, finalized_block: head.toHex(), balances: results, read_only: true }));
} finally { clearTimeout(deadline); if (api) await api.disconnect(); }
