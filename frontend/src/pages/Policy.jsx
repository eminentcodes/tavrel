import React, { useEffect, useState } from 'react';
import { ArrowRight, ArrowUpRight, Plus, Robot, Pause, Play, ArrowLeft, DownloadSimple } from '@phosphor-icons/react';
import { request, amount, download } from '../api.js';
import { Link, Button, Status, Empty, Field, Modal, PageHead, PaymentTable, Address, GlassForms } from '../components.jsx';

export function Policy({ task, policy, busy, mutate }) {
  const [sender, setSender] = useState(policy?.sender || '');
  const [budget, setBudget] = useState(amount(policy?.limit_units));
  const [approval, setApproval] = useState(amount(policy?.threshold_units));
  const [cap, setCap] = useState(policy ? amount(policy.per_payment_units) : '1');
  const [every, setEvery] = useState(policy?.require_approval || false);
  const [recipients, setRecipients] = useState(Object.entries(policy?.recipients || {}).map(([name, address]) => ({ name, address })));
  const [localError, setLocalError] = useState('');
  return <><Link className="back-link" href={`/agents/${task.id}`}><ArrowLeft size={17} />{task.name}</Link><PageHead title="The boundaries.">Define what this agent can prepare, and when you take a look.</PageHead><form className="policy-form" onSubmit={async event => {
    event.preventDefault(); setLocalError('');
    const names = recipients.map(item => item.name.trim());
    if (new Set(names).size !== names.length) { setLocalError('Recipient names must be unique.'); return; }
    await mutate(() => request(`/v1/operator/payments/policies/${task.id}`, 'PATCH', { sender, budget, approval, per_payment: cap, require_approval: every, recipients: Object.fromEntries(recipients.map((item, index) => [names[index], item.address.trim()])) }), 'Policy saved. Existing payments will be checked against the new version before approval or signing.');
  }}><section className="form-section"><h2>Public payment account</h2><p>This wallet signs and sends the agent’s payments.</p><Field label="Sender address" hint="Use a checksum-valid SS58 address or a 32-byte public AccountId. Never enter a private key."><input required value={sender} onChange={event => setSender(event.target.value)} autoComplete="off" /></Field></section>
  <section className="form-section"><h2>Spending envelope</h2><div className="form-grid"><Field label="Task allowance (tVFY)"><input inputMode="decimal" required value={budget} onChange={event => setBudget(event.target.value)} /></Field><Field label="Per-payment cap (tVFY)"><input inputMode="decimal" required value={cap} onChange={event => setCap(event.target.value)} /></Field><Field label="Approval above (tVFY)" hint="Amounts equal to the threshold can proceed automatically."><input inputMode="decimal" required value={approval} onChange={event => setApproval(event.target.value)} /></Field></div><label className="checkbox"><input type="checkbox" checked={every} onChange={event => setEvery(event.target.checked)} />Require approval for every payment</label></section>
  <section className="form-section"><h2>Approved recipients</h2><p>Only these public accounts can pass this agent’s payment policy.</p>{recipients.map((item, index) => <div className="recipient-fields" key={index}><Field label={`Recipient ${index + 1} name`}><input required pattern="[A-Za-z0-9_-]{1,60}" value={item.name} onChange={event => setRecipients(recipients.map((row, i) => i === index ? { ...row, name: event.target.value } : row))} /></Field><Field label="Public address"><input required value={item.address} onChange={event => setRecipients(recipients.map((row, i) => i === index ? { ...row, address: event.target.value } : row))} /></Field><Button type="button" secondary onClick={() => setRecipients(recipients.filter((_, i) => i !== index))}>Remove</Button></div>)}<Button type="button" secondary onClick={() => setRecipients([...recipients, { name: '', address: '' }])}><Plus size={16} />Add recipient</Button></section>
  {localError && <div role="alert" className="feedback error">{localError}</div>}<div className="form-footer"><span>Changes create a new policy version.</span><Button busy={busy} type="submit">Save policy <ArrowRight size={17} /></Button></div></form></>;
}
