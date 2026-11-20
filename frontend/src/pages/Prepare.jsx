import React, { useEffect, useState } from 'react';
import { ArrowRight, ArrowUpRight, Plus, Robot, Pause, Play, ArrowLeft, DownloadSimple } from '@phosphor-icons/react';
import { request, amount, download } from '../api.js';
import { Link, Button, Status, Empty, Field, Modal, PageHead, PaymentTable, Address, GlassForms } from '../components.jsx';

export function Prepare({ task, policy, close, busy, mutate }) {
  const [recipient, setRecipient] = useState(Object.keys(policy.recipients)[0] || '');
  const [value, setValue] = useState(''); const [purpose, setPurpose] = useState('');
  const [key, setKey] = useState(`invoice_${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`);
  return <Modal title="Prepare a payment." close={close}><form onSubmit={async event => { event.preventDefault(); const result = await mutate(() => request('/v1/operator/payments/prepare', 'POST', { task_id: task.id, recipient, amount: value, purpose, request_key: key }), result => `Payment prepared: ${result.status.replaceAll('_', ' ')}.`); if (result) { close(); window.history.pushState({}, '', `/payments/${result.id}`); window.dispatchEvent(new PopStateEvent('popstate')); } }}>
    <p className="form-note">{task.name} · zkVerify Volta · No funds will move.</p><Field label="Recipient" hint="Choose an approved recipient or enter a public address."><input list="approved-recipients" required value={recipient} onChange={event => setRecipient(event.target.value)} /></Field><datalist id="approved-recipients">{Object.keys(policy.recipients).map(name => <option value={name} key={name} />)}</datalist><Field label="Amount (tVFY)" hint="An exact decimal amount, with up to 18 decimal places."><input required inputMode="decimal" value={value} onChange={event => setValue(event.target.value)} /></Field><Field label="Payment purpose"><textarea required maxLength={1000} value={purpose} onChange={event => setPurpose(event.target.value)} /></Field><Field label="Request key" hint="Keep this key and the exact inputs when retrying."><input required pattern="[A-Za-z0-9_-]{1,100}" value={key} onChange={event => setKey(event.target.value)} /></Field><Button type="submit" busy={busy}>Check payment <ArrowRight size={17} /></Button>
  </form></Modal>;
}
