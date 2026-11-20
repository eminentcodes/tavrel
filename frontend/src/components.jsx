import React, { useEffect, useRef } from 'react';
import { ArrowUpRight, ArrowRight, X, CircleNotch } from '@phosphor-icons/react';

export const labels = {
  pending_approval: 'Needs approval', ready_for_signature: 'Ready to send',
  blocked: 'Blocked', denied: 'Denied', exported: 'Ready to send',
  submitting: 'Sending', submitted: 'Awaiting confirmation', settled: 'Confirmed', failed: 'Failed', expired: 'Expired',
};

export function Link({ href, children, className = '', ...props }) {
  return <a href={href} className={className} {...props} onClick={(event) => {
    if (!event.metaKey && !event.ctrlKey && !event.shiftKey && event.button === 0 && href.startsWith('/')) {
      event.preventDefault(); window.history.pushState({}, '', href); window.dispatchEvent(new PopStateEvent('popstate'));
    }
  }}>{children}</a>;
}
export function Button({ children, secondary, busy, ...props }) {
  return <button className={`button ${secondary ? 'secondary' : ''}`} {...props} disabled={busy || props.disabled}>
    {children}{busy ? <CircleNotch className="spin" size={17} /> : null}
  </button>;
}
export function Status({ value }) { return <span className={`status ${value}`}>{labels[value] || value}</span>; }
export function Empty({ title, children, action }) {
  return <div className="empty"><h3>{title}</h3><p>{children}</p>{action}</div>;
}
export function Field({ label, hint, children, wide }) {
  const id = React.useId();
  return <div className={`field ${wide ? 'wide' : ''}`}>
    <label htmlFor={id}>{label}</label>{React.cloneElement(children, { id, 'aria-describedby': hint ? `${id}-hint` : undefined })}
    {hint && <small id={`${id}-hint`}>{hint}</small>}
  </div>;
}
export function Modal({ title, children, close, className = '' }) {
  const ref = useRef();
  const titleId = React.useId();
  useEffect(() => {
    const dialog = ref.current;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  return <dialog ref={ref} className={`modal ${className}`} aria-labelledby={titleId} onCancel={close} onClick={(event) => { if (event.target === ref.current) close(); }}>
    <div className="modal-head"><h2 id={titleId}>{title}</h2><button aria-label="Close dialog" className="icon-button" onClick={close}><X size={21} /></button></div>
    {children}
  </dialog>;
}
export function PageHead({ title, children, action }) {
  return <div className="page-head"><div><h1>{title}</h1>{children && <p>{children}</p>}</div>{action}</div>;
}
export function Address({ value }) { return <code className="address" title={value}>{value}</code>; }
export function PaymentTable({ intents, tasks = [], compact = false }) {
  if (!intents.length) return <Empty title="No payment requests yet">Prepare a payment from an agent’s dashboard to see its policy decision here.</Empty>;
  return <div className="table-wrap"><table>
    <thead><tr><th>Payment</th>{!compact && <th>Agent</th>}<th>Amount</th><th>Status</th><th><span className="sr-only">View payment</span></th></tr></thead>
    <tbody>{intents.map((item) => <tr key={item.id}>
      <td><Link href={`/payments/${item.id}`} className="table-link">{item.purpose}</Link><small>{new Date(item.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} · {item.request_key}</small></td>
      {!compact && <td>{tasks.find(task => task.id === item.task_id)?.name || item.task_id}</td>}
      <td className="money">{item.amount}<small>tVFY</small></td><td><Status value={item.status} /></td>
      <td><Link href={`/payments/${item.id}`} className="icon-button" aria-label={`Review ${item.purpose}`}><ArrowUpRight size={19} /></Link></td>
    </tr>)}</tbody>
  </table></div>;
}
export function GlassForms({ small = false }) {
  // Three code-native geometric lenses, following the supplied reference.
  return <div className={`glass-art ${small ? 'small' : ''}`} aria-hidden="true"><div className="light-band" /><div className="lens lens-back" /><div className="lens lens-middle" /><div className="lens lens-front" /></div>;
}
export function ArrowCTA({ href, children }) { return <Link href={href} className="button">{children}<ArrowRight size={19} /></Link>; }
export function Brand() { return <Link href="/" className="brand" aria-label="Tavrel home"><img src="/tavrel-mark.svg" width="37" height="37" alt="" /><span className="wordmark">tavrel</span></Link>; }
