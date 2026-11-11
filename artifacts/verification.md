# Tavrel local verification

Verified through 2026-11-11 00:09, Africa/Lagos time (WAT), using Windows and Python 3.13.

The gateway/plugin/operator CLI supports real free research and a separate spending simulation. All **71 behavioral tests pass**, including real gateway-process startup/restart, bounded reconciliation, and migration without reinterpreting simulated costs. The actual Hermes loader discovers Tavrel and its real registry executes all three tools; `/budget` works. No language model, paid API, wallet signing, or payment settlement was used.

| Check | Observed result |
| --- | --- |
| `python -W error::ResourceWarning -m unittest discover -s tests -v` | 71 tests passed in 57.672 seconds; no resource warnings in the final output. |
| `python -m tavrel demo --output artifacts/demo-proof.json` | Exit 0; 184 cents simulated spend, zero held, 66 cents available; identical retry returned the same request. |
| `python -m tavrel demo --live --output artifacts/live-demo-proof.json` | Exit 0; five real GitHub repositories, five Crossref publications after operator approval, local extraction, permission blocking, and cached retry evidence. Zero recorded cost and hold. |
| `python scripts/verify_hermes.py --hermes-deps .cache/hermes-deps --live --output artifacts/hermes-loader-proof.json` | Exit 0 against official Hermes revision `e0f07847b8f38ac72890cf98e0d344c372ae7ee8`; real discovery, all three registry-dispatched tools, `/budget`, two free public API calls, operator-only approval, permission blocking, and identical retry passed. |
| `python scripts/package_plugin.py` | Archive rebuilt; exact two-file contents, archive integrity, and equality to plugin source verified. |
| `python -m compileall -q tavrel hermes_plugin tests scripts` | Exit 0. |
| Artifact integrity and sanitization | All three proofs contain no task tokens or token hashes; Hermes proof fingerprints and the two-file archive exactly match the current plugin source. Paid calls and wallet payments are zero; the Hermes verifier's model-call count is zero. |
| `git -C .cache/hermes-agent status --porcelain` | Empty output; the upstream source checkout used for verification is unmodified. |

The tests verify task and workspace budgets under competing requests, maximum-cost reservations, execution once under concurrent retries, approval fingerprints, policy changes, confirmed no-charge failures, invalid receipts, uncertain holds, restart recovery, task-token rotation, cross-task access, operator-only actions, Host/Origin checks, input bounds, redirect refusal, loopback proxy isolation, documented plugin registration signatures, and CLI subprocesses. The extension adds free HTTP receipt hashes, bounded provider responses, rate-limit/redirect/invalid-JSON handling, DOI/repository metadata, approval before free execution, explicit ledger-mode separation, legacy migration, and reconciliation through engine, HTTP, and CLI. Concurrent reconciliation commits the cost and releases the hold exactly once.

Issues found and fixed during verification:

- A service price change after reservation reached execution and only failed receipt validation afterward. Execution now blocks the stale quote and releases the reservation before invoking the service.
- Non-ASCII approval fingerprints and operator tokens caused comparison exceptions. They now return policy/authentication errors.
- HTTP error/redirect responses needed explicit closure. Final resource checks pass.
- On Windows, closing with a modest oversized unread request body could reset the connection before the client received its JSON error. The gateway now discards a bounded overflow before rejection; it still parses only bodies up to 64 KB.
- Repeated urllib client construction loaded the Windows trust stores repeatedly. Loopback clients now reuse stateless handlers while retaining urllib's TLS verification defaults and disabled proxies.
- An early authorization rejection could also close an unread POST/PATCH body and reset a Windows connection. The gateway now drains only bounded declared bytes before returning an error; it neither parses nor authorizes that rejected operation. Tests verify JSON rejections with bodies through 130 KB. Clients also preserve a structured HTTP rejection if the error body resets.
- The new migration fixture initially left a SQLite connection open. The fixture now closes it explicitly after committing, and the final resource-warning run passes. A misplaced test boundary was corrected before the final passing run.

The first restricted test runs failed to open and clean up their Windows temporary databases. The user approved running the local tests outside that sandbox. A later expanded run exposed a 15-second demo-test timeout and the oversized-body connection reset; both were addressed before the passing final run. The earlier session's demo startup error did not recur, so its historical cause remains unconfirmed.

The [demo proof](demo-proof.json) is synthetic. The [live research proof](live-demo-proof.json) contains actual unauthenticated API retrieval evidence, and the [Hermes proof](hermes-loader-proof.json) records real upstream loader/registry behavior against the gateway. All are sanitized. The [plugin archive](tavrel-hermes-plugin.zip) contains only `tavrel/__init__.py` and `tavrel/plugin.yaml`; operator runtime data and Hermes source/dependencies are excluded.

Reconciliation in this build is explicitly an operator attestation, bounded by the original maximum. It does not independently verify provider billing, retry unknown work, or create verified service output. Free requests establish useful live integration and provenance; they cannot prove a paid-spend ceiling or payment settlement.

Remaining milestones: a model-driven Hermes session, per-session task binding if needed, OS isolation of operator/provider access, authoritative live billing reconciliation, a verified paid-provider maximum-cost contract, and exact hackathon requirements. `hermes`, `ollama`, and `llama-server` are absent from PATH on this machine; the current proof uses the actual source loader without invoking a model. The user's current spending limit remains $0. No paid calls, transactions, deployment, or submission occurred.
