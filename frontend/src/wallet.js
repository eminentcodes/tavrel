const providers = new Map();
const sourceKey = 'tavrel-wallet-source';
let codecPromise;

export function walletRequest(work, { signal, timeoutMs = 45_000, message = 'Your wallet did not respond. Open its extension, unlock it, and check pending requests before trying again.' } = {}) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(signal.reason); return; }
    let finished = false;
    const finish = (callback, value) => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      signal?.removeEventListener('abort', cancel);
      callback(value);
    };
    const cancel = () => finish(reject, signal.reason);
    const timer = setTimeout(() => finish(reject, new Error(message)), timeoutMs);
    signal?.addEventListener('abort', cancel, { once: true });
    // Invoke on the user's click, without waiting for codecs or another wallet.
    try { Promise.resolve(work()).then(value => finish(resolve, value), error => finish(reject, error)); }
    catch (error) { finish(reject, error); }
  });
}

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

export function forgetWallet(source) { providers.delete(source); }

export async function walletProvider(source, options = {}) {
  options.signal?.throwIfAborted();
  if (!providers.has(source)) {
    const injected = window.injectedWeb3?.[source];
    if (!injected) throw new Error('This wallet is unavailable. Unlock it and connect again.');
    const pending = walletRequest(() => {
      // SubWallet's native interface uses enable with Substrate account access.
      // Other wallets may expose the newer connect interface (and a rejecting enable shim).
      if (/subwallet/i.test(source) && typeof injected.enable === 'function') {
        return injected.enable('Tavrel', { accountAuthType: 'substrate' });
      }
      return typeof injected.connect === 'function' ? injected.connect('Tavrel') : injected.enable('Tavrel');
    }, options).then(provider => {
      if (typeof provider?.accounts?.get !== 'function') throw new Error('The wallet did not provide native account access. Unlock it and reconnect.');
      return provider;
    });
    providers.set(source, pending);
    pending.catch(() => { if (providers.get(source) === pending) providers.delete(source); });
  }
  const pending = providers.get(source);
  try { return await walletRequest(() => pending, options); }
  catch (error) { if (providers.get(source) === pending) providers.delete(source); throw error; }
}

export async function walletAccounts(source, options = {}) {
  const pending = walletProvider(source, options);
  const cached = providers.get(source);
  try {
    const provider = await pending;
    const accounts = await walletRequest(() => provider.accounts.get(), options);
    if (!Array.isArray(accounts)) throw new Error('The wallet could not list its accounts. Unlock it and reconnect.');
    return accounts.flatMap(account => {
      // Accounts come from the selected extension. The server checks the actual
      // SS58 checksum before issuing a sign-in challenge. Load full codecs only
      // when matching the sender of a transfer, keeping login free of crypto downloads.
      if (!account || account.type === 'ethereum' || typeof account.address !== 'string'
          || !(/^(?:0x[0-9a-fA-F]{64}|[1-9A-HJ-NP-Za-km-z]{35,50})$/.test(account.address))) return [];
      return [{ ...account, meta: { name: account.name, source } }];
    });
  } catch (error) {
    if (providers.get(source) === cached) providers.delete(source);
    throw error;
  }
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
