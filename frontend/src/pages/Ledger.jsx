import React, { useEffect, useState } from 'react';
import { ArrowRight, ArrowUpRight, Plus, Robot, Pause, Play, ArrowLeft, DownloadSimple } from '@phosphor-icons/react';
import { request, amount, download } from '../api.js';
import { Link, Button, Status, Empty, Field, Modal, PageHead, PaymentTable, Address, GlassForms } from '../components.jsx';

export function Ledger({ data, authorize }) {
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const rows = data.intents.filter(item => (filter === 'all' || item.status === filter) && `${item.purpose} ${item.id} ${item.request_key}`.toLowerCase().includes(search.toLowerCase()));
  return <><PageHead title="The payment ledger." action={<Button secondary onClick={() => authorize(() => download({ network: data.network, intents: rows }, 'tavrel-ledger.json'))}><DownloadSimple size={17} />Export JSON</Button>}>Your payment requests, decisions, and verified transfer receipts.</PageHead><div className="ledger-toolbar"><Field label="Search payments"><input type="search" value={search} onChange={event => setSearch(event.target.value)} /></Field><Field label="Status"><select value={filter} onChange={event => setFilter(event.target.value)}><option value="all">All requests</option><option value="pending_approval">Needs approval</option><option value="ready_for_signature">Ready to send</option><option value="blocked">Blocked</option><option value="denied">Denied</option><option value="submitting">Sending</option><option value="submitted">Awaiting confirmation</option><option value="settled">Confirmed</option><option value="failed">Failed</option><option value="expired">Expired</option></select></Field><span>Latest 100 app requests</span></div><section className="panel"><PaymentTable intents={rows} tasks={data.tasks} /></section></>;
}
