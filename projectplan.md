# Tavrel — Hermes Agents hackathon project plan

Last updated: 2026-11-11 08:08 WAT (UTC+01:00).
Stage: the zero-cost integration extension is complete: live free research, actual Hermes loader/registry execution, operator reconciliation, documentation, and packaging are verified. All 71 behavioral tests pass. The user's spending constraint remains $0.
Target: Hermes Agents hackathon, selected by the user on 2026-11-09; exact event page and rules awaiting verification.
Working name: **Tavrel**, previously selected by the user; retain while exploring the new product.
Product description: a Hermes plugin for deterministic task budgets, human purchase approvals, and a durable spend ledger, with a companion gateway and operator CLI.
Repository: [eminentcodes/tavrel](https://github.com/eminentcodes/tavrel), private. The current build is pushed to main from a standalone repository in this workspace.

## Current objective

Build a runnable local Tavrel prototype that proves a complete governed-spending workflow through Hermes-compatible tools and operator CLI commands. A dashboard is deferred following the user's question about its necessity.

Current extension, requested on 2026-11-10: make the integrations real while spending $0. Use public unauthenticated APIs and local processing for useful research results; test the actual Hermes runtime/loader without a paid model call. Paid service execution stays disabled. Actual paid-spend enforcement and payment settlement cannot be proved by a free request, and must remain explicitly unverified.

First audience: Hermes users delegating workflows that use paid tools, especially solo builders, researchers, and small teams. Concrete use case: "Research five competitors and write a comparison. Spend up to $5 and ask before any purchase over $1." The first local proof uses simulated services; this is not evidence of demand or a live billing integration.

The build runs with `python -m tavrel serve` (free public APIs), `python -m tavrel demo --live` (real zero-cost research), or `python -m tavrel demo` (explicit simulated spending). Actual Hermes discovery and registry dispatch have passed against official revision `e0f07847b8f38ac72890cf98e0d344c372ae7ee8` without a model call. Setup and plugin installation are in [README.md](README.md); observed test and packaging results are in [artifacts/verification.md](artifacts/verification.md). Sanitized simulation, live-free, and actual-Hermes proofs are retained under artifacts/.

The user requested that the build continue on 2026-11-09. This authorizes local implementation of the most recent Tavrel spending-control direction and supersedes the earlier instruction to remain in ideation. The plugin should serve Hermes users broadly; the niche freelancer/job-search shortlist remains rejected. Live integrations and event eligibility remain separate, unverified milestones.

## Confirmed decisions

- The target has changed from the Celo hackathon to the Hermes Agents hackathon.
- Start local implementation following the user's 2026-11-09 build request.
- Explore a plugin with a concrete real-world use case and potential user traction.
- Evaluate Tavrel's original spending-control concept for broad Hermes use; the user rejected the narrow freelancer/job-search direction.
- Implement spending control without buy. Use the gateway architecture for the local proof; live account-billed and wallet integrations remain proposals.
- Keep the existing 30-minute checkpoint protocol during active work.
- Continue with real integrations under the user's 2026-11-10 instruction, with zero paid API/model calls, wallet transactions, or funding requirements.
- Create a project repository on the user's GitHub account and push the current build, authorized on 2026-11-11. Use a private repository by default; hackathon submission remains separate.

The former Celo Track 3 requirement, mandatory buy integration, mainnet demonstration, and November 9 submission schedule are superseded. The prior plan and its research remain available for historical context in [projectplan.celo-archive.md](projectplan.celo-archive.md).

## Current build scope

- Python standard-library gateway with SQLite-backed integer money accounting and atomic task/account reservations.
- Real unauthenticated GitHub repository search, Crossref publication metadata, and local text extraction, each at a fixed zero price. Paid execution is disabled and the default workspace allowance is $0.
- Fixed-price, clearly labeled simulated services in a separate explicit mode for the nonzero-spending proof. A Tavrel allowance is not a deposit; simulated costs are not real payments. Ledger modes cannot be mixed or reinterpreted, including legacy simulation migration.
- Request-bound operator approval above a configurable threshold, with an optional approval-before-every-request policy for free services. Approval must not override remaining budget or service restrictions.
- Idempotent requests, concurrency-safe budget checks, persistent pending/uncertain reservations, and a traceable ledger.
- Restricted task token for Hermes tools, separate operator authentication, and no agent-accessible approval tool.
- Self-contained native Hermes plugin manifest, tool registration, status command, and documented installation.
- Operator CLI with budget creation, policy controls, request-bound approval actions, and request/result inspection. Operator credentials are separate from the plugin's task token.
- Operator-only reconciliation of uncertain requests, bounded by the original maximum and backed by an explicit evidence reference and note. This records an operator attestation, releases the unused hold once, and never retries work or invents verified service output.
- Reproducible verification through the actual Hermes loader and tool registry, in an isolated temporary profile without a language-model call.
- Meaningful engine/API/plugin/CLI tests plus an executable end-to-end terminal walkthrough.

The dashboard, live model-provider routing, wallet payments, remote deployment, hackathon submission, and demo video are later milestones. The interrupted video request has been redirected to the build.

## Hackathon requirements

- [ ] Identify the exact official Hermes hackathon announcement and submission page.
- [ ] Verify deadline, eligibility, judging criteria, required Hermes integration, and deliverables.
- [ ] Confirm whether a native plugin, skill, MCP integration, or another extension format qualifies.
- [ ] Verify publication and submission expectations.

The event link has been requested from the user while independent Hermes research continues.

## Product selection criteria

1. An identifiable first audience with a frequent, costly, or frustrating problem.
2. A concrete before/after outcome demonstrated through a realistic workflow.
3. A reason to keep using the plugin after the first demo.
4. Capabilities that add value beyond Hermes' existing memory, scheduling, messaging, and tools.
5. A focused MVP with practical integrations and a short route to first value.
6. A credible way to reach initial users and collect direct demand evidence.
7. Accurate state tracking, grounded outputs, and user control over consequential actions.

Popularity, willingness to pay, and retention remain hypotheses until validated with prospective users or usage. Repository stars and available APIs do not establish demand for a particular plugin.

## Hermes capability research

Assumption pending the event link: the target platform is Nous Research's Hermes Agent.

The official [Hermes repository](https://github.com/NousResearch/hermes-agent) README documents persistent memory, scheduled tasks, messaging gateways, skills, and MCP support. The [plugin documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins) documents custom tools, hooks, slash commands, bundled skills, and installable plugins. The [plugin catalog documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugin-catalog) describes a reviewed distribution route; catalog admission is not guaranteed.

Source snapshots are retained under [research/hermes](research/hermes/README.md). Event eligibility is a separate unanswered question. Inspect existing plugins and supported integration interfaces before choosing the implementation.

## Idea exploration

Active question: can Tavrel's original governed agent spending become a useful Hermes plugin across research, coding, content creation, and other paid-tool workflows?

Original concept: an operator gives an agent a constrained budget, permits specific services, requires approval for certain purchases, and can trace each purchase to its task and payment evidence.

Proposed Hermes adaptation: an installable spending-control plugin with per-task and cumulative budgets, paid-service adapters, purchase approval, and durable spend records. Wallet/payment integrations can be adapters rather than a mandatory Celo dependency. This is a feasibility proposal, not confirmed scope.

The official plugin documentation lists `pre_tool_call`, `pre_llm_call`, and observer hooks, as well as custom tools and commands. It also states that approval transports change where an existing approval is presented; they are not an authorization-policy API. Tavrel would need its own deterministic budget and purchase-authorization logic at an actual payment boundary.

Important technical gate: prove allowed purchases, blocked purchases before signing/payment, approval binding, retry/concurrency accounting, and the routes a user or agent could use to bypass the adapter. Initial hard limits should be described only for integrated purchase routes. Complete model-billing coverage and universal enforcement are unverified.

Proposed integration without buy: a Hermes plugin provides the controls, and a separate gateway holds provider credentials and checks/reserves budget before covered billable requests. API services charge their existing account or prepaid credits; a Tavrel budget is an allowance, not a deposit. An optional wallet adapter could handle direct payments to compatible services, with compatibility still to be verified.

Hermes' provider documentation includes custom endpoints, allowing a proposed model-gateway route. Paid tools require service adapters. Reliable maximum prices, isolated credentials, auxiliary/subagent/fallback routing, retries, and reconciliation all require verification before advertising a hard cap. Existing local cost analytics are documented as lower-bound estimates, and Nous billing already has some account-level caps; differentiation needs research.

The full proposed flow, evidence, and open questions are in [research/hermes/spending-integration.md](research/hermes/spending-integration.md). Recommended first proof: one supported model provider and one fixed-price paid tool. This recommendation is not confirmed MVP scope.

The narrow missed-follow-up, freelancer-invoice, and job-search shortlist was rejected by the user on 2026-11-09. Do not continue it as the selected direction.

Demand and differentiation still need evidence. Broad usefulness is a product goal; it does not establish that every Hermes user needs paid-service governance. The previous creator-research demo remains optional.

## Milestones

- [x] Receive authorization to start the local build.
- [x] Implement deterministic budgets, reservations, approvals, and durable spend evidence.
- [x] Verify concurrency, idempotency, uncertain outcomes, and application-level authorization boundaries through local behavioral tests.
- [x] Implement and verify the documented native Hermes plugin contract, actual Hermes discovery, all three registry-dispatched tools, and /budget.
- [x] Build the operator CLI and demonstrate the end-to-end local plugin flow.
- [ ] Add an optional dashboard if actual usage establishes a need.
- [x] Document local setup and actual enforcement limits, including process-wide task binding, filesystem access, and explicit operator attestation for uncertain outcomes.
- [x] Prove real free GitHub/Crossref retrieval and local extraction, including provenance, approval, permission blocking, and idempotent retries.
- [x] Implement bounded operator reconciliation without reexecution or automatic provider-billing claims.
- [x] Verify Tavrel through the real Hermes loader and registry against the gateway, without invoking a model.
- [ ] Run a model-driven Hermes session against the gateway when a free/local model is available.
- [ ] Add per-session task binding if needed; the current environment token binds the entire Hermes process.
- [ ] Prove at least one supported live provider adapter with authoritative billing evidence, after authorization and account setup.
- [ ] Prepare the demo video after the build is ready.
- [x] Create a standalone Tavrel Git repository, push the project to the authenticated GitHub account, and verify the remote commit.

- [x] Read the previous working documents and record the target change.
- [x] Record the user's requirement to continue ideating around a useful plugin.
- [x] Verify that Hermes documents native plugin interfaces and a reviewed catalog.
- [ ] Verify the Hermes event and extension eligibility requirements.
- [ ] Research existing Hermes spending/approval capabilities and competing solutions.
- [x] Present an initial shortlist; user rejected the narrow audience focus.
- [x] Assess the original Tavrel concept against documented Hermes extension hooks; actual integration and enforcement remain unproven.
- [x] Document a spending-gateway proposal without buy, distinguishing API-account charges from wallet payments.
- [ ] Select the problem, first audience, and differentiator with the user.
- [x] Define and build a focused CLI-first local MVP with a simulated competitor-research spending demo.
- [ ] Validate demand with prospective users; record actual evidence.
- [x] Choose the local gateway/plugin/CLI architecture; retain the active-session checkpoint cadence.
- [x] Build, behaviorally verify, and document the authorized local prototype.
- [ ] Confirm event publication requirements and prepare hackathon submission after eligibility and submission authorization are confirmed.

## Working boundaries and verification

Local implementation, documentation, and verification are authorized by the current build request. Earlier ideation-only boundaries are superseded.

Use real free public APIs for the zero-cost integration, and clearly label the separate simulation's costs and examples. The user has authorized no paid calls, transactions, or funding. Do not initiate messages to others, deployment, or submission without authorization. Enforce spending and authorization in deterministic gateway code.

For the selected idea, verify the outcome that matters to its users and the actual integration boundary. Label simulations and unverified assumptions accurately. Keep secrets out of the repository.

## References and records

- [Hermes Agent repository](https://github.com/NousResearch/hermes-agent)
- [Hermes documentation](https://hermes-agent.nousresearch.com/docs/)
- [Previous Celo project plan](projectplan.celo-archive.md)
- [Naming research](research/naming-report.md)
- [Agent instructions and append-only progress log](agent.md)
