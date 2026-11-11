# Tavrel — Celo hackathon project plan

Last updated: 2026-11-02, 16:13 WAT (UTC+01:00).
Stage: research and product definition. Implementation has not started.
Target: Agents on Open Rails Hackathon, Track 3 — Build with buy.
Project name: **Tavrel**, selected by the user on 2026-11-02. Pronunciation: TAV-rel.
Working descriptor: controlled spending for AI agents on Celo.

## Objective

Build an original product inspired by ARCANUM's governed agent spending: let an agent buy useful third-party services through buy on Celo while its operator controls the budget, permitted services, and approval requirements.

The user has selected Track 3 and supplied ARCANUM as a reference. The exact product, target user, and feature priorities remain open. The scope below is a proposal, not a finalized product decision.

## Verified hackathon requirements

Source: [Celo announcement](https://celo-devs.beehiiv.com/p/agents-on-open-rails-hackathon-starts-tuesday-october-6th), published 2026-10-01. A readable copy is saved in [research/hackathon.txt](research/hackathon.txt).

| Item | Published requirement |
| --- | --- |
| Track | Track 3 — Build with buy |
| Prize | $1,000 in CELO across five projects, $200 each |
| Core flow | Pays for services the team does not own using buy |
| Product | Solves a real problem; judged on the problem and depth of integration |
| Network | The announcement describes five weeks on Celo mainnet and says onchain volume counts toward the score |
| Meaningful usage | Spamming the cheapest call scores nothing |
| Submission deadline | Monday, 9 November 2026, 09:00 GMT / 10:00 WAT |
| Winners | Friday, 13 November 2026 |

The announcement describes buy as handling HTTP 402 with a locally signed stablecoin payment on Celo attached to the retry, optionally with human identity proof. Listed services include social data, rented browsers, Linux machines, flight data, RPCs, indexing, and inference.

Confirm the submission portal, full eligibility rules, required artifacts, supported tokens, and current service catalog before relying on them. These details are not established by the announcement alone.

## Track 3 fit assessment

**Conditional fit:** a governed-wallet dashboard alone does not demonstrate Track 3's core flow. The product should govern actual buy purchases that an agent needs to complete a useful task.

| ARCANUM inspiration | Proposed Celo adaptation | Evidence to demonstrate |
| --- | --- | --- |
| Agent spending authority | Operator gives a buy-powered agent a constrained budget | A task completes with real paid third-party results |
| Per-payment and cumulative limits | Enforce limits at the supported payment boundary | Allowed purchase succeeds; over-budget purchase is blocked before signing |
| Vendor allowlist | Permit specific verified services and payment recipients | Unapproved service cannot receive a payment |
| Human escalation | Pause sensitive purchases for operator review | Approval resumes the intended purchase; rejection prevents it |
| Payment records | Link task, service, price, policy decision, and settlement | Traceable records with payment evidence where available |

ARCANUM's README describes smart-contract enforcement on Arc. That does not establish compatibility with buy on Celo. Its repository was reviewed as a reference; its contracts, security claims, and live flows have not been independently verified.

If we reuse code, check the license of the exact files and document attribution and new work. The README identifies AGPL-3.0 for the application and Apache-2.0 for contracts and SDKs.

## Proposed MVP

Working description: a spending-control layer for agents using buy, with one complete example task.

A candidate demo is creator research: an agent purchases relevant social data through buy and produces a sourced comparison or brief. This is a proposed example; the user may prefer another real task.

1. Operator creates an agent budget, service allowlist, and approval threshold.
2. User submits a task that requires a supported third-party service.
3. Agent discovers the service and obtains its actual payment requirements.
4. Policy validates the service, recipient, token, network, price, and available budget before payment signing.
5. An allowed purchase proceeds through buy; a sensitive purchase pauses for approval; a prohibited purchase stops.
6. Agent uses the purchased result to finish the task.
7. Operator sees the result, spend, decisions, and settlement evidence.

Must-have deliverables:

- [ ] One clearly defined target user and useful task.
- [ ] buy integration in the task's core flow, purchasing a service we do not own.
- [ ] Per-payment and total budget controls, service allowlist, and a simple approval flow.
- [ ] Correct handling of retries, concurrent requests, cancellations, and uncertain settlement.
- [ ] A task result that uses the purchased data or service.
- [ ] A concise operator interface and truthful payment/decision records.
- [ ] A successful Celo mainnet demonstration within an agreed spending budget.
- [ ] README, reproducible setup, deployment details, demo video, and submission materials.

Defer unless the core flow is complete: multi-person councils, anomaly scoring, multi-chain support, public badges, extensive analytics, and a broad marketplace.

## First technical gate: buy payment compatibility

Before choosing a smart-wallet architecture:

- [ ] Obtain current official buy installation and integration documentation.
- [ ] Confirm supported Celo assets, service pricing, settlement evidence, and payment signing interfaces.
- [ ] Determine whether buy accepts smart-contract wallets, delegated/session signing, or only an EOA signing path.
- [ ] Identify whether external payments can bypass the proposed policy checks.
- [ ] Prove that a blocked request never reaches payment signing, and that approving one request cannot authorize another.
- [ ] Define reservation and reconciliation rules so retries or concurrent tasks cannot overspend.
- [ ] Record the supported enforcement model and its limitations before implementation.

If buy supports a compatible contract-wallet path, assess contract-enforced controls. If only an EOA integration is available, consider a restricted signing adapter, explicitly describing its trust assumptions. Do not call offchain controls onchain enforcement or claim protection from a compromised signing key.

Current research limitation: direct requests to usebuy.ai failed to resolve, and a readable-copy request failed. No buy SDK interface or smart-wallet compatibility is confirmed yet. AgentCash research was unavailable; AgentCash is not the required buy integration.

## Proposed implementation approach

- Web interface: TypeScript with a framework selected after product definition.
- Agent runner: orchestration that exposes paid tools through the policy/payment adapter.
- Payment integration: official buy interface, determined by the compatibility check.
- Policy: deterministic checks outside the model; enforcement location depends on supported signing.
- Records: durable task, request, approval, budget reservation, and settlement state.
- Contracts: add only if they support the verified payment path and improve the MVP.

No stack or deployment choice is final yet. Never store secrets in these documents, browser code, screenshots, or committed fixtures.

## Delivery schedule

Dates use Africa/Lagos time (WAT). This is a target schedule starting 2 November, not evidence of completed work.

| Date | Focus | Exit condition |
| --- | --- | --- |
| Nov 2 | Define user/problem; verify buy compatibility and rules | Product scope and feasible signing/payment path recorded |
| Nov 3 | Prove one paid service request; implement basic policy | Allowed request succeeds; blocked request cannot sign |
| Nov 4 | Build the useful agent task and result | Purchased third-party output materially supports the result |
| Nov 5 | Add approvals, durable budgets, retries, and records | No duplicate spend or budget bypass in covered failure cases |
| Nov 6 | Connect the operator interface | Complete task-to-payment-to-result walkthrough |
| Nov 7 | Run meaningful checks and bounded mainnet demo | Settlement evidence and spending totals captured |
| Nov 8 | Prepare submission and rehearse | README, video, links, and required portal fields ready |
| Nov 9 before 10:00 WAT | Submit with buffer | Submission confirmation recorded |

## Verification and demo

Test the risks that affect money and authorization: budget accounting, concurrent reservations, service/recipient mismatch, approval binding and expiry, duplicate retries, failed calls, and ambiguous settlement. Verify the complete user flow once the implementation exists.

The demo should show a useful successful purchase, one blocked request, one reviewed purchase, the resulting task output, and real payment evidence. Label simulations clearly. Do not generate artificial volume.

## Progress and decisions

- [x] Inspect the workspace: initially empty.
- [x] Read the hackathon announcement and identify Track 3 requirements and deadline.
- [x] Review ARCANUM's README and public landing-page source as inspiration.
- [x] Create the project plan and agent progress protocol.
- [ ] Confirm whether the user prioritizes a general spending-control product or a specific agent product.
- [x] Select product name: **Tavrel**.
- [ ] Select target user, first task, and differentiator.
- [x] Research product names and record preliminary software/domain collision checks in [research/naming-report.md](research/naming-report.md). The user selected Tavrel from the shortlist.
- [ ] Complete the buy compatibility gate.
- [ ] Confirm implementation scope and start development.

Use [agent.md](agent.md) for timestamped work records. Update this plan when decisions, scope, milestones, or risks materially change.

## Reference links

- [Hackathon announcement](https://celo-devs.beehiiv.com/p/agents-on-open-rails-hackathon-starts-tuesday-october-6th)
- [buy](https://usebuy.ai/)
- [ARCANUM live site](https://thearcanum.in/)
- [ARCANUM repository](https://github.com/bunnyyxtan/ARCANUM)
- Local research: [ARCANUM README](research/arcanum-readme.md), [repository metadata](research/arcanum-repo.json), and [landing-page source](research/arcanum-site.html).
