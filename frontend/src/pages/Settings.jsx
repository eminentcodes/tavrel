import React, { useEffect, useState } from 'react';
import { ArrowRight, ArrowUpRight, Plus, Robot, Pause, Play, ArrowLeft, DownloadSimple } from '@phosphor-icons/react';
import { request, amount, download } from '../api.js';
import { Link, Button, Status, Empty, Field, Modal, PageHead, PaymentTable, Address, GlassForms } from '../components.jsx';

export function Settings({ data, busy, mutate, connected, authorize }) {
  const [budget, setBudget] = useState(connected ? amount(data.account.limit_units) : '');
  useEffect(() => { setBudget(connected ? amount(data.account.limit_units) : ''); }, [connected, data.account.limit_units]);
  return <><PageHead title="Account settings.">Manage the shared payment allowance.</PageHead><form className="settings-form" onSubmit={event => { event.preventDefault(); mutate(() => request('/v1/operator/payments/account', 'PATCH', { budget }), 'Account allowance updated.'); }}><section className="form-section"><h2>Native-token allowance</h2><p>A policy limit shared by all agents. This is not a wallet balance or a deposit.</p><Field label="Account allowance (tVFY)" hint={connected ? `At least ${amount(data.account.reserved_units)} tVFY is currently held by payment requests.` : 'Connect your wallet to view and change your account allowance.'}><input required={connected} disabled={!connected} placeholder="Connect to view" inputMode="decimal" value={budget} onChange={event => setBudget(event.target.value)} /></Field><Button busy={busy} type={connected ? 'submit' : 'button'} onClick={connected ? undefined : () => authorize(() => {})}>Save allowance</Button></section><section className="form-section"><h2>Connection</h2><dl><dt>Account</dt><dd>{connected ? 'Wallet connected' : 'Wallet not connected'}</dd><dt>Network</dt><dd>zkVerify Volta</dd><dt>Native asset</dt><dd>tVFY · Test token</dd><dt>Sign-in</dt><dd>Wallet message signature</dd></dl></section></form></>;
}
