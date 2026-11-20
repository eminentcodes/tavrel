export async function request(path, method = 'GET', body) {
  const response = await fetch(path, {
    method, redirect: 'error', cache: 'no-store', credentials: 'same-origin',
    headers: { ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    signal: AbortSignal.timeout(path.endsWith('/proof') ? 250_000 : path.endsWith('/quote') || path.endsWith('/submit') ? 55_000 : 15_000),
  });
  const value = await response.json();
  if (!response.ok || value.ok !== true) {
    const error = new Error(value.error?.message || 'The app could not complete this request.');
    error.status = response.status;
    throw error;
  }
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
