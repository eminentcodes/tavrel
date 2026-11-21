# Tavrel verification

## Deterministic invoice tasks, agent wallets, balance, and connection repair

The current deterministic backend suite passed **145 tests in 191.321 seconds**. The focused invoice suite passed **17 tests in 8.841 seconds**, including whole-batch validation, scoped access, cancellation, restart/resume, legacy-run isolation, recipient alias binding, and invoice identity across batches. Two actual offline agent-wallet signature tests passed. Earlier build results below remain historical evidence rather than the current test count.

The user replaced model execution after malformed tool instructions and provider connectivity failures. The active runner is `invoice_rules_v1`: it accepts exact invoice fields, saves a bounded action plan, and uses the existing payment ledger. It makes no model calls and needs no model API key. Earlier model runs remain readable as history and cannot resume or execute; unpublished provider evidence stays in an ignored private archive.

Offline agent-wallet signing and tamper/sender checks passed, and an actual Windows DPAPI/Fernet encryption round trip passed. Permission tests cover version, expiry, sender, approval, funds, fee estimate, pause, and atomic revocation before durable transaction storage. Automatic settlement from a funded agent wallet remains unobserved. Agent wallets use server-held encrypted keys and server permissions; they do not offer ARCANUM's contract enforcement.

Read-only finalized Volta inspection and the authenticated balance route confirmed **1 tVFY** for the user's public account. The app displays the equivalent Volta SS58 address and a small top-right balance pill. No user allowance, recipient, or historical blocked intent was changed by these checks.

After the user's installed SubWallet hang report, **16 focused Node tests passed** for wallet access, login, and API responses. They cover SubWallet's documented native `enable` interface, new-style `connect` wallets, selected-extension isolation, access/account/signature timeouts, explicit retry, cancelled HTTP requests, and late replies. A cancelled or timed-out signature never reaches `/v1/auth/verify`. The app now gives pending-request guidance and a Cancel connection action. These checks use controlled providers and do not establish that the user's installed extension popup opens.

The production build passed. A publication audit found **zero source/evidence files containing the privately reused provider key**. The key, wallet vault, user ledger, research, and plans remain excluded from publication.

The deterministic and connection checks were verified on 21 November 2026, Africa/Lagos (WAT), using Windows, Python 3.13, and Node 22.22.2. Earlier published checks below are from 20 November. Documented installation requires Node 24.22.1+ to satisfy the sponsor SDK's engine requirement; the earlier sponsor SDK check used Node 24.22.1.

Tavrel implements actual wallet transfer payloads, cryptographic signature validation, durable native submission, finalized reconciliation, and receipt accounting. Production startup has empty account data and no simulation catalog. **No funded installed-wallet transaction was signed or broadcast during these checks.** Settlement behavior was tested with controlled RPC responses; live Volta fee/balance/nonce/finality reads were verified separately.

