import React, { useEffect, useState } from 'react';
import { ArrowUpRight, Stop, Play, Plus } from '@phosphor-icons/react';
import { request, paymentReason } from '../api.js';
import { Button, Field, Link, PaymentTable } from '../components.jsx';

const labels = { queued: 'Queued', running: 'Processing invoices', completed: 'Invoices prepared', interrupted: 'Interrupted', failed: 'Stopped', cancelled: 'Cancelled' };
const tools = { read_rules: 'Checked payment rules', read_source: 'Read invoice details', prepare_payment: 'Prepared a payment request', finish: 'Finished preparation' };
const emptyInvoice = () => ({ invoice_reference: '', recipient: '', amount: '', purpose: '' });

function Run({ run, busy, act, historical = false }) {
  return <article className="agent-run"><div className="section-head"><div><h3>{run.goal}</h3><span>{labels[run.status] || run.status}</span></div>{!historical && ['queued', 'running'].includes(run.status) && <Button secondary busy={busy} onClick={() => act(run, 'cancel')}><Stop size={15} />Stop task</Button>}</div>
    {run.error && <p className="feedback error">{run.error}</p>}
    <ol className="agent-activity">{run.actions.map(action => <li key={action.slot}><span>{action.status === 'pending' ? 'Waiting: ' : ''}{tools[action.name] || action.name}</span>{action.result?.error && <p className="reason-note">{action.result.message}</p>}{action.result?.id && <Link className="text-link" href={`/payments/${action.result.id}`}>View payment <ArrowUpRight size={15} /></Link>}{action.result?.reason && <p>{paymentReason(action.result.reason)}</p>}</li>)}</ol>
    {!historical && ['failed', 'interrupted'].includes(run.status) && <Button secondary busy={busy} onClick={() => act(run, 'resume')}><Play size={15} />Resume task</Button>}
    {run.payments.length > 0 && <PaymentTable intents={run.payments} compact />}
    {!historical && run.status === 'completed' && <p>Invoices are prepared. Eligible payments use automatic signing when enabled; review the other requests below.</p>}
    {run.status === 'cancelled' && <p>Invoice preparation stopped. Existing payment requests and wallet permissions still apply.</p>}
  </article>;
}

export function AgentGoal({ task, policy, busy, mutate, refresh }) {
  const [goal, setGoal] = useState('');
  const [invoices, setInvoices] = useState([emptyInvoice()]);
  const [requestKey, setRequestKey] = useState(() => `batch_${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`);
  const [runs, setRuns] = useState([]);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true, timer, lastVersion = '';
    const load = async () => {
      try {
        const result = await request(`/v1/operator/tasks/${task.id}/runs`);
        if (!active) return;
        setRuns(result.runs); setError('');
        const version = result.runs.map(run => run.updated_at).join();
        if (lastVersion && version !== lastVersion) await refresh();
        lastVersion = version;
      } catch (failure) { if (active) setError(failure.message); }
      if (active) timer = setTimeout(load, 4000);
    };
    load();
    return () => { active = false; clearTimeout(timer); };
  }, [task.id, refresh]);
  async function act(run, suffix) {
    const result = await mutate(() => request(`/v1/operator/runs/${run.id}/${suffix}`, 'POST', {}), suffix === 'cancel' ? 'Invoice preparation stopped. Existing requests remain available.' : 'Invoice task resumed.');
    if (result) setRuns(current => current.map(item => item.id === result.id ? result : item));
  }
  function change(index, key, value) { setInvoices(current => current.map((row, at) => at === index ? { ...row, [key]: value } : row)); }
  const currentRuns = runs.filter(run => run.executor === 'invoice_rules_v1');
  const previousRuns = runs.filter(run => run.executor !== 'invoice_rules_v1');
  return <section className="panel agent-goals"><div className="section-head"><div><h2>Give your agent a task</h2><p>Add the invoices. Your agent checks the rules and prepares each payment.</p></div></div>
    <form onSubmit={async event => {
      event.preventDefault();
      const result = await mutate(() => request(`/v1/operator/tasks/${task.id}/runs`, 'POST', { goal, invoices, request_key: requestKey }), 'Invoice task started. Payment requests appear below.');
      if (result) { setRuns(current => [result, ...current.filter(run => run.id !== result.id)]); setGoal(''); setInvoices([emptyInvoice()]); setRequestKey(`batch_${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`); }
    }}>
      <Field label="Payment task name"><input required maxLength={200} value={goal} onChange={event => setGoal(event.target.value)} placeholder="November service invoices" /></Field>
      <datalist id={`recipients-${task.id}`}>{Object.keys(policy?.recipients || {}).map(name => <option key={name} value={name} />)}</datalist>
      {invoices.map((invoice, index) => <div className="invoice-entry" key={index}><div className="section-head"><h3>Invoice {index + 1}</h3>{invoices.length > 1 && <button type="button" className="text-link" onClick={() => setInvoices(current => current.filter((_, at) => at !== index))}>Remove invoice {index + 1}</button>}</div><div className="form-grid">
        <Field label={`Invoice ${index + 1} reference`} hint="Reuse this reference when retrying this invoice."><input required maxLength={80} pattern="[A-Za-z0-9_-]+" value={invoice.invoice_reference} onChange={event => change(index, 'invoice_reference', event.target.value)} placeholder="INV-001" /></Field>
        <Field label={`Invoice ${index + 1} recipient`} hint="Choose an approved name or paste a public wallet address."><input required list={`recipients-${task.id}`} value={invoice.recipient} onChange={event => change(index, 'recipient', event.target.value)} autoComplete="off" spellCheck={false} /></Field>
        <Field label={`Invoice ${index + 1} amount (tVFY)`}><input required inputMode="decimal" value={invoice.amount} onChange={event => change(index, 'amount', event.target.value)} placeholder="0.005" /></Field>
        <Field label={`Invoice ${index + 1} purpose`}><input required maxLength={1000} value={invoice.purpose} onChange={event => change(index, 'purpose', event.target.value)} placeholder="Service invoice" /></Field>
      </div></div>)}
      <div className="invoice-task-actions"><Button type="button" secondary disabled={invoices.length >= 20 || busy} onClick={() => setInvoices(current => [...current, emptyInvoice()])}><Plus size={16} />Add invoice</Button><Button type="submit" busy={busy} disabled={!policy || task.paused}>Start task</Button></div>
      <p className="form-note">The same invoice reference identifies the same payment for this agent. Payments still follow your allowances, approvals, and wallet permissions.</p>
    </form>
    {error && <p role="alert" className="feedback error">{error}</p>}
    {currentRuns.map(run => <Run key={run.id} run={run} busy={busy} act={act} />)}
    {previousRuns.length > 0 && <details className="previous-agent-tasks"><summary>Earlier tasks</summary><p>These records are from the earlier model setup. Use the invoice form above to start a new task.</p>{previousRuns.map(run => <Run key={run.id} run={run} historical />)}</details>}
  </section>;
}
