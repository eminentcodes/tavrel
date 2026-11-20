import React, { useEffect, useState } from 'react';
import { ArrowRight, ArrowUpRight, ArrowLeft, DownloadSimple, ArrowClockwise } from '@phosphor-icons/react';
import { request, amount, download } from '../api.js';
import { signPayment } from '../wallet.js';
import { Link, Button, Status, Empty, PageHead, Address } from '../components.jsx';

export function PaymentDetail({ paymentId, data, busy, mutate, connected, authorize, refresh }) {
  const [payment, setPayment] = useState(data.intents.find(item => item.id === paymentId));
  const [error, setError] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [quote, setQuote] = useState(null);
  useEffect(() => {
    if (!connected) { setPayment(null); setError(''); return; }
    let active = true;
    request(`/v1/operator/payments/${paymentId}`).then(result => {
      if (active) { setPayment(result); setError(''); }
    }).catch(failure => { if (active) { setPayment(null); setError(failure.message); } });
    return () => { active = false; };
  }, [paymentId, data, connected]);
  useEffect(() => { setConfirmed(false); setQuote(null); }, [paymentId, payment?.approval_hash, payment?.status]);
  useEffect(() => {
    if (!['submitting', 'submitted'].includes(payment?.status)) return;
    const timer = setInterval(() => refresh().catch(failure => setError(failure.message)), 6000);
    return () => clearInterval(timer);
  }, [payment?.status, refresh]);
  if (!connected) return <Empty title="Payment details" action={<Button secondary onClick={() => authorize(() => {})}>Connect wallet</Button>}>Connect when you are ready to view and review this payment.</Empty>;
  if (!payment) return <Empty title={error || 'Loading payment…'}>The amount, recipient, and payment result appear here.</Empty>;
  const task = data.tasks.find(task => task.id === payment.task_id);
  const transaction = payment.transaction;
  const receipt = transaction?.receipt;
  const ready = ['ready_for_signature', 'exported'].includes(payment.status);
  async function decide(decision) {
    await mutate(() => request(`/v1/operator/payments/${payment.id}/decision`, 'POST', { expected_hash: payment.approval_hash, decision }),
      result => result.status === 'blocked' ? `Request blocked: ${result.reason}.` : result.reason === 'POLICY_CHANGED_REVIEW_AGAIN' ? 'Rules changed. Review the updated payment.' : decision === 'deny' ? 'Payment denied. Its allowance has been released.' : 'Payment approved. Review fees to send it.');
  }
  async function reviewFees() {
    const result = await mutate(() => request(`/v1/operator/payments/${payment.id}/quote`, 'POST', { expected_hash: payment.approval_hash }), 'Current wallet balance and estimated network fee checked.');
    if (result) setQuote(result);
  }
  async function send() {
    await mutate(async () => {
      const signature = await signPayment(quote.payload, payment.sender);
      return request(`/v1/operator/payments/${payment.id}/submit`, 'POST', { expected_hash: payment.approval_hash, quote_id: quote.quote_id, ...signature });
    }, 'Signed payment saved. Tavrel will submit it and check finalized chain history.');
  }
  return <><Link href="/ledger" className="back-link"><ArrowLeft size={17} />Payment ledger</Link><PageHead title={payment.purpose}>{task?.name} · {payment.id}</PageHead>
  <section className="payment-detail"><div className="payment-detail-top"><div><span>Payment amount</span><strong>{payment.amount} <small>tVFY</small></strong></div><Status value={payment.status} /></div>
    <dl className="intent-fields"><div><dt>Network</dt><dd>zkVerify Volta · Testnet</dd></div><div><dt>Sender</dt><dd><Address value={payment.sender} /></dd></div><div><dt>Recipient</dt><dd><Address value={payment.recipient} /></dd></div><div><dt>Payment rules</dt><dd>Version {payment.policy_version}</dd></div><div><dt>Request key</dt><dd>{payment.request_key}</dd></div><div><dt>Review fingerprint</dt><dd><code className="break">{payment.approval_hash}</code></dd></div></dl>
    {payment.reason && <div className="reason-note">{payment.reason}</div>}
    {error && <div className="feedback error" role="alert">{error}</div>}
    {(payment.status === 'pending_approval' || ready) && <div className="decision-area">
      <label className="checkbox"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I have reviewed the amount, recipient, network, and payment rules.</label>
      <div className="decision-buttons">{payment.status !== 'exported' && <Button secondary disabled={!confirmed} busy={busy} onClick={() => decide('deny')}>Deny request</Button>}
        <Button disabled={!confirmed} busy={busy} onClick={payment.status === 'pending_approval' ? () => decide('approve') : reviewFees}>{payment.status === 'pending_approval' ? 'Approve request' : 'Review fees'}<ArrowRight size={17} /></Button>
      </div>
    </div>}
    {ready && quote && <div className="export-area"><h2>Send this payment</h2><dl className="intent-fields"><div><dt>Estimated network fee</dt><dd>{amount(quote.fee_units)} tVFY</dd></div><div><dt>Transferable balance</dt><dd>{amount(quote.transferable_units)} tVFY</dd></div></dl>
      <p>Your wallet will ask you to sign this transfer. The fee is charged in addition to the payment and can change before inclusion.</p>
      {!quote.enough_funds && <div className="feedback error">The sender needs more tVFY to cover this payment and the network fee. <a href="https://www.faucy.com/zkverify-volta" target="_blank" rel="noreferrer">Get test tokens</a>.</div>}
      <Button disabled={!confirmed || !quote.enough_funds} busy={busy} onClick={send}>Sign and send<ArrowRight size={17} /></Button>
    </div>}
    {transaction && <div className="export-area"><h2>{payment.status === 'settled' ? 'Payment confirmed' : payment.status === 'failed' ? 'Transfer failed' : payment.status === 'expired' ? 'Transaction expired' : 'Waiting for confirmation'}</h2>
      <p>{payment.status === 'settled' ? 'The matching transfer succeeded in a finalized zkVerify block.' : payment.status === 'failed' ? 'The finalized transaction failed. Payment funds were released from the allowance; a network fee may still apply.' : payment.status === 'expired' ? transaction.error : 'The payment allowance stays reserved while Tavrel checks the chain. You can leave this page and return later.'}</p>
      <a className="text-link break" href={`${payment.network.explorer}/extrinsic/${transaction.tx_hash}`} target="_blank" rel="noreferrer">View transaction <ArrowUpRight size={16} /></a>
      {transaction.error && !['failed', 'expired'].includes(payment.status) && <p className="reason-note">Network response: {transaction.error}</p>}
      {receipt && <><dl className="intent-fields"><div><dt>Finalized block</dt><dd>{receipt.block_number}</dd></div><div><dt>Transaction index</dt><dd>{receipt.extrinsic_index}</dd></div><div><dt>Actual network fee</dt><dd>{receipt.fee_units ? `${amount(receipt.fee_units)} tVFY` : 'Unavailable in chain events'}</dd></div></dl><Button secondary onClick={() => download({ payment_id: payment.id, purpose: payment.purpose, approval_hash: payment.approval_hash, ...receipt }, `${payment.id}-receipt.json`)}><DownloadSimple size={17} />Download receipt</Button></>}
      {['submitting', 'submitted'].includes(payment.status) && <Button secondary busy={busy} onClick={() => mutate(refresh, 'Payment status refreshed.')}><ArrowClockwise size={17} />Check status</Button>}
    </div>}
    {data.proofs_available && (quote || transaction || payment.policy_proof) && <div className="export-area"><h2>Payment policy proof</h2><p>Verify recipient permission and the amount against a committed policy snapshot. This proof is separate from transfer confirmation.</p>
      {payment.policy_proof ? <><code className="break">{payment.policy_proof.reference}</code><p>Locally verified FFLONK proof. A zkVerify proof transaction has not been submitted.</p><Button secondary onClick={() => download(payment.policy_proof, `${payment.id}-policy-proof.json`)}><DownloadSimple size={17} />Download proof</Button></> : <Button secondary busy={busy} onClick={() => mutate(() => request(`/v1/operator/payments/${payment.id}/proof`, 'POST', { expected_hash: payment.approval_hash }), 'Policy proof generated and locally verified.')} >Generate policy proof</Button>}
    </div>}
  </section></>;
}
