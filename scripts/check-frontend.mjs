/** Browser verification against an empty, normal operator gateway and a test wallet provider. */
import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { blake2AsU8a, cryptoWaitReady, sr25519PairFromSeed, sr25519Sign, encodeAddress } from '@polkadot/util-crypto';
import { u8aToHex, hexToU8a, u8aWrapBytes } from '@polkadot/util';

const origin = 'http://127.0.0.1:9797';
await mkdir('.cache', { recursive: true });
await mkdir('artifacts/ui', { recursive: true });
const directory = await mkdtemp(resolve('.cache/ui-verify-'));
const gateway = spawn('python', ['-m', 'tavrel', '--data-dir', directory, 'serve', '--port', '9797', '--quiet'], { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
let output = '';
let startupError = '';
gateway.stdout.on('data', bytes => { output += bytes.toString(); });
gateway.stderr.on('data', bytes => { startupError += bytes.toString(); });
let browser;
async function verify() {
try {
  for (let attempt = 0; attempt < 450 && gateway.exitCode === null && !output.includes('Native Volta payments enabled.'); attempt++) await new Promise(resolve => setTimeout(resolve, 100));
  if (!output.includes('Native Volta payments enabled.')) throw new Error('The clean gateway did not become ready: ' + startupError + output);
  await cryptoWaitReady();
  const pair = sr25519PairFromSeed(blake2AsU8a('Tavrel browser verification fixture only'));
  const address = encodeAddress(pair.publicKey, 251);
  browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  const errors = []; const badResponses = [];
  let policyProofReference = null;
  let invoiceRun = null;
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => { if (response.status() >= 400 && !response.url().includes('/v1/auth/')) badResponses.push({ status: response.status(), path: new URL(response.url()).pathname }); });
  await page.exposeFunction('tavrelFixtureSign', data => ({ signature: u8aToHex(sr25519Sign(u8aWrapBytes(hexToU8a(data)), pair)) }));
  await page.addInitScript(({ address }) => {
    window.unselectedWalletRequests = 0;
    window.wrongWalletMethodRequests = 0;
    window.walletVerificationMode = 'normal';
    const provider = () => ({
      accounts: { get: async () => [{ address, name: 'Verification wallet', type: 'sr25519' }] },
      signer: { signRaw: ({ data }) => window.walletVerificationMode === 'signature-pending'
        ? new Promise(resolve => { window.finishLateSignature = () => window.tavrelFixtureSign(data).then(resolve); })
        : window.tavrelFixtureSign(data) },
    });
    window.injectedWeb3 = { 'subwallet-verification': { version: '1',
      enable: async (name, options) => {
        if (name !== 'Tavrel' || options?.accountAuthType !== 'substrate') throw new Error('SubWallet native account access was not requested.');
        return window.walletVerificationMode === 'permission-pending'
          ? new Promise(resolve => { window.finishLateAccess = () => resolve(provider()); }) : provider();
      },
      connect: () => { window.wrongWalletMethodRequests++; return new Promise(() => {}); },
    }, unselectedWallet: { enable: () => { window.unselectedWalletRequests++; return new Promise(() => {}); } } };
  }, { address });
  await page.goto(`${origin}/dashboard`);
  await page.getByRole('heading', { name: 'A clear view.' }).waitFor();
  if (await page.getByRole('link', { name: 'Manage allowance', exact: true }).count()) throw new Error('The removed Overview link remains.');
  if (await page.locator('dialog[open]').count()) throw new Error('Browsing opens an unwanted wallet modal.');
  if ((await page.locator('.big-amount').innerText()).trim() !== '—tVFY') throw new Error('Guest allowance is presented as account data.');
  await page.getByRole('button', { name: 'New agent', exact: true }).click();
  await page.getByRole('dialog', { name: 'Sign in with your wallet.' }).waitFor();
  const walletWidth = await page.locator('.wallet-modal').evaluate(dialog => dialog.getBoundingClientRect().width);
  if (walletWidth > 425) throw new Error('The wallet modal has not been made smaller.');
  if (await page.locator('.wallet-modal .first-wallet-note, .wallet-modal .wallet-login-note').count()) throw new Error('Removed wallet modal notes remain.');
  await page.getByRole('button', { name: 'Close dialog', exact: true }).click();
  for (const route of ['/agents', '/vendors', '/approvals', '/ledger', '/settings']) {
    await page.goto(origin + route);
    await page.getByRole('heading', { level: 1 }).waitFor();
    if (await page.locator('dialog[open]').count()) throw new Error('Browsing ' + route + ' requires a wallet.');
  }
  await page.getByRole('button', { name: 'Save allowance', exact: true }).click();
  await page.getByRole('dialog', { name: 'Sign in with your wallet.' }).waitFor();
  let verifyRequests = 0;
  page.on('request', incoming => { if (new URL(incoming.url()).pathname === '/v1/auth/verify') verifyRequests++; });
  await page.evaluate(() => { window.walletVerificationMode = 'permission-pending'; });
  await page.getByRole('dialog', { name: 'Sign in with your wallet.' }).getByRole('button', { name: 'Connect wallet', exact: true }).click();
  await page.getByRole('button', { name: 'SubWallet', exact: true }).click();
  await page.locator('.wallet-pending').getByText('Open your wallet extension', { exact: false }).waitFor();
  await page.getByRole('button', { name: 'Cancel connection', exact: true }).click();
  await page.evaluate(() => { window.finishLateAccess(); window.walletVerificationMode = 'signature-pending'; });
  await page.getByRole('dialog', { name: 'Sign in with your wallet.' }).getByRole('button', { name: 'Connect wallet', exact: true }).click();
  await page.getByRole('button', { name: 'SubWallet', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm in your wallet', exact: false }).waitFor();
  await page.getByRole('button', { name: 'Close dialog', exact: true }).click();
  await page.evaluate(async () => { await window.finishLateSignature(); window.walletVerificationMode = 'normal'; });
  if (verifyRequests !== 0) throw new Error('A cancelled wallet request was verified.');
  const afterCancel = await page.evaluate(async () => (await (await fetch('/v1/auth/status')).json()).result);
  if (afterCancel.authenticated || afterCancel.configured) throw new Error('Cancelled extension replies registered or signed in a wallet.');
  await page.getByRole('button', { name: 'Save allowance', exact: true }).click();
  await page.getByRole('dialog', { name: 'Sign in with your wallet.' }).waitFor();
  const connectionStarted = Date.now();
  await page.getByRole('dialog', { name: 'Sign in with your wallet.' }).getByRole('button', { name: 'Connect wallet', exact: true }).click();
  await page.getByRole('button', { name: 'SubWallet', exact: true }).click();
  await page.getByRole('dialog', { name: 'Sign in with your wallet.' }).waitFor({ state: 'hidden' });
  const connectionMilliseconds = Date.now() - connectionStarted;
  await page.getByRole('button', { name: 'Refresh wallet balance', exact: true }).filter({ hasText: '0 tVFY' }).waitFor({ timeout: 60000 });
  if ((await page.locator('.wallet-balance-pill').boundingBox()).height > 42) throw new Error('Wallet balance is not a compact pill.');
  if (!(await page.locator('.app-label small').getAttribute('title')).startsWith('x')) throw new Error('Signed-in wallet is not displayed in Volta SS58 format.');
  process.stdout.write(`First wallet verified without a setup link in ${connectionMilliseconds}ms.\n`);
  if (await page.evaluate(() => window.unselectedWalletRequests) !== 0) throw new Error('An unselected wallet was asked to connect.');
  if (await page.evaluate(() => window.wrongWalletMethodRequests) !== 0) throw new Error('The generic connect method was called for SubWallet.');
  if (process.env.TAVREL_WALLET_UI_ONLY === '1') {
    if (verifyRequests !== 1 || errors.length || badResponses.length) throw new Error('Wallet-only verification failed.');
    await writeFile('artifacts/ui/wallet-connection-proof.json', JSON.stringify({
      observed_at: new Date().toISOString(), real_gateway: true, isolated_empty_ledger: true,
      provider: 'Controlled SubWallet-compatible native interface with actual sr25519 signatures',
      installed_extension_tested: false, subwallet_native_enable_requested: true,
      unselected_wallet_requests: 0, cancelled_authorization_ignored: true, cancelled_signature_ignored: true,
      cancelled_requests_did_not_register_wallet: true, retry_after_cancel: true,
      successful_verification_requests: verifyRequests, connection_milliseconds: connectionMilliseconds,
      wallet_balance_pill: true, volta_address_display: true, page_errors: errors,
      signed_transfer: false, submitted_transfer: false,
    }, null, 2) + '\n');
    process.stdout.write('Wallet cancellation, late replies, explicit retry, and real signature login passed.\n');
    return;
  }
  if (page.url().includes('setup=')) throw new Error('Wallet registration still depends on a setup link.');
  await page.getByRole('link', { name: 'Overview', exact: true }).click();
  await page.getByRole('heading', { name: 'A clear view.' }).waitFor();
  if (await page.getByText('Demo mode', { exact: true }).count()) throw new Error('A production demo mode is visible.');
  await page.reload();
  await page.getByRole('heading', { name: 'A clear view.' }).waitFor();
  await page.getByRole('link', { name: 'Settings', exact: true }).click();
  await page.getByLabel('Account allowance (tVFY)', { exact: true }).fill('10');
  await page.getByRole('button', { name: 'Save allowance', exact: true }).click();
  await page.getByRole('status').filter({ hasText: 'Account allowance updated.' }).waitFor();
  await page.getByRole('link', { name: 'Agents', exact: true }).click();
  await page.getByRole('button', { name: 'New agent', exact: true }).click();
  await page.getByLabel('Agent name', { exact: true }).fill('Research assistant');
  await page.getByLabel('What will it do?', { exact: true }).fill('Prepare service invoices with defined payment limits.');
  await page.getByRole('button', { name: 'Create agent', exact: false }).click();
  await page.getByRole('heading', { name: 'The boundaries.' }).waitFor();
  const expectedSender = address;
  if (await page.getByLabel('Sender address', { exact: true }).inputValue() !== expectedSender) throw new Error('A new agent does not default to the connected sending wallet.');
  await page.getByLabel('Sender address', { exact: true }).fill('0x' + '34'.repeat(32));
  await page.getByRole('button', { name: 'Use connected wallet', exact: true }).click();
  if (await page.getByLabel('Sender address', { exact: true }).inputValue() !== expectedSender) throw new Error('The connected-wallet shortcut does not restore the sender.');
  await page.getByLabel('Task allowance (tVFY)', { exact: true }).fill('10');
  await page.getByLabel('Per-payment cap (tVFY)', { exact: true }).fill('7');
  await page.getByLabel('Approval above (tVFY)', { exact: true }).fill('3');
  await page.getByRole('button', { name: 'Add recipient', exact: false }).click();
  await page.getByLabel('Recipient 1 name', { exact: true }).fill('compute_vendor');
  await page.getByLabel('Public address', { exact: true }).fill('0x' + '12'.repeat(32));
  await page.getByRole('button', { name: 'Save policy', exact: false }).click();
  await page.getByRole('status').filter({ hasText: 'Policy saved.' }).waitFor();
  await page.getByRole('link', { name: 'Research assistant', exact: true }).click();
  await page.getByRole('button', { name: 'Agent connection', exact: true }).click();
  const connectionDownload = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Create and download', exact: true }).click();
  const connection = JSON.parse(await readFile(await (await connectionDownload).path(), 'utf8'));
  const connectedAgent = await page.request.get(`${origin}/v1/agent/payments/status`, { headers: { Authorization: 'Bearer ' + connection.task_token } });
  if (connectedAgent.status() !== 200) throw new Error('Downloaded agent connection cannot read its restricted payment status.');
  await page.getByRole('button', { name: 'Prepare payment', exact: false }).click();
  await page.getByLabel('Amount (tVFY)', { exact: true }).fill('6');
  await page.getByLabel('Payment purpose', { exact: true }).fill('Compute service invoice');
  await page.getByRole('button', { name: 'Check payment', exact: false }).click();
  await page.getByText('Review fingerprint', { exact: true }).waitFor();
  if (await page.getByRole('button', { name: 'Approve request', exact: false }).isEnabled()) throw new Error('Approval was enabled before exact-intent review.');
  await page.locator('.payment-detail').screenshot({ path: 'artifacts/ui/payment-review.png' });
  await page.getByLabel('I have reviewed the amount, recipient, network, and payment rules.', { exact: true }).check();
  await page.getByRole('button', { name: 'Approve request', exact: false }).click();
  await page.getByText('Ready to send', { exact: true }).waitFor();
  await page.getByLabel('I have reviewed the amount, recipient, network, and payment rules.', { exact: true }).check();
  await page.getByRole('button', { name: 'Review fees', exact: false }).click();
  await page.getByRole('heading', { name: 'Send this payment' }).waitFor({ timeout: 60000 }).catch(async error => {
    const feedback = await page.locator('.feedback.error').allTextContents();
    await page.screenshot({ path: resolve('.cache/ui-fee-review-failure.png'), fullPage: true });
    throw new Error('Fee review did not complete: ' + feedback.join(' | ') + '. ' + error.message);
  });
  if (await page.getByRole('button', { name: 'Sign and send', exact: false }).isEnabled()) throw new Error('An unfunded test account can send through the UI.');
  await page.locator('.payment-detail').screenshot({ path: 'artifacts/ui/payment-fee-review.png' });
  if (await page.getByRole('button', { name: 'Generate policy proof', exact: true }).count()) {
    await page.getByRole('button', { name: 'Generate policy proof', exact: true }).click();
    await page.getByRole('button', { name: 'Download proof', exact: true }).waitFor({ timeout: 260000 }).catch(async error => {
      const feedback = await page.locator('.feedback.error').allTextContents();
      throw new Error('Policy proof did not complete: ' + feedback.join(' | ') + '. ' + error.message);
    });
    const proofDownload = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Download proof', exact: true }).click();
    const proofPath = await (await proofDownload).path();
    const proof = JSON.parse(await readFile(proofPath, 'utf8'));
    const verifier = spawn(process.execPath, ['scripts/verify-policy-proof.mjs', proofPath], { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    let verifyOutput = ''; let verifyErrors = '';
    verifier.stdout.on('data', bytes => { verifyOutput += bytes; });
    verifier.stderr.on('data', bytes => { verifyErrors += bytes; });
    const verifiedCode = await new Promise((resolve, reject) => { verifier.on('exit', resolve); verifier.on('error', reject); });
    if (verifiedCode !== 0 || JSON.parse(verifyOutput).valid !== true) throw new Error('Downloaded proof verification failed: ' + verifyErrors);
    policyProofReference = proof.reference;
  }
  await page.getByRole('link', { name: 'Ledger', exact: true }).click();
  await page.getByRole('heading', { name: 'The payment ledger.' }).waitFor();
  await page.locator('.panel').screenshot({ path: 'artifacts/ui/ledger.png' });
  const status = await page.evaluate(async () => (await (await fetch('/v1/operator/payments/status')).json()).result);
  if (status.account.reserved_units !== '6000000000000000000' || status.settled_units !== '0') throw new Error('The UI flow changed settlement/hold accounting incorrectly.');
  await page.getByRole('link', { name: 'Overview', exact: true }).click();
  await page.screenshot({ path: 'artifacts/ui/dashboard.png', fullPage: true });
  await page.goto(`${origin}/agents/${connection.task_id}`);
  await page.getByRole('heading', { name: 'Give your agent a task' }).waitFor();
  await page.getByRole('button', { name: 'Create agent wallet', exact: true }).click();
  await page.getByLabel('Agent wallet address', { exact: true }).waitFor();
  if (!(await page.getByLabel('Agent wallet address', { exact: true }).inputValue()).startsWith('x')) throw new Error('Generated wallet address is not in Volta format.');
  if (await page.getByRole('button', { name: 'Enable automatic signing', exact: true }).isEnabled()) throw new Error('An unreviewed or mismatched wallet can enable signing.');
  {
    await page.getByLabel('Payment task name', { exact: true }).fill('Browser invoice task');
    await page.getByLabel('Invoice 1 reference', { exact: true }).fill('UI-001');
    await page.getByLabel('Invoice 1 recipient', { exact: true }).fill('compute_vendor');
    await page.getByLabel('Invoice 1 amount (tVFY)', { exact: true }).fill('0.005');
    await page.getByLabel('Invoice 1 purpose', { exact: true }).fill('Invoice from browser');
    await page.getByRole('button', { name: 'Start task', exact: true }).click();
    await page.getByText('Invoices are prepared. Eligible payments use automatic signing when enabled; review the other requests below.', { exact: true }).waitFor({ timeout: 15000 });
    const response = await page.request.get(`${origin}/v1/operator/tasks/${connection.task_id}/runs`);
    invoiceRun = (await response.json()).result.runs[0];
    if (invoiceRun.status !== 'completed' || invoiceRun.payments[0]?.amount !== '0.005' || invoiceRun.payments[0]?.broadcast) throw new Error('Invoice task did not prepare the expected real ledger request.');
  }
  await page.screenshot({ path: 'artifacts/ui/agent-tasks.png', fullPage: true });
  await page.goto(origin);
  await page.getByRole('heading', { level: 1 }).waitFor();
  const faucetLink = page.locator('footer').getByRole('link', { name: 'Get test tokens', exact: false });
  if (await faucetLink.getAttribute('href') !== 'https://www.faucy.com/zkverify-volta') throw new Error('The footer faucet link is missing or points to another network.');
  if (await page.locator('.landing-nav').getByText('Launch app', { exact: true }).count()) throw new Error('The top Launch app link remains.');
  for (const text of ['Agent-led preparation.', 'Exact-intent review', 'Durable decision history', 'Retries reuse the same intent']) {
    if (await page.getByText(text, { exact: true }).count()) throw new Error('Removed text remains: ' + text);
  }
  const navWidth = await page.locator('.landing-nav nav').evaluate(nav => nav.getBoundingClientRect().width);
  if (navWidth < 330) throw new Error('The desktop navigation has not been widened: ' + navWidth + 'px.');
  for (const section of await page.locator('.landing section').all()) await section.scrollIntoViewIfNeeded();
  // Lazy images begin loading after entering the viewport. Wait for decoding
  // before judging their rendered state, including images above the last section.
  for (const img of await page.locator('.landing img').all()) {
    await img.scrollIntoViewIfNeeded();
    await page.waitForFunction(element => element.complete && element.naturalWidth > 0,
      await img.elementHandle(), { timeout: 15000 });
    await img.evaluate(element => element.decode());
  }
  const images = await page.locator('img').evaluateAll(images => images.map(image => ({ src: new URL(image.src).pathname, loaded: image.complete && image.naturalWidth > 0 })));
  if (images.some(image => !image.loaded)) throw new Error('An image failed to render: ' + JSON.stringify(images));
  if (await page.locator('input[type="range"]').count()) throw new Error('The landing slider is still interactive.');
  if (await page.getByText('Explore approvals', { exact: true }).count()) throw new Error('The removed approval CTA is still present.');
  await page.screenshot({ path: 'artifacts/ui/landing-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(origin);
  for (const section of await page.locator('.landing section').all()) await section.scrollIntoViewIfNeeded();
  if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)) throw new Error('Mobile landing overflows horizontally.');
  await page.screenshot({ path: 'artifacts/ui/landing-mobile.png', fullPage: true });
  for (const width of [320, 375, 768]) {
    await page.setViewportSize({ width, height: 844 });
    const overlap = await page.locator('.landing-nav').evaluate(header => {
      const brand = header.querySelector('.brand').getBoundingClientRect();
      const nav = header.querySelector('nav').getBoundingClientRect();
      return brand.right > nav.left || nav.right > innerWidth - 8;
    });
    if (overlap) throw new Error('Navigation overlaps at width ' + width);
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)) throw new Error('Landing overflows at width ' + width);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${origin}/docs`);
  await page.getByRole('heading', { name: 'Payments, with clear rules.' }).waitFor();
  const documentationSections = await page.locator('main section').count();
  if (documentationSections !== 12) throw new Error('Detailed documentation is missing.');
  if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)) throw new Error('Mobile documentation overflows.');
  await page.screenshot({ path: 'artifacts/ui/docs-mobile.png', fullPage: true });
  await page.goto(`${origin}/dashboard`);
  await page.getByRole('heading', { name: 'A clear view.' }).waitFor();
  if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)) throw new Error('Mobile app overflows horizontally.');
  await page.screenshot({ path: 'artifacts/ui/dashboard-mobile.png', fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole('button', { name: 'Disconnect', exact: true }).click();
  await page.getByRole('button', { name: 'Connect wallet', exact: true }).waitFor();
  if (await page.locator('dialog[open]').count()) throw new Error('Logout blocks app browsing.');
  if (await page.getByRole('link', { name: 'Status', exact: true }).count()) throw new Error('The removed Status page remains in navigation.');
  if (await page.getByRole('navigation', { name: 'App navigation' }).getByRole('link', { name: 'Docs', exact: true }).count()) throw new Error('Docs remains inside the app sidebar.');
  for (const text of ['Explore the app', 'Control center']) {
    if (await page.getByText(text, { exact: true }).count()) throw new Error('Removed app text remains: ' + text);
  }
  const loggedOut = (await page.request.get(`${origin}/v1/operator/payments/status`)).status();
  if (loggedOut !== 401) throw new Error('Logout failed to revoke the operator session.');
  await page.getByRole('button', { name: 'New agent', exact: true }).click();
  await page.getByRole('dialog', { name: 'Sign in with your wallet.' }).waitFor();
  await page.screenshot({ path: 'artifacts/ui/wallet-login.png', fullPage: true });
  if (errors.length || badResponses.length) throw new Error(JSON.stringify({ errors, badResponses }));
  await writeFile('artifacts/ui/frontend-proof.json', JSON.stringify({ real_gateway: true, starts_empty: true, production_demo_mode: false,
    wallet_provider: 'Injected test fixture, native sr25519 signature verified by the server',
    live_browser_wallet_tested: false, native_signature_verified: true, session_survived_reload: true, logout_revoked_session: true,
    first_wallet_connected_without_setup_link: true, unselected_wallet_requests: 0, connection_milliseconds: connectionMilliseconds,
    subwallet_native_enable_requested: true, cancelled_authorization_ignored: true, cancelled_signature_ignored: true, cancelled_requests_did_not_register_wallet: true, retry_after_cancel: true,
    policy_saved: true, sender_defaults_to_connected_wallet: true, connected_sender_shortcut: true, wallet_balance_pill: true, volta_address_display: true, generated_agent_wallet: true, automatic_signing_requires_reviewed_matching_sender: true, deterministic_invoice_run: { id: invoiceRun.id, executor: invoiceRun.executor, actions: invoiceRun.actions.map(action => action.name), status: invoiceRun.status }, llm_calls: false, payment_prepared: true, exact_review_required: true, approval: true, live_fee_review: true, insufficient_funds_prevents_signing: true,
    agent_connection_download_verified: true, policy_proof_reference: policyProofReference, downloaded_policy_proof_verified: !!policyProofReference,
    transfer_signed: false, transfer_submitted: false, held_units: status.account.reserved_units, settled_units: status.settled_units,
    landing_images: images, footer_test_token_link: 'https://www.faucy.com/zkverify-volta', static_policy_slider: true, top_launch_link_removed: true, desktop_nav_width: navWidth,
    browse_without_wallet: true, operations_prompt_wallet: true, status_page_replaced_by_docs: true,
    documentation_sections: documentationSections, wallet_modal_width: walletWidth, wallet_modal_notes_removed: true,
    overview_manage_link_removed: true, responsive: [1440, 768, 390, 375, 320], page_errors: errors,
    signing_transfer: false, broadcast: false }, null, 2) + '\n');
  process.stdout.write('Wallet login, persistent session, empty-account setup, policy, payment approval/real fee review, images, and mobile layout passed.\n');
} catch (error) {
  if (browser) {
    const failedPage = browser.contexts()[0]?.pages()[0];
    if (failedPage) {
      const feedback = await failedPage.locator('.feedback, [role="alert"]').allTextContents();
      process.stderr.write('Browser feedback: ' + feedback.join(' | ') + '\n');
      await failedPage.screenshot({ path: resolve('.cache/ui-last-failure.png'), fullPage: true });
    }
  }
  throw error;
} finally { if (browser) await browser.close(); gateway.kill('SIGINT'); }
}
await verify();
