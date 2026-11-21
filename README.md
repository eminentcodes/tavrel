<p align="center"><img src="frontend/public/tavrel-mark.svg" width="58" alt="Tavrel logo" /></p>
<h1 align="center">Tavrel</h1>
<p align="center">Agentic payments. On your terms.</p>

**Tavrel is an agent payment app.** Give your agent exact invoice details. It checks recipients and spending limits, prepares each payment, and follows its outcome. Sign transfers in your wallet, or authorize a separate agent wallet to sign eligible payments automatically. Tavrel sends them on **zkVerify Volta** and checks finalized confirmation.

The app brings agents, recipients, approvals, and payment receipts into one place. You can browse before connecting a wallet; account operations ask you to sign in. Normal startup uses real APIs and starts with empty account data.

## Table of contents

- [The problem](#the-problem)
- [What we built](#what-we-built)
- [How it works](#how-it-works)
- [Judge Guide](#judge-guide)
- [Getting started](#getting-started)
- [Deploying on Railway](#deploying-on-railway)
- [Connecting an agent](#connecting-an-agent)
- [Invoice tasks](#invoice-tasks)
- [Automatic agent-wallet payments](#automatic-agent-wallet-payments)
- [zkVerify and test tokens](#zkverify-and-test-tokens)
- [Optional policy proof](#optional-policy-proof)
- [Architecture](#architecture)
- [Tests and evidence](#tests-and-evidence)
- [Capabilities and limits](#capabilities-and-limits)
- [Project context and references](#project-context-and-references)

## The problem

AI agents can request compute, data, and other services faster than a person can review each invoice. A wrong address, an amount outside the budget, or a retry of the same invoice can cause an expensive mistake.

Tavrel is for developers and small teams delegating payment tasks to agents. The agent handles the instructions and follows payment progress. Deterministic code checks recipients and spending limits, while the person controls wallet signatures.

For example, a team gives an agent **0.1 tVFY**, permits one service recipient, caps each payment at **0.03 tVFY**, and asks for review above **0.01 tVFY**. A **0.005 tVFY** invoice is ready to send. A **0.02 tVFY** invoice needs approval. An unknown recipient is blocked. Retrying the same invoice returns its existing request, including its eventual receipt.

These examples use the sponsor's native test token. They demonstrate payment controls, rather than stablecoin purchasing or a commercial service integration.

## What we built

| Part | Behavior |
| --- | --- |
| Agents | A sender wallet, allowance, cap, approval threshold, approved recipients, pause/resume, and restricted API connection. |
| Invoice task runner | Submit real invoice instructions, report decisions, link requests for review, and watch payment status. |
| Invoice tasks | Process 1–20 exact invoices with durable activity, recipient/allowance decisions, cancellation, and safe resume. |
| Agent wallet | Generate a separate encrypted signing key; authorize a policy version and expiry for automatic eligible transfers. |
| Rules engine | Exact 18-decimal amounts, atomic account/agent reservations, recipient checks, policy version checks, and stable retry keys. |
| Approvals | Review the exact payment. Approval cannot bypass a budget or recipient rule. |
| Wallet access | Server-verified Substrate signed-message login and revocable sessions. |
| Payment execution | Live balance/fee review, wallet transfer signatures, cryptographic payload validation, durable native submission, and recovery. |
| Settlement | Scan finalized blocks and match the transaction, sender, recipient, amount, success, and transfer event. |
| Receipts | Explorer links and downloadable payment evidence with finalized block and transaction index. |
| Optional proof | Generate a real FFLONK artifact for recipient membership and amount limits against a committed policy snapshot. |

<p align="center"><img src="frontend/public/payment-preview.png" width="640" alt="Tavrel payment review" /></p>
<p align="center"><sub>Product preview captured from the app with an isolated test account; it is not evidence of a live transfer.</sub></p>

## How it works

1. Set the shared account allowance and the agent's sender, recipients, cap, and review threshold.
2. Name a payment task and enter each invoice's reference, recipient, exact amount, and purpose. The agent validates the entire input before preparing any request.
3. Tavrel checks the rules. An eligible request reserves its principal; a prohibited request is recorded as blocked.
4. Approve qualifying requests after reviewing their exact details. Rules are checked again if they change.
5. The app checks the real network fee and balance. Your wallet signs the native transfer, or a separately authorized agent wallet signs an eligible request automatically.
6. Tavrel verifies the signature and saves the signed transaction before submitting it. Recovery reuses those signed bytes.
7. A matching successful transfer in a finalized block moves principal from reserved to spent. The request receives a downloadable receipt.

```mermaid
sequenceDiagram
    participant Agent
    participant Tavrel
    participant Person
    participant Wallet
    participant Volta as zkVerify Volta
    Agent->>Tavrel: Invoice and stable request key
    Tavrel->>Tavrel: Check rules and reserve principal
    Tavrel-->>Person: Exact payment review
    Person->>Tavrel: Approve if required; request fee review
    Tavrel->>Volta: Read balance, fee, nonce, finalized head
    Person->>Wallet: Sign reviewed transfer
    Wallet-->>Tavrel: Signature
    Tavrel->>Tavrel: Verify and persist signed transaction
    Tavrel->>Volta: Submit identical signed bytes
    Tavrel->>Volta: Check finalized block and transfer events
    Tavrel-->>Agent: Confirmed payment and receipt
```

The shared and agent allowances track **principal**, with available allowance equal to limit minus confirmed principal minus active reservations. Network fees are paid separately by the sender. Allowances are not deposits or wallet balances.

## Judge Guide

This guide exercises the actual application and includes the agent's role. Wallet signing is a deliberate user action. Automated test fixtures are described separately under [Tests and evidence](#tests-and-evidence).

### 1. Start the app and connect your wallet

Follow [Getting started](#getting-started). Open `http://127.0.0.1:8787` and choose **Launch app**. Browsing works before connecting.

Open the app, choose **Connect wallet**, select **SubWallet**, **Talisman**, or the **Polkadot extension**, and sign the login message with a Substrate account. Your first verified wallet becomes the account owner. Subsequent sign-ins use that wallet; no terminal setup link is needed.

Claim tVFY for the intended **sender** using the [Volta faucet](https://www.faucy.com/zkverify-volta). The sender needs funds for the amount, fee, and account minimum. Login alone needs no tokens.

### 2. Configure a small payment task

- In **Settings**, set the account allowance to `0.1` tVFY.
- In **Agents**, create **Invoice assistant**.
- Use your funded wallet's public Substrate address as the sender.
- Set agent allowance `0.1`, per-payment cap `0.03`, and approval above `0.01`.
- Add `service_vendor` with a second Substrate account's public address. Use an account you control for testing.

### 3. See the agent in action

Open **Invoice assistant**. Under **Give your agent a task**, name the task **Service invoices** and fill in the first invoice. Choose **Add invoice** for the second:

| Reference | Recipient | Amount (tVFY) | Purpose |
| --- | --- | --- | --- |
| `INV-001` | `service_vendor` | `0.005` | First service invoice |
| `INV-002` | `service_vendor` | `0.02` | Compute invoice requiring review |

Choose **Start task**. The agent checks the payment rules, reads the invoices, and prepares each request. The activity and links come from the actual ledger. A missing or invalid field is rejected before any invoice is prepared. No model setup or API key is required.

Expected result: the first invoice is **Ready to send**; the second **Needs approval**. This reserves `0.025` tVFY in principal across the two invoices.

### 4. Complete a real payment

Open the first request. Review the details, tick the confirmation box, and choose **Review fees**. Check the current transferable balance and estimated fee, then choose **Sign and send** and confirm the transfer in your wallet.

Expected progression: **Sending → Awaiting confirmation → Confirmed**. Finality can take time. Keep the server running; the page may be closed and reopened.

Open **View transaction** and compare the sender, recipient, amount, and finalized block. **Download receipt** exports the evidence. The confirmed principal moves from reserved to spent exactly once.

### 5. Check approval, blocking, and retries

- Open the second invoice through **Approvals**, review it, and approve or deny it. Approval makes it eligible for wallet signing; denial releases its hold.
- Try a payment of `0.031` to `service_vendor`: it must be blocked by the cap.
- Try a payment to a checksum-valid address absent from the recipient list: it must be blocked before signing.
- Submit another task with the same invoice references and details: it returns the existing payment IDs and does not prepare duplicate payments.
- Change an amount under the same key: Tavrel rejects the conflict.
- Change rules before signing an older request: its previous review cannot authorize a changed policy version.

### 6. Inspect evidence and the optional proof

Use the ledger, explorer links, and downloaded receipts. A node's submission response alone is not settlement evidence.

If the optional proving artifacts have been built, choose **Generate policy proof** after fee review. Download and verify that artifact using [Optional policy proof](#optional-policy-proof). The app displays a real local proof reference; it does not invent an on-chain zkVerify proof transaction.

## Getting started

Requirements: **Python 3.11+**, **Node 24.22.1+**, npm, and a Substrate browser wallet for account actions. Node's version matches the requirement of `zkverifyjs@3.4.0`.

```bash
git clone https://github.com/eminentcodes/tavrel.git
cd tavrel
python -m pip install -e .
npm ci
npm run build
python -m tavrel serve
```

Open the printed address, normally `http://127.0.0.1:8787`. The build produces the frontend and bundled Node helpers. Runtime data lives in `.tavrel/`, which is excluded from Git. Use a different `--data-dir` for a separate installation.

First-wallet registration requires a same-origin browser request to the loopback app and a valid wallet signature. It cannot replace an existing account owner. The app requests access only from the selected extension. Sessions expire after 30 minutes, survive page reloads, and are revoked by Disconnect. Your connected wallet's private key stays in its extension.

If a wallet popup does not open, click the extension in your browser toolbar, unlock it, and check pending requests. SubWallet access requests use its native Substrate interface. Access and account-list requests time out after 45 seconds; the login-signature request times out after 90 seconds. Closing the modal stops the app from using late extension replies. Close any old pending wallet request before reconnecting; Tavrel does not automatically repeat signing or sign-in verification. The server warms and reuses its native signature verifier, and successful login returns the display address directly.

This command starts the local app. Use the hosted entrypoint below for Railway.

## Deploying on Railway

The repository includes a [Dockerfile](Dockerfile) and [Railway configuration](railway.json). Railway builds the frontend and bundled payment helpers, installs the Python app, and runs `python -m tavrel.hosted`. This avoids Railpack's Python auto-detection error, **No start command detected**. The frontend and API run together in one service.

1. Deploy the latest `main` from this repository with the repository root as the service root. Railway should use the **Dockerfile** builder. Remove any old build or start command overrides so it uses the Dockerfile commands.
2. Under **Networking**, generate a public HTTPS domain. Railway supplies `RAILWAY_PUBLIC_DOMAIN`; for a custom domain, set `TAVREL_PUBLIC_ORIGIN` to its full HTTPS origin, such as `https://payments.example.com`, without a path.
3. Add a persistent volume mounted at **`/data`**. Keep **one replica**: the SQLite ledger, login sessions, allowance reservations, and encrypted agent wallets belong to that volume.
4. Set these service variables, then redeploy:

| Variable | Value |
| --- | --- |
| `TAVREL_OWNER_WALLET` | The public Substrate address of the wallet you will connect. SS58 or a 32-byte public AccountId is accepted. |
| `TAVREL_DATA_DIR` | `/data`, matching the volume mount. |
| `TAVREL_WALLET_VAULT_KEY` | A stable Fernet encryption key for newly created automatic agent wallets. Generate it once using the command below. |
| `TAVREL_PUBLIC_ORIGIN` | Optional when using Railway's generated domain; required for a custom domain. |

Generate the vault key locally, then paste its output into Railway's private Variables settings:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep that key private and preserve it across deployments. Replacing it prevents existing agent wallets from decrypting. A Windows-created vault uses Windows profile encryption and cannot be moved to Linux merely by copying its files; create a separate hosted agent wallet instead.

Railway supplies `PORT`; the app listens on `0.0.0.0`. The configured health check is `/health`. Successful startup logs `Tavrel ready at https://YOUR_DOMAIN`. Open that domain and connect the wallet configured above. An existing ledger's owner cannot be replaced by changing the variable.

If Deploy Logs repeat **Set TAVREL_PUBLIC_ORIGIN to your HTTPS domain**, the image has built and the container is reaching Tavrel's startup. Under **Settings → Networking → Public Networking**, choose **Generate Domain**, targeting port **8080** unless you changed `PORT`. Copy the generated domain and set `TAVREL_PUBLIC_ORIGIN` to `https://` followed by that hostname in the service's **Variables** tab. For example, a generated hostname `tavrel-production-1234.up.railway.app` needs `https://tavrel-production-1234.up.railway.app`. Use your actual hostname, with no `/dashboard`, other path, or custom port. Apply the variable changes and redeploy. Railway's automatic `RAILWAY_PUBLIC_DOMAIN` also works when present; an explicitly set `TAVREL_PUBLIC_ORIGIN` takes precedence and must be valid.

Set `TAVREL_OWNER_WALLET` at the same time, using your public wallet address. Otherwise startup will next stop with **Set TAVREL_OWNER_WALLET**. No model API key is involved. Once startup succeeds, open `https://YOUR_DOMAIN/health`; it should return JSON with `status` equal to `ready`.

Each deployment has one account owner. Visitors and judges can browse the public routes; account operations require that owner's wallet. Judges can run their own local installation to test with their own wallet. The hosted app makes no LLM calls and needs no model API key.

The default image supports invoice tasks, wallet login, manual transfers, automatic agent wallets, and receipt tracking. Optional **policy proof generation** requires separate local proving setup and is not included in this image. The app hides unavailable proof actions; native tVFY payments remain independent of that optional proof.

Package and hosted authentication checks are linked under [Tests and evidence](#tests-and-evidence). A successful Railway deployment and a funded transfer still need to be observed on the deployed service.

## Connecting an agent

Choose **Agent connection → Create and download**. Keep the connection JSON private; creating it revokes the previous task token. Your own automation can use the task-scoped API, or run the included deterministic CLI with a JSON array containing `recipient`, `amount`, and `purpose`:

```bash
python -m tavrel.agent TASK_ID --connection TASK_ID-connection.json --file invoices.json --key invoice-batch --watch 600
```

The CLI reports each decision and follows payment status while you review requests. Reuse its task key and exact ordered file when retrying. UI invoice references and CLI batch keys identify their own requests; choose one submission route for an invoice rather than submitting it through both.

## Invoice tasks

The app agent validates 1–20 invoices, resolves approved recipient names to public accounts, checks the current rules, and prepares requests in order. Required details are explicit fields; it does not interpret natural-language instructions or invent missing information. Its durable activity records rule checks, invoice counts, each payment outcome, and completion.

Task-token clients can `POST /v1/agent/runs` with `goal` (a task name), `invoices`, and a stable `request_key`:

```json
{
  "goal": "Service invoices",
  "request_key": "service-invoices-november",
  "invoices": [
    {"invoice_reference":"INV-001","recipient":"service_vendor","amount":"0.005","purpose":"First service invoice"}
  ]
}
```

List/get scoped runs and use `/resume` or `/cancel`. The same reference within an agent identifies the same payment across app batches; changed details conflict rather than replacing that payment. Different references can identify separate invoices with equal amounts. A restarted or interrupted task requires explicit resume and reuses saved requests. Cancellation stops future invoice preparation; existing payments, holds, and automatic-wallet permissions still apply.

A blocked request remains history. After correcting rules, use a clearly revised reference such as `INV-001-retry2` to request a fresh review. Earlier model-task records remain under **Earlier tasks** and cannot execute again. The current app makes no model calls and has no model-provider configuration.

## Automatic agent-wallet payments

To pay without signing each transfer:

1. Open the agent and choose **Create agent wallet**.
2. Fund its displayed public address with tVFY using the faucet or a transfer you authorize.
3. Set that address as the sender in the agent's policy. Set recipients, principal allowance, cap, and approval threshold.
4. Review the estimated fee cap and permission duration, tick the authorization box, then choose **Enable automatic signing**.
5. Start an invoice task. Eligible payments are signed and submitted automatically; requests above the threshold still require your approval in the app.

Permission is bound to the reviewed policy version, expires after 1–168 hours, and can be disabled. A policy change or pause stops new automatic signing. Disabling does not cancel previously stored signed transactions or release payment holds; existing transaction recovery continues.

The app holds the **separate agent wallet's encrypted key**. Your connected wallet's private key remains in its extension. Limits are enforced by Tavrel's server, rather than ARCANUM-style smart contracts, so keep only the funds you intend to delegate in the agent wallet. Fees are paid separately; the fee cap checks the current estimate and cannot guarantee the final fee charged by the chain.

Windows uses profile-bound DPAPI to protect the encryption key. On other systems set `TAVREL_WALLET_VAULT_KEY` to a Fernet key in the server environment before creating wallets. Preserve the encrypted ledger and original vault key/profile; losing them loses access to agent-wallet funds. Never commit or pass the vault key to an agent.

| Method | Task-scoped endpoint | Purpose |
| --- | --- | --- |
| GET | `/v1/agent/payments/status` | Read this agent's allowance, policy, and requests. |
| POST | `/v1/agent/payments/prepare` | Prepare one invoice using recipient, amount, purpose, and request key. |
| POST | `/v1/agent/payments/task` | Submit an ordered task with a stable task key and 1–20 invoices. |
| GET | `/v1/agent/payments/PAYMENT_ID` | Follow the request and its eventual receipt. |
| POST / GET | `/v1/agent/runs` | Start or list exact invoice tasks. |
| GET | `/v1/agent/runs/RUN_ID` | Read durable activity and payment outcomes. |
| POST | `/v1/agent/runs/RUN_ID/resume` or `/cancel` | Resume an interrupted task or stop future invoice preparation. |

Authenticate using the connection file's task token in `Authorization: Bearer TOKEN`. The token is restricted to its own agent. Keep connection files outside version control; do not give an agent access to the server's data directory.

Agents cannot modify policies, approve payments, create wallet sessions, request signing quotes, or submit signatures. The person uses the app for those operations.

## zkVerify and test tokens

| Property | Value |
| --- | --- |
| Network | zkVerify Volta testnet |
| Asset | Native **tVFY**, 18 decimal places |
| Transfer | `balances.transferKeepAlive` |
| RPC | `https://volta-rpc.zkverify.io` for the server's native operations |
| WebSocket | `wss://volta-rpc.zkverify.io` / `wss://zkverify-volta-rpc.zkverify.io` |
| Genesis | `0xff7fe5a610f15fe7a0c52f94f86313fb7db7d3786e7f8acf2b66c11d5be7c242` |
| Explorer | [Volta Subscan](https://zkverify-testnet.subscan.io) |
| Faucet | [Faucy](https://www.faucy.com/zkverify-volta) |

tVFY is a **test token**, not a stablecoin. The build uses the sponsor's native chain for actual payment submission and finality checks, rather than adding an unrelated EVM network.

The faucet currently asks you to connect a wallet and complete a CAPTCHA. Its displayed claim amount and availability can change. Official guidance: [Getting testnet tokens](https://docs.zkverify.io/overview/getting-started/get_testnet_tokens).

## Optional policy proof

The checkable claim is: **this exact payment's recipient belongs to the committed approved-recipient tree, and its positive amount fits the committed per-payment cap and remaining account/agent allowances.**

The circuit binds that claim to the sender, recipient, exact amount, approval fingerprint, and Volta genesis hash. A single Poseidon public commitment fits zkVerify's FFLONK verifier. The recipient tree and allowance values remain private in the proof artifact. The optional circuit supports up to **eight approved recipients**; ordinary payment policies support larger lists.

The proof establishes those checks against the supplied commitment. It does not independently authenticate the server's policy snapshot, enforce wallet policy on chain, prove external service delivery, or prove that a transfer settled. Settlement has its own chain receipt.

Build the proving artifacts from the pinned public PSE ceremony file:

```bash
curl -fL https://pse-trusted-setup-ppot.s3.eu-central-1.amazonaws.com/pot28_0080/ppot_0080_16.ptau -o ppot_0080_16.ptau
npm run proof:setup -- ppot_0080_16.ptau
```

Setup checks the file's pinned SHA-256, compiles the circuit, and derives the FFLONK key from the published PSE ceremony. It relies on that published ceremony; checksum verification is not an independent cryptographic recheck of its transcript. Add `--verify-ceremony` to recheck the full ceremony, including its expensive beacon computation, which can take hours. The manifest records whether that recheck completed. Large setup files and generated keys are excluded from Git.

After generating a payment proof in the app, verify its downloaded JSON:

```bash
node scripts/verify-policy-proof.mjs PAYMENT_ID-policy-proof.json
```

Run `npm run proof:check` for actual proof generation, verification after JSON key reordering, and rejection of changed payment claims, proof data, and allowance overflows. These checks use isolated test instructions and make no chain calls.

Verification uses the public circuit key and manifest included in [proofs](proofs), and recomputes the public commitment and proof reference. Verifying a downloaded artifact does **not** require the large SRS or proving-key setup. A downloaded artifact's own `locally_verified` field is not trusted as verification.

The bundle's SHA-256 reference identifies the actual artifact. `zkverify_transaction` stays `null` until a real proof transaction is submitted and verified; no submission is claimed merely from local verification or native tVFY settlement.

## Architecture

| Source | Responsibility |
| --- | --- |
| [frontend/src](frontend/src) | Landing, public Docs, agent management, recipients, approvals, ledger, wallet review, and receipts. |
| [payments.py](tavrel/payments.py) | Exact units, budgets, reservation accounting, permissions, and review hashes. |
| [settlement.py](tavrel/settlement.py) | Signing quotes, durable transaction records, recovery, expiry, and finality accounting. |
| [native_rpc.mjs](tavrel/native_rpc.mjs) | Live metadata/balance/fee reads, signature inspection, native submission, finalized block/event scanning. |
| [auth.py](tavrel/auth.py) | Registered wallet ownership, expiring login challenges, replay prevention, and revocable sessions. |
| [agent.py](tavrel/agent.py) | Invoice task execution and status watching through restricted agent APIs. |
| [agent_runs.py](tavrel/agent_runs.py) | Deterministic invoice validation, durable action plans, scoped runs, and retry identities. |
| [wallet_verifier.py](tavrel/wallet_verifier.py) | Reuses native crypto for wallet login with bounded waits and independent request IDs. |
| [agent_wallets.py](tavrel/agent_wallets.py) | Separate encrypted wallets and explicit bounded automatic-signing permissions. |
| [server.py](tavrel/server.py) | App/API routes, authentication, origin checks, and reconciliation lifecycle. |
| [proofs](proofs) | Optional payment-policy circuit and witness/commitment construction. |
| [tests](tests) | Behavioral and cryptographic verification with isolated fixtures. |

Python and SQLite provide the authorization boundary. Amounts are decimal text in SQLite and Python integers during atomic transactions, so 18-decimal values do not overflow SQLite's signed integer range. The invoice agent executes a bounded saved action plan. Signing belongs either to the browser wallet or the separately authorized encrypted agent wallet. Node helpers use current chain metadata and cryptographic primitives.

The app routes are `/dashboard`, `/agents`, agent details/policies, `/vendors`, `/approvals`, `/ledger`, payment details, and `/settings`. `/docs` is public and linked from the landing navigation/footer.

## Tests and evidence

Run:

```bash
python -W error::ResourceWarning -m unittest discover -s tests
node --test tests/native-signing.test.mjs tests/wallet-connection.test.mjs tests/wallet-login.test.mjs tests/agent-wallet.test.mjs tests/api.test.mjs
npm run check:ui
node scripts/check-native-rpc.mjs
npm audit
```

The backend verification covers payment rules, wallet login, standalone invoice execution, proof snapshot caching, and recovery. Signature tests reject changes to the call, nonce, mortality, genesis, runtime versions, tip, and signer. Settlement tests cover identical retries, restart recovery, uncertain node responses, finalized success/failure, forged receipt rejection, expiry, and exact-once principal accounting. Current counts and timings are in the verification record.

After proof setup, run `node --test tests/policy-proof.test.mjs` to check the actual compiled circuit's constraints and `npm run proof:check` to exercise the full FFLONK pipeline.

| Evidence | What it establishes |
| --- | --- |
| [Verification record](artifacts/verification.md) | Commands, observed results, and their limits. |
| [Native RPC check](artifacts/native-rpc-check.json) | Real Volta fee/balance/nonce/finality reads and signing-payload preparation; no signing or submission. |
| [Sponsor SDK check](artifacts/zkverify-network-proof.json) | Live sponsor chain properties and an unsigned SCALE transfer round trip. |
| [Browser record](artifacts/ui/frontend-proof.json) | App browsing, wallet message authentication, policy/approval flow, images, and responsive layout; the file labels its test provider and network coverage. |
| [Settlement tests](tests/test_settlement.py) | Controlled RPC responses verify authorization, reservations, recovery, and receipt accounting. |
| [Cryptographic tests](tests/native-signing.test.mjs) | Offline signatures verify against stored public chain payloads. |
| [Wallet connection tests](tests/wallet-connection.test.mjs) | Selected native access, bounded waiting, retry after timeout/cancellation, unsupported account filtering, and exact payment payloads. |
| [Wallet login tests](tests/wallet-login.test.mjs) | Cancelled or timed-out signatures never reach verification; successful login signs the exact challenge once. |
| [Signature-worker tests](tests/test_wallet_verifier.py) | Actual signatures, changed claims, concurrent callers, worker recovery, and fail-closed timeouts. |
| [Hosted tests](tests/test_hosted.py) | HTTPS domain validation, Railway health checks, pinned wallet ownership, actual message signatures, and Secure login/logout cookies. |
| [Packaged hosted runtime](artifacts/railway-package-check.json) | Built wheel runs outside the source tree, serves frontend assets, verifies a real login signature, and derives an agent-wallet address using bundled helpers without runtime node_modules. Docker/Railway deployment remains unobserved. |
| [Latest wallet browser record](artifacts/ui/wallet-connection-proof.json) | Modal-close cancellation, ignored late replies, retry, actual native-signature login, and removal of Cancel connection. Live balance and installed extension speed are outside this focused check. |
| [Verifier timing record](artifacts/wallet-verifier-check.json) | Three cold and three reused native-verifier calls with an offline fixture; excludes extension and human signing time. Reproduce with `python scripts/check-wallet-verifier.py`. |
| [Invoice task tests](tests/test_agent_runs.py) | Input validation, exact ledger outcomes, scoped access, duplicate references, crash recovery, cancellation, recipient binding, and retained historical runs. |
| [Agent-wallet tests](tests/test_agent_wallets.py) | Encrypted keys, version/expiry/sender permissions, required approval, funding/fee checks, and revocation before durable transaction storage. |
| [Policy proof checks](artifacts/policy-proof-check.json) | Twelve actual FFLONK generation/verification cases, including altered claims and allowance overflows. |
| [Actual policy artifact](artifacts/payment-policy-proof.json) | A real locally verified proof from isolated test instructions; no on-chain proof or payment transaction. |

Tests do not spend funds. A funded installed-wallet transfer must be confirmed by its user and checked on the explorer before claiming an observed live settlement. Controlled test receipts and product screenshots are not live transaction evidence.

## Capabilities and limits

- Transfers use a user's Substrate wallet and native Volta tVFY. Stablecoins, contract wallets, swaps, and commercial x402 service purchasing are not implemented.
- Rules cover Tavrel's API. They do not constrain a wallet owner who sends directly elsewhere. Agents must be isolated from server credentials and files.
- Manual payments use the browser wallet. Optional automatic payments use a separate encrypted agent wallet after explicit permission.
- A saved signature stays bound to its reviewed call, nonce, network, and mortal era. Uncertain outcomes retain reservations until finalized success, failure, or verified expiry.
- Confirmed principal reduces the remaining allowance; fees are tracked separately when emitted by the chain.
- App invoice tasks and the deterministic CLI use the same payment ledger. Explicit invoice details drive execution; natural-language reasoning, external invoice fetching, and LLM calls are not included.
- Railway configuration and hosted authentication are implemented. Deployed-service behavior, hackathon submission, and funded-wallet settlement require their own observed results.

## Project context and references

Built for [Agent Games Wildcard](https://agentgames.zkverify.io/events/wildcard) under agentic payments. This entry focuses on the useful problem, a reviewable working workflow, clear capability boundaries, and optional checkable policy evidence.

Tavrel began as a task-spending prototype and was reworked into this standalone app. [ARCANUM](https://github.com/bunnyyxtan/ARCANUM), reviewed at commit `46d30739c675b54390061a2e39d52a30d447e41b`, informed the wallet access, policy, approval, ledger, and receipt workflows. Its Arc/USDC contracts were not copied or presented as native zkVerify functionality. Councils, contract-enforced caps, and anomaly indexing are not claimed here.

- [zkVerify documentation](https://docs.zkverify.io/)
- [zkverifyjs](https://github.com/zkVerify/zkverifyjs)
- [SubWallet](https://www.subwallet.app/)
- [Talisman](https://talisman.xyz/)
- [PSE Perpetual Powers of Tau](https://github.com/privacy-scaling-explorations/perpetualpowersoftau)
- [snarkjs](https://github.com/iden3/snarkjs) and [circomlib](https://github.com/iden3/circomlib)

Dependency licenses apply to their respective code. The optional proof tooling uses GPL-licensed snarkjs/circomlib; compiler/setup outputs are generated from the linked source and published ceremony. No ARCANUM code or assets were reused.
