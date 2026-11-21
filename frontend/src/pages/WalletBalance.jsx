import React, { useEffect, useState } from 'react';
import { ArrowClockwise, CircleNotch, Wallet } from '@phosphor-icons/react';
import { request, amount } from '../api.js';
import { Button, Address } from '../components.jsx';

export function WalletBalance({ connected, walletAccount, onBalance }) {
  const [balance, setBalance] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setError('');
    if (!connected || !walletAccount) { setBalance(null); setLoading(false); return; }
    setLoading(true);
    request(`/v1/operator/wallet/balance?address=${encodeURIComponent(walletAccount)}`).then(result => { if (active) { setBalance(result); onBalance?.(result); } }).catch(failure => { if (active) setError(failure.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [connected, walletAccount, revision, onBalance]);
  return <button className={`wallet-balance-pill${error ? ' balance-error' : ''}`} type="button" disabled={!connected || loading} aria-label="Refresh wallet balance" title={error || (balance ? `${balance.wallet_address} · ${amount(balance.transferable_units)} tVFY available before fees · Click to refresh` : 'Wallet tokens on zkVerify Volta')} onClick={() => setRevision(current => current + 1)}><Wallet size={16} /><span aria-live="polite">{balance ? `${amount(balance.free_units)} tVFY` : error ? 'Balance unavailable' : 'Checking balance…'}</span>{loading ? <CircleNotch className="spin" size={14} /> : <ArrowClockwise size={14} />}</button>;
}
