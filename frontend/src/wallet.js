const providers = new Map();
const sourceKey = 'tavrel-wallet-source';
let codecPromise;

export function warmWallet() {
  if (!codecPromise) codecPromise = Promise.all([
    import('@polkadot/util-crypto/address/decode'), import('@polkadot/util/u8a/toHex'),
  ]).then(([{ decodeAddress }, { u8aToHex }]) => ({ decodeAddress, u8aToHex }));
  return codecPromise;
}

export function installedWallets() {
  return Object.entries(window.injectedWeb3 || {})
    .filter(([, wallet]) => typeof wallet.enable === 'function' || typeof wallet.connect === 'function')
    .map(([source]) => ({ source, name: /subwallet/i.test(source) ? 'SubWallet'
      : /talisman/i.test(source) ? 'Talisman' : /polkadot/i.test(source) ? 'Polkadot extension' : source }));
}

export function rememberWallet(source) {
  try { source ? sessionStorage.setItem(sourceKey, source) : sessionStorage.removeItem(sourceKey); } catch { /* Storage may be disabled. */ }
}

export async function walletProvider(source) {
  if (!providers.has(source)) {
    const injected = window.injectedWeb3?.[source];
    if (!injected) throw new Error('This wallet is unavailable. Unlock it and connect again.');
    const pending = Promise.resolve().then(() => injected.connect ? injected.connect('Tavrel') : injected.enable('Tavrel'));
    providers.set(source, pending);
    pending.catch(() => { if (providers.get(source) === pending) providers.delete(source); });
  }
  return providers.get(source);
}

export async function walletAccounts(source) {
  const [provider, { decodeAddress }] = await Promise.all([walletProvider(source), warmWallet()]);
  const accounts = await provider.accounts.get();
  return accounts.flatMap(account => {
    try {
      // Ethereum accounts do not represent native zkVerify AccountId32 wallets.
      if (account.type === 'ethereum' || decodeAddress(account.address).length !== 32) return [];
      return [{ ...account, meta: { name: account.name, source } }];
    } catch { return []; }
  });
}

export async function signPayment(payload, expectedSender) {
  let source;
  try { source = sessionStorage.getItem(sourceKey); } catch { /* Storage may be disabled. */ }
  if (!source && providers.size === 1) source = providers.keys().next().value;
  if (!source) throw new Error('Connect your wallet again before signing this payment.');
  const { decodeAddress, u8aToHex } = await warmWallet();
  const accounts = await walletAccounts(source);
  const account = accounts.find(item => u8aToHex(decodeAddress(item.address)) === expectedSender);
  if (!account) throw new Error('Connect the wallet account named as this payment’s sender.');
  const provider = await walletProvider(account.meta.source);
  if (!provider.signer.signPayload) throw new Error('This wallet cannot sign native transfers. Use SubWallet or Talisman with a Substrate account.');
  const result = await provider.signer.signPayload({ ...payload, address: account.address });
  return { signature: result.signature, ...(result.signedTransaction ? { signed_hex: result.signedTransaction } : {}) };
}
