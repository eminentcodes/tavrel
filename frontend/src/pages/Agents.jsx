import React, { useEffect, useState } from 'react';
import { ArrowRight, ArrowUpRight, Plus, Robot, Pause, Play, ArrowLeft, DownloadSimple } from '@phosphor-icons/react';
import { request, amount, download } from '../api.js';
import { Link, Button, Status, Empty, Field, Modal, PageHead, PaymentTable, Address, GlassForms } from '../components.jsx';

export function Agents({ data, setModal, connected }) {
  return <><PageHead title="Your agents." action={<Button onClick={() => setModal({ type: 'agent' })}><Plus size={17} />New agent</Button>}>A clear allowance and payment policy for each agent.</PageHead>
    {!connected ? <Empty title="Agents with clear boundaries">Connect your wallet when you are ready to create an agent and set its payment policy.</Empty> : !data.tasks.length ? <Empty title="Give your first agent an allowance">Create an agent, then add its payment policy.</Empty> : <div className="agent-grid">{data.tasks.map(task => {
      const policy = data.policies.find(item => item.task_id === task.id);
      return <Link href={`/agents/${task.id}`} className="agent-card" key={task.id}><div className="agent-card-top"><span className="agent-avatar"><Robot size={24} weight="light" /></span><Status value={task.paused ? 'Paused' : 'Active'} /></div><h2>{task.name}</h2><p>{task.description || 'An agent for controlled payments.'}</p><div className="agent-card-budget"><span>Available allowance</span><strong>{policy ? amount(policy.available_units) : '0'} <small>tVFY</small></strong></div><div className="agent-card-bottom"><span>{policy ? `${Object.keys(policy.recipients).length} approved recipients` : 'Policy setup needed'}</span><ArrowUpRight size={20} /></div></Link>;
    })}</div>}</>;
}
