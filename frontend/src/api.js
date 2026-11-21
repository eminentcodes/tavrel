export async function request(path, method = 'GET', body, { signal, attempt = 0 } = {}) {
  signal?.throwIfAborted();
  const timeout = AbortSignal.timeout(path.endsWith('/proof') ? 250_000 : path.endsWith('/quote') || path.endsWith('/submit') || path.includes('/wallet/balance') ? 55_000 : 15_000);
  const response = await fetch(path, {
    method, redirect: 'error', cache: 'no-store', credentials: 'same-origin',
    headers: { ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
  });
  const raw = await response.text();
  let value;
  try { value = JSON.parse(raw); }
  catch {
    if (method === 'GET' && attempt === 0 && !raw.trim()) {
      return request(path, method, body, { signal, attempt: 1 });
    }
    const error = new Error('The app connection was interrupted. Try again now that the gateway is running.');
    error.status = response.status >= 400 ? response.status : 503;
    throw error;
  }
  if (!response.ok || !value || value.ok !== true) {
    const error = new Error(value?.error?.message || 'The app could not complete this request.');
    error.status = response.status;
    throw error;
  }
  signal?.throwIfAborted();
  return value.result;
}

export function amount(units = '0') {
  const value = BigInt(units);
  const whole = value / 10n ** 18n;
  const fraction = (value % (10n ** 18n)).toString().padStart(18, '0').replace(/0+$/, '');
  return `${whole}${fraction ? `.${fraction}` : ''}`;
}

export function download(value, filename) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2) + '\n'], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url; link.download = filename; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function paymentReason(reason) {
  return {
    RECIPIENT_NOT_ALLOWED: 'This recipient is not approved for this agent. Add their public address in the agent’s policy, save, then create a new payment request.',
    WORKSPACE_PAYMENT_BUDGET: 'The shared account allowance cannot cover this payment. Set an account allowance in Settings, then create a new payment request. Wallet tokens and app allowances are separate.',
    TASK_PAYMENT_BUDGET: 'This agent has insufficient allowance available. Check its limit and existing payment holds before creating a new request.',
    PER_PAYMENT_LIMIT: 'This amount exceeds the agent’s per-payment limit. Check its policy before creating a new request.',
    TASK_PAUSED: 'This agent is paused. Resume it before creating a new payment request.',
    POLICY_CHANGED_REVIEW_AGAIN: 'The payment rules changed. Review the updated request before approving it.',
  }[reason] || reason?.replaceAll('_', ' ').toLowerCase();
}

export function allowanceAboveBalance(value, balance) {
  if (!balance || !/^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,18})?$/.test(value)) return false;
  const [whole, fraction = ''] = value.split('.');
  return BigInt(whole) * 10n ** 18n + BigInt(fraction.padEnd(18, '0')) > BigInt(balance.free_units);
}