| Check | Observed result |
| --- | --- |
| `python -W error::ResourceWarning -m unittest discover -s tests -v` (current deterministic build) | **145 tests passed** in 191.321 seconds. Includes invoice batches, automatic-wallet permissions, payment rules, authentication, scoped HTTP/CLI access, proof lifecycle, restart recovery, and finalized accounting. |
| `python -m unittest tests.test_agent_runs -v` | **17 tests passed** in 8.841 seconds. Exact inputs, whole-batch validation, aliases fixed at creation, duplicate/revised references, scoped access, interruption/resume, cancellation, and legacy-run isolation. |
| `node --test tests/wallet-connection.test.mjs tests/wallet-login.test.mjs tests/api.test.mjs` | **16 tests passed**. Selected native provider, bounded waits, stale-provider retry, cancelled/late replies, exact message signing, incomplete HTTP responses, and no automatic repeated POSTs. |
| `node --test tests/agent-wallet.test.mjs` | **Two actual offline signature tests passed**, including sender/payload tampering. No live transfer. |
| `python -W error::ResourceWarning -m unittest discover -s tests -v` | **117 tests passed** in 145.910 seconds on the earlier published `f2082c1` build. Includes standalone invoice HTTP/CLI checks, payment rules, wallet login, scoped access, proof snapshot lifecycle, recovery, and finalized receipt accounting. |
| `python -m unittest tests.test_auth tests.test_gateway -v` | **17 tests passed** in 80.849 seconds after the first-wallet repair. Actual signatures register the first wallet through same-origin HTTP; missing browser provenance, task credentials, replay, and replacement of an existing owner are rejected. |
| `node --test tests/wallet-connection.test.mjs` | **Four tests passed** after the selected-extension change. An unrelated unresponsive extension receives no request; unsupported accounts are filtered, rejection can be retried, and signing preserves the exact payload and expected sender. |
| `node --test tests/native-signing.test.mjs tests/policy-proof.test.mjs` | **Ten tests passed**. Actual offline signatures reject changed call, nonce, era, genesis, runtime versions, tip, and sender. Compiled WASM tests check valid witnesses, limits, commitment binding, canonical field values, and production approval hashes. |
| `node scripts/check-native-rpc.mjs` | Real Volta genesis/token checks, balance, fee, nonce, finalized height, mortal era, and SCALE signing payload passed. No signing or submission. See [native RPC record](native-rpc-check.json). |
| `node scripts/check-zkverify.mjs` | Sponsor SDK chain properties and unsigned native SCALE transfer round trip passed in the earlier recorded network check. See [sponsor SDK record](zkverify-network-proof.json). |
| `node scripts/setup-policy-proof.mjs` | Compiled the circuit and derived a real FFLONK key from the pinned published PSE SRS. One public output; optional recipient tree supports eight accounts. Generated keys remain ignored. |
| `npm run proof:check` | **Twelve actual FFLONK checks passed**: valid proof, JSON key reordering, changed amount/recipient/sender/review/genesis with recalculated commitments/references, altered proof, cap/agent/account overflows, and unknown recipient. See [proof check record](policy-proof-check.json). |
| `node scripts/verify-policy-proof.mjs artifacts/payment-policy-proof.json` | The documented CLI independently verified the actual artifact's public commitment and SHA-256 reference. |
| `npm run build` | Native RPC/wallet bundles and production Vite build passed. |
| `node scripts/check-frontend.mjs` | Full browser flow passed, including restricted agent connection download, actual app-generated policy proof, downloaded proof verification, native wallet-message login, live fee review, images, and responsive layouts. No page errors. |
| `npm audit --json` | **Zero vulnerabilities**. Patched `underscore` is pinned to 1.13.8. |

The current [browser record](ui/frontend-proof.json) covers normal empty-ledger startup, actual sr25519 message verification using an injected unfunded wallet, persistent/revoked sessions, selected native SubWallet access, cancellation and ignored late replies, explicit retry, policy creation, approvals, live Volta fee review, and insufficient-funds sign gating. It completed an `invoice_rules_v1` task through the actual invoice form with no model calls. It also checked the balance pill, Volta address display, separate agent-wallet creation, sender permission gates, landing images, twelve Docs sections, and responsive layouts with no page errors. The selected fixture connected and signed in **15.424 seconds** in this run; unrelated extensions received zero requests. The downloaded proof verified with reference `sha256:994bc2b5521ff521d3b88cf1f9d819b916cebed55dc550e3552460bf2c927ed9`. The footer links to the Volta faucet. Controlled providers do not establish installed-extension popup behavior or human signing speed; no transfer was signed or broadcast.

## What the tests establish

- Amounts retain exact 18-decimal precision above SQLite's signed-integer range. Atomic account/agent reservations cannot overrun allowances under competing requests.
- Approval binds the reviewed amount, sender, recipient, purpose, and policy version. Changed rules require a new review. Agent tokens cannot approve, change policies, request signing quotes, or submit signatures.
- Signed bytes persist before submission. Restart and uncertain pool responses reuse those bytes; they do not create replacements or release reservations prematurely.
- Controlled finalized receipts must match genesis, transaction, sender, recipient, amount, and success. Successful principal moves from held to spent once. Included failures release principal; expiry requires finalized scanning through the signed lifetime.
- Proof caching follows the reviewed snapshot. Changed reservations invalidate proofs on fee re-review; submitting an earlier quote restores its snapshot. A snapshot changed while proving causes generation to fail without storing a reference.
- The standalone invoice runner uses real HTTP routes and downloaded connection data. It reports ready/approval decisions, watches requests, and returns the same IDs on retry.

