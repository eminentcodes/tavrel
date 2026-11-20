import React, { useEffect, useState } from 'react';
import { ArrowRight, ArrowUpRight, Plus, Robot, Pause, Play, ArrowLeft, DownloadSimple } from '@phosphor-icons/react';
import { request, amount, download } from '../api.js';
import { Link, Button, Status, Empty, Field, Modal, PageHead, PaymentTable, Address, GlassForms } from '../components.jsx';

export function Recipients({ data }) {
  const rows = data.policies.flatMap(policy => Object.entries(policy.recipients).map(([name, address]) => ({ name, address, task: data.tasks.find(task => task.id === policy.task_id), policy })));
  return <><PageHead title="Known recipients.">Payment permissions belong to each agent’s policy.</PageHead><section className="panel">{rows.length ? <div className="table-wrap"><table><thead><tr><th>Recipient</th><th>Public account</th><th>Agent</th><th>Policy</th></tr></thead><tbody>{rows.map(row => <tr key={`${row.policy.task_id}-${row.name}`}><td>{row.name}</td><td><Address value={row.address} /></td><td>{row.task?.name}</td><td><Link href={`/agents/${row.policy.task_id}/policy`} className="text-link">Manage <ArrowUpRight size={16} /></Link></td></tr>)}</tbody></table></div> : <Empty title="No recipients configured">Add recipients in an agent’s policy to allow payments to known accounts.</Empty>}</section></>;
}
