# Tavrel verification

Verified on 20 November 2026, Africa/Lagos (WAT), using Windows, Python 3.13, and Node 22.22.2. Documented installation requires Node 24.22.1+ to satisfy the sponsor SDK's engine requirement; the earlier sponsor SDK check used Node 24.22.1.

Tavrel implements actual wallet transfer payloads, cryptographic signature validation, durable native submission, finalized reconciliation, and receipt accounting. Production startup has empty account data and no simulation catalog. **No funded installed-wallet transaction was signed or broadcast during these checks.** Settlement behavior was tested with controlled RPC responses; live Volta fee/balance/nonce/finality reads were verified separately.

| Check | Observed result |
| --- | --- |
| `python -W error::ResourceWarning -m unittest discover -s tests -v` | **117 tests passed** in 145.910 seconds. Includes standalone invoice HTTP/CLI checks, payment rules, wallet login, scoped access, proof snapshot lifecycle, recovery, and finalized receipt accounting. |
| `node --test tests/native-signing.test.mjs tests/policy-proof.test.mjs` | **Ten tests passed**. Actual offline signatures reject changed call, nonce, era, genesis, runtime versions, tip, and sender. Compiled WASM tests check valid witnesses, limits, commitment binding, canonical field values, and production approval hashes. |
| `node scripts/check-native-rpc.mjs` | Real Volta genesis/token checks, balance, fee, nonce, finalized height, mortal era, and SCALE signing payload passed. No signing or submission. See [native RPC record](native-rpc-check.json). |
| `node scripts/check-zkverify.mjs` | Sponsor SDK chain properties and unsigned native SCALE transfer round trip passed in the earlier recorded network check. See [sponsor SDK record](zkverify-network-proof.json). |
| `node scripts/setup-policy-proof.mjs` | Compiled the circuit and derived a real FFLONK key from the pinned published PSE SRS. One public output; optional recipient tree supports eight accounts. Generated keys remain ignored. |
| `npm run proof:check` | **Twelve actual FFLONK checks passed**: valid proof, JSON key reordering, changed amount/recipient/sender/review/genesis with recalculated commitments/references, altered proof, cap/agent/account overflows, and unknown recipient. See [proof check record](policy-proof-check.json). |
| `node scripts/verify-policy-proof.mjs artifacts/payment-policy-proof.json` | The documented CLI independently verified the actual artifact's public commitment and SHA-256 reference. |
| `npm run build` | Native RPC/wallet bundles and production Vite build passed. |
| `node scripts/check-frontend.mjs` | Full browser flow passed, including restricted agent connection download, actual app-generated policy proof, downloaded proof verification, native wallet-message login, live fee review, images, and responsive layouts. No page errors. |
| `npm audit --json` | **Zero vulnerabilities**. Patched `underscore` is pinned to 1.13.8. |

The [browser record](ui/frontend-proof.json) covers normal gateway startup, native sr25519 login using an injected unfunded test wallet, persistent/revoked sessions, action-gated wallet access, policy creation, approval, real Volta fee review, insufficient-funds sign gating, images, and responsive layout. It also confirms the actual downloaded proof verified with reference `sha256:c4f7578f659f95ed9cdc45958da6e368932a83c9f889c283888d79d042102193`. An injected provider is not a tested installed wallet.

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

Volta codec properties needed JSON normalization, and WebSocket checks timed out; HTTPS native reads passed. Circom's Windows WASI bindings needed native Node paths; generated CommonJS helpers needed a package boundary. O2 compilation expanded the FFLONK representation beyond the downloaded SRS. O1 and an eight-recipient tree fit the pinned file while preserving the documented amount/recipient claim.

Canonical object-key ordering now allows SQLite-stored/downloaded JSON to verify. Canonical uint128/field parsing rejects aliases. Snapshot tests exposed stale proof reuse across changed allowance reviews; atomic invalidation and generation-time checks fixed it. Browser verification exposed production approval hashes without a hex prefix; the witness builder now binds their exact bytes consistently, with a compiled-circuit regression check.

Some Windows subprocess checks required approved execution outside the sandbox after EPERM errors. Final checks passed. Historical simulations/plugin archives are excluded from publication; controlled fixtures remain under tests and cannot populate production startup.

## Remaining real-world verification

A person must use an installed wallet funded with faucet tVFY, confirm **Sign and send**, and compare the finalized explorer transaction with the downloaded receipt. That outcome is not claimed by offline signatures, fixture receipts, fee quotes, or screenshots. No paid calls, funding, tool-initiated live transactions, deployment, or hackathon submission occurred.