## Actual policy artifact and trust

[payment-policy-proof.json](payment-policy-proof.json) contains a real FFLONK proof from isolated test instructions. Its reference is:

`sha256:a95cd109e9ae372f2bb6e4302313a5a7d8a882fa1f5e3e0ab731c0f63f966658`

It binds the exact positive amount, recipient, sender, approval hash, and Volta genesis to a policy commitment containing recipient membership and cap/remaining allowances. It proves the supplied commitment. It does not independently authenticate the server's snapshot, prove service delivery, constrain unrelated wallet transfers, or prove settlement. The public key and manifest are included under `proofs/`; verification needs no SRS or proving-key setup. Source hashing normalizes line endings for Windows/Linux checkouts.

The key uses the published [PSE power-16 ceremony file](https://pse-trusted-setup-ppot.s3.eu-central-1.amazonaws.com/pot28_0080/ppot_0080_16.ptau), pinned to SHA-256 `ed3622a7c79b0b49aadd134ebbc5b77df8c8c59bccebdfd0d9bf2c1a51561cf9`. Default setup verifies that checksum and relies on the published ceremony. **Full cryptographic ceremony re-verification was not completed**; `--verify-ceremony` explicitly enables it. The manifest records `ceremony_reverified: false` for this run. Local proof verification does not remove the SRS trust assumption.

`zkverify_transaction` is `null`: no on-chain proof submission is claimed. Native transfers and ZK verification are separate actions.

## Corrections made during verification

The final deterministic browser review initially inspected lazy landing images before loading completed. Waiting for each image to enter the viewport and decode confirmed all images rendered. A later live RPC fee request timed out. The final read-only browser rerun outside the sandbox passed fee review, invoice execution, proof download/verification, image rendering, and mobile layout. No transaction was inferred from that retry.

Volta codec properties needed JSON normalization, and WebSocket checks timed out; HTTPS native reads passed. Circom's Windows WASI bindings needed native Node paths; generated CommonJS helpers needed a package boundary. O2 compilation expanded the FFLONK representation beyond the downloaded SRS. O1 and an eight-recipient tree fit the pinned file while preserving the documented amount/recipient claim.

Canonical object-key ordering now allows SQLite-stored/downloaded JSON to verify. Canonical uint128/field parsing rejects aliases. Snapshot tests exposed stale proof reuse across changed allowance reviews; atomic invalidation and generation-time checks fixed it. Browser verification exposed production approval hashes without a hex prefix; the witness builder now binds their exact bytes consistently, with a compiled-circuit regression check.

Some Windows subprocess checks required approved execution outside the sandbox after EPERM errors. Final checks passed. Historical simulations/plugin archives are excluded from publication; controlled fixtures remain under tests and cannot populate production startup.

The first-wallet test previously used a terminal setup URL, which hid the blocked onboarding path reported by the user. Direct same-origin enrollment now still requires a real signature and cannot replace an existing owner. Wallet selection avoids waiting for every installed extension. Decoder libraries load when the wallet modal opens, reducing the initial app bundle from the interim 756.81 kB to 479.49 kB. Account data finishes loading before sign-in exposes editable controls, fixing an allowance-field reset found during browser verification.

An interim browser RPC request failed to fetch Volta data. The explicitly escalated read-only RPC retry passed, and the final full browser run passed live fee review and actual proof generation/download verification. No signing, broadcast, or settlement was inferred from these retries. The local production server was restarted with the authentication repair while preserving its ledger.

## Remaining real-world verification

A person must use an installed wallet funded with faucet tVFY, confirm **Sign and send**, and compare the finalized explorer transaction with the downloaded receipt. That outcome is not claimed by offline signatures, fixture receipts, fee quotes, or screenshots. No paid calls, funding, tool-initiated live transactions, deployment, or hackathon submission occurred.
