import { request } from './api.js';
import { walletProvider, walletRequest, forgetWallet } from './wallet.js';

export async function authenticateWallet(account, { signal, ticket, onProgress = () => {}, timeoutMs = 90_000 } = {}) {
  signal?.throwIfAborted();
  onProgress('Preparing sign-in');
  const provider = await walletProvider(account.meta.source, { signal });
  if (typeof provider.signer?.signRaw !== 'function') throw new Error('This wallet does not support signed-message login. Choose a compatible Substrate wallet.');
  const challenge = await request('/v1/auth/challenge', 'POST', { address: account.address, ...(ticket ? { ticket } : {}) }, { signal });
  const bytes = new TextEncoder().encode(challenge.message);
  const data = '0x' + Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
  signal?.throwIfAborted();
  onProgress('Confirm in your wallet');
  let result;
  try {
    result = await walletRequest(() => provider.signer.signRaw({ address: account.address, data, type: 'bytes' }), {
      signal, timeoutMs,
      message: 'The sign-in request timed out. Open your wallet extension and close its pending request, then try again.',
    });
  } catch (error) { forgetWallet(account.meta.source); throw error; }
  signal?.throwIfAborted();
  if (!result?.signature) throw new Error('The wallet did not return a signature. Check its pending request and try again.');
  onProgress('Verifying signature');
  return request('/v1/auth/verify', 'POST', { challenge_id: challenge.challenge_id, signature: result.signature }, { signal });
}
