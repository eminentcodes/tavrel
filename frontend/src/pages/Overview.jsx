import React, { useEffect, useState } from 'react';
import { ArrowRight, ArrowUpRight, Plus, Robot, Pause, Play, ArrowLeft, DownloadSimple } from '@phosphor-icons/react';
import { request, amount, download } from '../api.js';
import { Link, Button, Status, Empty, Field, Modal, PageHead, PaymentTable, Address, GlassForms } from '../components.jsx';

export function Overview({ data, pending, setModal, connected, walletAccount }) {
  const ready = data.intents.filter(item => item.status === 'ready_for_signature').length;
  return <><PageHead title="A clear view." action={<Button onClick={() => setModal({ type: 'agent' })}><Plus size={17} />New agent</Button>}>Your agents’ payments, with you in control.</PageHead>
    <section className="allowance-overview"><div><span>Available allowance</span><div className="big-amount">{connected ? amount(data.account.available_units) : '—'}<span>tVFY</span></div><p>{connected ? `Of ${amount(data.account.limit_units)} tVFY assigned to this account.` : 'Connect when you are ready to manage payments.'}</p></div><GlassForms small />
    <div className="allowance-side"><span>Reserved for requests</span><strong>{connected ? amount(data.account.reserved_units) : '—'} <small>tVFY</small></strong><span>Verified settlement</span><strong>{connected ? amount(data.settled_units) : '—'} <small>tVFY</small></strong></div></section>
    <section className="summary-strip"><div><span>Active agents</span><strong>{connected ? data.tasks.filter(task => !task.paused).length : '—'}</strong></div><div><span>Awaiting your review</span><strong>{connected ? pending.length : '—'}</strong></div><div><span>Ready to send</span><strong>{connected ? ready : '—'}</strong></div><Link href="/approvals">Review requests <ArrowUpRight size={20} /></Link></section>
    <section className="panel"><div className="section-head"><h2>Recent payments</h2><Link href="/ledger">View ledger <ArrowUpRight size={17} /></Link></div>{connected ? <PaymentTable intents={data.intents.slice(0, 5)} tasks={data.tasks} /> : <Empty title="Your payment activity">Requests and decisions appear here after you connect your wallet.</Empty>}</section>
    <div className="app-footnote"><span>Native payments on zkVerify Volta</span><span>Prepare → Review → Pay → Confirm</span></div>
  </>;
}
