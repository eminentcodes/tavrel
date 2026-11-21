import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, ArrowUpRight, SquaresFour, Robot, Users, CheckCircle, ListBullets, GearSix, Plus, SignOut, Pause, Play, ArrowLeft, DownloadSimple, ArrowClockwise } from '@phosphor-icons/react';
import { Landing } from './Landing.jsx';
import { Connection } from './pages/Connection.jsx';
import { Overview } from './pages/Overview.jsx';
import { Agents } from './pages/Agents.jsx';
import { AgentDetail } from './pages/AgentDetail.jsx';
import { Policy } from './pages/Policy.jsx';
import { Recipients } from './pages/Recipients.jsx';
import { Ledger } from './pages/Ledger.jsx';
import { PaymentDetail } from './pages/PaymentDetail.jsx';
import { Settings } from './pages/Settings.jsx';
import { WalletBalance } from './pages/WalletBalance.jsx';
import { NewAgent } from './pages/NewAgent.jsx';
import { Prepare } from './pages/Prepare.jsx';
import { Docs } from './pages/Docs.jsx';
import { request } from './api.js';
import { rememberWallet } from './wallet.js';
import { Link, Button, Status, Empty, Field, Modal, PageHead, PaymentTable, Address, GlassForms, Brand } from './components.jsx';

const navigation = [
  ['Overview', '/dashboard', SquaresFour], ['Agents', '/agents', Robot],
  ['Recipients', '/vendors', Users], ['Approvals', '/approvals', CheckCircle],
  ['Ledger', '/ledger', ListBullets], ['Settings', '/settings', GearSix],
];
const initialData = { tasks: [], policies: [], intents: [], account: {}, network: {
  name: 'zkVerify Volta', websocket: 'wss://zkverify-volta-rpc.zkverify.io', symbol: 'tVFY', decimals: 18,
} };

