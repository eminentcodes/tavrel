import React, { useEffect, useState } from 'react';
import { Button, Field, Address, Link } from '../components.jsx';
import { request } from '../api.js';

export function AgentWallet({ task, policy, busy, mutate }) {
  const [wallet, setWallet] = useState(null);
  const [error, setError] = useState('');
  const [fee, setFee] = useState('0.001');
  const [hours, setHours] = useState('24');
  const [accepted, setAccepted] = useState(false);
  useEffect(() => { setAccepted(false); }, [policy?.version]);
  useEffect(() => {
    let active = true, timer;
    async function load() {
      try { const result = await request(`/v1/operator/tasks/${task.id}/wallet`); if (active) { setWallet(result); setError(''); } }
      catch (failure) { if (active) setError(failure.message); }
      if (active) timer = setTimeout(load, 6000);
    }
    load();
    return () => { active = false; clearTimeout(timer); };
  }, [task.id]);
  const matches = wallet?.address === policy?.sender;
  async function permission(enabled) {
    const result = await mutate(() => request(`/v1/operator/tasks/${task.id}/wallet`, 'PATCH', { enabled, expected_version: policy.version, fee_cap: fee, hours: Number(hours) }), enabled ? 'Agent-wallet signing enabled for the reviewed rules.' : 'Future agent-wallet signing stopped. Saved transactions still finish their existing recovery.');
    if (result) setWallet(result);
  }
  return <section className="panel agent-wallet"><div className="section-head"><div><h2>Pay without wallet prompts</h2><p>Use a separate wallet for payments that pass your agent’s rules.</p></div></div><div className="agent-wallet-content">
    {error && <p className="feedback error" role="alert">{error}</p>}
    {!wallet?.created ? <><p>Create an agent wallet, fund it with test tokens, then authorize its payment limits. Your connected wallet remains yours.</p><Button secondary busy={busy} onClick={async () => { const result = await mutate(() => request(`/v1/operator/tasks/${task.id}/wallet`, 'POST', {}), 'Agent wallet created. Fund it and set it as this agent’s sender.'); if (result) setWallet(result); }}>Create agent wallet</Button></> : <>
      <Field label="Agent wallet address" hint="Send tokens here or use this address in the Volta faucet."><input readOnly value={wallet.wallet_address} onFocus={event => event.target.select()} /></Field>
      <a className="text-link" href="https://www.faucy.com/zkverify-volta" target="_blank" rel="noreferrer">Get test tokens</a>
      {!matches && <p>Set this address as the sender in <Link className="text-link" href={`/agents/${task.id}/policy`}>the agent’s policy</Link> before enabling automatic signing.</p>}
      {wallet.authorized ? <><p>Automatic signing is active until {new Date(wallet.expires_at).toLocaleString()}. Payments above your approval threshold still wait for your decision.</p><Button secondary busy={busy} onClick={() => permission(false)}>Disable automatic signing</Button></> : <form onSubmit={event => { event.preventDefault(); permission(true); }}>
        <p>Tavrel holds this wallet’s encrypted signing key. Keep only the tokens your agent needs here. Signing permission expires and stops when the payment rules change.</p>
        <div className="form-grid"><Field label="Estimated fee cap (tVFY)"><input required inputMode="decimal" value={fee} onChange={event => setFee(event.target.value)} /></Field><Field label="Permission duration (hours)"><input required type="number" min="1" max="168" value={hours} onChange={event => setHours(event.target.value)} /></Field></div>
        <label className="checkbox"><input type="checkbox" checked={accepted} onChange={event => setAccepted(event.target.checked)} />Allow Tavrel to sign eligible payments from this agent wallet under policy version {policy?.version || '—'}.</label>
        <Button type="submit" busy={busy} disabled={!matches || !accepted || task.paused}>Enable automatic signing</Button>
      </form>}
      {wallet.last_error && <p className="reason-note">{wallet.last_error}</p>}
    </>}
  </div></section>;
}
