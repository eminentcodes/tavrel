import React, { useEffect, useRef, useState } from 'react';
import { ArrowRight, ArrowUpRight, Wallet } from '@phosphor-icons/react';
import { installedWallets, rememberWallet, walletAccounts, warmWallet } from '../wallet.js';
import { authenticateWallet } from '../wallet-login.js';
import { Button, Brand, GlassForms, Link, Modal } from '../components.jsx';

export function Connection({ busy, error, onSignedIn, embedded = false }) {
  const [ticket] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('setup') || '');
  const [accounts, setAccounts] = useState([]);
  const [wallets, setWallets] = useState([]);
  const [connecting, setConnecting] = useState(false);
  const [progress, setProgress] = useState('');
  const [walletError, setWalletError] = useState('');
  const attempt = useRef(null);
  useEffect(() => {
    warmWallet().catch(() => {});
    if (ticket) window.history.replaceState({}, '', window.location.pathname);
    return () => { attempt.current?.abort(); attempt.current = null; };
  }, []);
  async function runConnection(work, label) {
    if (attempt.current) return;
    const controller = new AbortController();
    attempt.current = controller;
    setConnecting(true); setWalletError(''); setWallets([]); setProgress(label);
    try {
      await work(controller.signal);
    } catch (failure) {
      if (!controller.signal.aborted) setWalletError(failure.name === 'TimeoutError' ? 'The app did not respond. Check that Tavrel is running, then try again.' : failure.message || 'Could not connect your wallet.');
    } finally {
      if (attempt.current === controller) { attempt.current = null; setConnecting(false); setProgress(''); }
    }
  }
  async function finishSignIn(account, signal) {
    setAccounts([]);
    const result = await authenticateWallet(account, { signal, ticket, onProgress: setProgress });
    signal.throwIfAborted();
    rememberWallet(account.meta.source);
    setProgress('Opening your account');
    await onSignedIn(result.account, signal);
  }
  function signIn(account) {
    return runConnection(signal => finishSignIn(account, signal), 'Preparing sign-in');
  }
  async function connectSource(source) {
    return runConnection(async signal => {
      const available = await walletAccounts(source, { signal });
      signal.throwIfAborted();
      if (!available.length) throw new Error('Your wallet has no available Substrate account. Add an account and allow Tavrel to connect.');
      if (available.length === 1) await finishSignIn(available[0], signal);
      else setAccounts(available);
    }, 'Allow wallet access');
  }
  function cancelConnection() {
    attempt.current?.abort(); attempt.current = null;
    setConnecting(false); setProgress('');
    setWalletError('Connection cancelled. Close any pending request in your wallet before trying again.');
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
    {connecting && <div className="wallet-pending" role="status">{['Allow wallet access', 'Confirm in your wallet'].includes(progress) && <p>Open your wallet extension from the browser toolbar, unlock it, and check its pending request.</p>}<button type="button" className="text-link" onClick={cancelConnection}>Cancel connection</button></div>}
    {wallets.length > 0 && <div className="wallet-account-list" aria-label="Choose a wallet">{wallets.map(wallet => <button key={wallet.source} disabled={connecting} onClick={() => connectSource(wallet.source)}><Wallet size={22} /><strong>{wallet.name}</strong><ArrowRight size={17} /></button>)}</div>}
    {(error || walletError) && <div className="feedback error" role="alert">{walletError || error}</div>}
    <div className="wallet-options"><span>Substrate wallets</span><a href="https://www.subwallet.app/" target="_blank" rel="noreferrer">SubWallet <ArrowUpRight size={13} /></a><a href="https://talisman.xyz/" target="_blank" rel="noreferrer">Talisman <ArrowUpRight size={13} /></a></div>
    <Link href="/docs" className="text-link">Setup guide <ArrowUpRight size={16} /></Link>
  </div></div>{accounts.length > 0 && <Modal title="Choose an account." close={() => setAccounts([])}><div className="wallet-account-list">{accounts.map(account => <button key={account.address} onClick={() => signIn(account)}><Wallet size={22} /><div><strong>{account.meta.name || 'Wallet account'}</strong><span>{account.address.slice(0, 9)}…{account.address.slice(-7)}</span></div><ArrowRight size={17} /></button>)}</div></Modal>}</div>;
}