export function App() {
  const [path, setPath] = useState(window.location.pathname);
  const [session, setSession] = useState(null);
  const [data, setData] = useState(initialData);
  const [walletBalance, setWalletBalance] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const loadedRoute = useRef('');
  const [modal, setModal] = useState(() => new URLSearchParams(window.location.hash.slice(1)).has('setup') ? { type: 'wallet' } : null);
  useEffect(() => {
    const onRoute = () => { setPath(window.location.pathname); setError(''); setNotice(''); setModal(null); window.scrollTo(0, 0); };
    window.addEventListener('popstate', onRoute);
    return () => window.removeEventListener('popstate', onRoute);
  }, []);
  const refresh = useCallback(async (signal) => {
    const [payments, app] = await Promise.all([request('/v1/operator/payments/status', 'GET', undefined, { signal }), request('/v1/operator/status', 'GET', undefined, { signal })]);
    signal?.throwIfAborted();
    setData({ ...payments, tasks: app.tasks, events: app.events });
  }, []);
  const enter = async (account, address, signal) => {
    setWalletBalance(null);
    await refresh(signal);
    signal?.throwIfAborted();
    loadedRoute.current = `${account}:${window.location.pathname}`;
    setSession({ account, address: address || account }); setError('');
  };
  useEffect(() => {
    let active = true;
    request('/v1/auth/status').then(async result => {
      if (active && result.authenticated) await enter(result.account, result.address);
    }).catch(() => {});
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (!session || path === '/') return;
    const routeKey = `${session.account}:${path}`;
    if (loadedRoute.current === routeKey) return;
    loadedRoute.current = routeKey;
    let active = true;
    refresh().catch(failure => { if (active) { if (failure.status === 401) { setSession(null); setData(initialData); } setError(failure.message); } });
    return () => { active = false; };
  }, [path, session, refresh]);
  async function mutate(work, message) {
    if (!session) { setModal({ type: 'wallet' }); return null; }
    setBusy(true); setError(''); setNotice('');
    try { const result = await work(); await refresh(); setNotice(typeof message === 'function' ? message(result) : message); return result; }
    catch (failure) { if (failure.status === 401) { setSession(null); setData(initialData); setModal({ type: 'wallet' }); } setError(failure.message); return null; }
    finally { setBusy(false); }
  }
  async function leave() { await request('/v1/auth/logout', 'POST', {}); rememberWallet(null); loadedRoute.current = ''; setSession(null); setData(initialData); }
  function authorize(work) { if (session) work(); else setModal({ type: 'wallet' }); }
  function actionModal(value) { if (session) setModal(value); else setModal({ type: 'wallet' }); }
  if (path === '/') return <Landing />;
  if (path === '/docs') return <Docs />;
  const pending = data.intents.filter(item => item.status === 'pending_approval');
  const segments = path.split('/').filter(Boolean);
  const task = data.tasks.find(item => item.id === segments[1]);
  const policy = data.policies.find(item => item.task_id === segments[1]);
  const props = { data, busy, mutate, setModal: actionModal, connected: !!session, walletAccount: session?.account, walletAddress: session?.address, walletBalance: walletBalance?.address === session?.account ? walletBalance : null, authorize, refresh };
  let page;
  if (path === '/dashboard' || path === '/connect') page = <Overview {...props} pending={pending} />;
  else if (path === '/agents') page = <Agents {...props} />;
  else if (segments[0] === 'agents' && !session) page = <Empty title="Agent details"><Button secondary onClick={() => setModal({ type: 'wallet' })}>Connect wallet</Button> to view this agent and manage its policy.</Empty>;
  else if (segments[0] === 'agents' && task) page = segments[2] === 'policy' ? <Policy key={task.id} {...props} task={task} policy={policy} /> : <AgentDetail {...props} task={task} policy={policy} />;
  else if (path === '/vendors') page = <Recipients {...props} />;
  else if (path === '/approvals') page = <><PageHead title="Approvals">A second look before the next step.</PageHead><div className="panel">{session ? <PaymentTable intents={pending} tasks={data.tasks} /> : <Empty title="Review agent requests">Connect your wallet when you are ready to view and approve your account's payments.</Empty>}</div></>;
  else if (path === '/ledger') page = <Ledger {...props} />;
  else if (segments[0] === 'payments') page = <PaymentDetail {...props} paymentId={segments[1]} />;
  else if (path === '/settings') page = <Settings {...props} />;
  else page = <Empty title="Page not found" action={<Link href="/dashboard" className="button">Go to overview</Link>}>This route is not available in this account.</Empty>;
  return <div className="app"><aside className="sidebar"><Brand /><div className="app-label"><span className="app-avatar">T</span><div>Agent control{session && <small title={session.address}>{`${session.address.slice(0, 7)}…${session.address.slice(-6)}`}</small>}</div></div>
    <nav aria-label="App navigation">{navigation.map(([label, href, Icon]) => <Link key={href} href={href} className={path.startsWith(href) ? 'active' : ''}><Icon size={20} weight={path.startsWith(href) ? 'fill' : 'regular'} />{label}{href === '/approvals' && pending.length > 0 && <span className="nav-count">{pending.length}</span>}</Link>)}</nav>
    <div className="sidebar-bottom"><div className="network-tag"><span />zkVerify Volta<small>Testnet · tVFY</small></div>{session && <button onClick={leave}><SignOut size={19} />Disconnect</button>}</div>
  </aside><div className="app-main"><header className="app-top"><div>{session ? <><WalletBalance connected walletAccount={session.account} onBalance={setWalletBalance} /><button className="icon-button" aria-label="Refresh app" disabled={busy} onClick={() => mutate(() => refresh(), 'Dashboard refreshed.')}><ArrowClockwise size={18} /></button></> : <Button secondary onClick={() => setModal({ type: 'wallet' })}>Connect wallet</Button>}</div></header>
    <main className="app-content">
    {error && <div className="feedback error" role="alert">{error}</div>}{notice && <div className="feedback success" role="status">{notice}</div>}{page}</main>
  </div>{modal?.type === 'agent' && <NewAgent {...props} close={() => setModal(null)} />}
  {modal?.type === 'prepare' && <Prepare {...props} task={modal.task} policy={modal.policy} close={() => setModal(null)} />}
  {modal?.type === 'wallet' && <Modal title="Sign in with your wallet." className="wallet-modal" close={() => setModal(null)}><Connection embedded busy={busy} error={error} onSignedIn={async (result, signal) => {
    setBusy(true); try { await enter(result.account, result.address, signal); setModal(null); }
    finally { setBusy(false); }
  }} /></Modal>}
  </div>;
}
