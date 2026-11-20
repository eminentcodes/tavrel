import { decodeAddress } from '@polkadot/util-crypto';
import { u8aToHex } from '@polkadot/util';

export async function signPayment(payload, expectedSender) {
  const { web3Enable, web3Accounts, web3FromSource } = await import('@polkadot/extension-dapp');
  await web3Enable('Tavrel');
  const accounts = await web3Accounts();
  const account = accounts.find(item => u8aToHex(decodeAddress(item.address)) === expectedSender);
  if (!account) throw new Error('Connect the wallet account named as this payment’s sender.');
  const provider = await web3FromSource(account.meta.source);
  if (!provider.signer.signPayload) throw new Error('This wallet cannot sign native transfers. Use SubWallet or Talisman with a Substrate account.');
  const result = await provider.signer.signPayload({ ...payload, address: account.address });
  return { signature: result.signature, ...(result.signedTransaction ? { signed_hex: result.signedTransaction } : {}) };
}
