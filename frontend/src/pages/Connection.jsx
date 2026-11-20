import React, { useEffect, useState } from 'react';
import { ArrowRight, ArrowUpRight, Wallet } from '@phosphor-icons/react';
import { request } from '../api.js';
import { installedWallets, rememberWallet, walletAccounts, walletProvider, warmWallet } from '../wallet.js';
import { Button, Brand, GlassForms, Link, Modal } from '../components.jsx';

export function Connection({ busy, error, onSignedIn, embedded = false }) {
  const [ticket] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('setup') || '');
  const [accounts, setAccounts] = useState([]);
  const [wallets, setWallets] = useState([]);
  const [connecting, setConnecting] = useState(false);
  const [progress, setProgress] = useState('');
  const [walletError, setWalletError] = useState('');
  useEffect(() => {
    warmWallet().catch(() => {});
    if (ticket) window.history.replaceState({}, '', window.location.pathname);
  }, []);
  async function signIn(account) {
    setConnecting(true); setWalletError(''); setAccounts([]); setProgress('Preparing sign-in');
    try {
      const provider = await walletProvider(account.meta.source);
      if (!provider.signer.signRaw) throw new Error('This wallet does not support signed-message login. Choose a compatible Substrate wallet.');
      const challenge = await request('/v1/auth/challenge', 'POST', { address: account.address, ...(ticket ? { ticket } : {}) });
      const bytes = new TextEncoder().encode(challenge.message);
      const data = '0x' + Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
      setProgress('Confirm in your wallet');
      const { signature } = await provider.signer.signRaw({ address: account.address, data, type: 'bytes' });
      setProgress('Verifying signature');
      const result = await request('/v1/auth/verify', 'POST', { challenge_id: challenge.challenge_id, signature });
      rememberWallet(account.meta.source);
      setProgress('Opening your account');
      await onSignedIn(result.account);
    } catch (failure) { setWalletError(failure.message || 'Wallet sign-in was cancelled.'); }
    finally { setConnecting(false); setProgress(''); }
  }
  async function connectSource(source) {
    setConnecting(true); setWalletError(''); setWallets([]); setProgress('Allow wallet access');
    try {
      const available = await walletAccounts(source);
      if (!available.length) throw new Error('Your wallet has no available Substrate account. Add an account and allow Tavrel to connect.');
      if (available.length === 1) await signIn(available[0]);
      else setAccounts(available);
    } catch (failure) { setWalletError(failure.message || 'Could not connect your wallet.'); }
    finally { setConnecting(false); setProgress(''); }
  }
  async function connectWallet() {
    setWalletError('');
    const available = installedWallets();
    if (!available.length) { setWalletError('No compatible wallet found. Install or unlock SubWallet, Talisman, or the Polkadot extension, then refresh this page.'); return; }
    if (available.length === 1) await connectSource(available[0].source);
    else setWallets(available);
  }
  return <div className={embedded ? 'wallet-embedded' : 'connection-page'}>{!embedded && <Brand />}<div className={embedded ? '' : 'connection-grid'}>{!embedded && <div className="connection-art"><GlassForms small /><h1>Payments,<br />under your control.</h1></div>}<div className="connection-form">
    <span className="wallet-symbol"><Wallet size={28} weight="light" /></span>{!embedded && <h2>Connect your wallet.</h2>}<p>Sign in to manage your agents, payment rules, and approvals.</p>
    <Button busy={busy || connecting} onClick={connectWallet}>{connecting ? progress : 'Connect wallet'}<ArrowRight size={18} /></Button>
    {wallets.length > 0 && <div className="wallet-account-list" aria-label="Choose a wallet">{wallets.map(wallet => <button key={wallet.source} disabled={connecting} onClick={() => connectSource(wallet.source)}><Wallet size={22} /><strong>{wallet.name}</strong><ArrowRight size={17} /></button>)}</div>}
    {(error || walletError) && <div className="feedback error" role="alert">{walletError || error}</div>}
    <div className="wallet-options"><span>Substrate wallets</span><a href="https://www.subwallet.app/" target="_blank" rel="noreferrer">SubWallet <ArrowUpRight size={13} /></a><a href="https://talisman.xyz/" target="_blank" rel="noreferrer">Talisman <ArrowUpRight size={13} /></a></div>
    <Link href="/docs" className="text-link">Setup guide <ArrowUpRight size={16} /></Link>
  </div></div>{accounts.length > 0 && <Modal title="Choose an account." close={() => setAccounts([])}><div className="wallet-account-list">{accounts.map(account => <button key={account.address} onClick={() => signIn(account)}><Wallet size={22} /><div><strong>{account.meta.name || 'Wallet account'}</strong><span>{account.address.slice(0, 9)}…{account.address.slice(-7)}</span></div><ArrowRight size={17} /></button>)}</div></Modal>}</div>;
}
