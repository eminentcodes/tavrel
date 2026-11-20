import React, { useEffect, useState } from 'react';
import { ArrowRight, ArrowUpRight, Plus, Robot, Pause, Play, ArrowLeft, DownloadSimple } from '@phosphor-icons/react';
import { request, amount, download } from '../api.js';
import { Link, Button, Status, Empty, Field, Modal, PageHead, PaymentTable, Address, GlassForms } from '../components.jsx';

export function AgentDetail({ task, policy, data, busy, mutate, setModal }) {
  const [connectionOpen, setConnectionOpen] = useState(false);
  return <><Link className="back-link" href="/agents"><ArrowLeft size={17} />All agents</Link><PageHead title={task.name} action={<Button disabled={!policy || task.paused} onClick={() => setModal({ type: 'prepare', task, policy })}><Plus size={17} />Prepare payment</Button>}>{task.description || 'Your agent’s payment dashboard.'}</PageHead>
    <div className="detail-actions"><Status value={task.paused ? 'Paused' : 'Active'} /><Link href={`/agents/${task.id}/policy`} className="text-link">Edit policy <ArrowUpRight size={17} /></Link><Button secondary busy={busy} onClick={() => mutate(() => request(`/v1/operator/tasks/${task.id}`, 'PATCH', { paused: !task.paused }), task.paused ? 'Agent resumed.' : 'Agent paused.')}>{task.paused ? <Play size={15} /> : <Pause size={15} />}{task.paused ? 'Resume' : 'Pause'}</Button></div>
    {policy ? <><div className="detail-stats"><div><span>Available</span><strong>{amount(policy.available_units)} <small>tVFY</small></strong></div><div><span>Held</span><strong>{amount(policy.reserved_units)} <small>tVFY</small></strong></div><div><span>Approval above</span><strong>{policy.require_approval ? 'Every payment' : amount(policy.threshold_units)} {!policy.require_approval && <small>tVFY</small>}</strong></div></div><section className="panel"><div className="section-head"><h2>Payment history</h2><span>Last 100 app requests</span></div><PaymentTable intents={data.intents.filter(item => item.task_id === task.id)} compact /></section></> : <Empty title="Set this agent’s boundaries" action={<Link href={`/agents/${task.id}/policy`} className="button">Configure policy</Link>}>Add a public sender account, an allowance, and approved recipients before preparing payments.</Empty>}
    <section className="panel"><div className="section-head"><div><h2>Connect an agent</h2><p>Give your agent access to prepare payments and read their status.</p></div><Button secondary onClick={() => setConnectionOpen(true)}>Agent connection</Button></div></section>
    {connectionOpen && <Modal title="Agent connection" close={() => setConnectionOpen(false)}><p>Download a connection file for this agent. This creates a new task token and revokes its previous token.</p><p>Keep the file with your agent. It cannot approve requests, change rules, or sign transfers.</p><Button busy={busy} onClick={async () => {
      const result = await mutate(() => request(`/v1/operator/tasks/${task.id}/token`, 'POST', {}), 'Agent connection created. The previous task token was revoked.');
      if (result) { download({ ...result, gateway_url: window.location.origin }, `${task.id}-connection.json`); setConnectionOpen(false); }
    }}><DownloadSimple size={17} />Create and download</Button></Modal>}
  </>;
}
