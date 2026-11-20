import React, { useEffect, useState } from 'react';
import { ArrowRight, ArrowUpRight, Plus, Robot, Pause, Play, ArrowLeft, DownloadSimple } from '@phosphor-icons/react';
import { request, amount, download } from '../api.js';
import { Link, Button, Status, Empty, Field, Modal, PageHead, PaymentTable, Address, GlassForms } from '../components.jsx';

export function NewAgent({ close, busy, mutate }) {
  const [name, setName] = useState(''); const [description, setDescription] = useState('');
  return <Modal title="A new agent." close={close}><form onSubmit={async event => { event.preventDefault(); const result = await mutate(() => request('/v1/operator/tasks', 'POST', { name, description, limit_cents: 0, threshold_cents: 0, allowed_services: [] }), 'Agent created. Configure its native-payment policy next.'); if (result) { close(); window.history.pushState({}, '', `/agents/${result.task.id}/policy`); window.dispatchEvent(new PopStateEvent('popstate')); } }}><Field label="Agent name"><input autoFocus required maxLength={100} value={name} onChange={event => setName(event.target.value)} /></Field><Field label="What will it do?"><textarea value={description} maxLength={1000} onChange={event => setDescription(event.target.value)} /></Field><p className="form-note">Payment permissions start empty. Add an allowance and approved recipients in the next screen.</p><Button type="submit" busy={busy}>Create agent <ArrowRight size={17} /></Button></form></Modal>;
}
