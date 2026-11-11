# Tavrel spending integration without buy

Status: architecture proposal for ideation; no integration has been implemented or demonstrated.
Prepared: 2026-11-09 10:24 WAT (UTC+01:00).

## Proposed product

A Hermes plugin supplies budget settings, approval interactions, and spending records. A separate spending gateway performs the actual checks and sends authorized requests to supported paid services.

The gateway holds upstream provider credentials or a payment-signing credential in an isolated service. Hermes receives a restricted Tavrel token bound to its budget. Hard enforcement requires relevant requests to pass through the gateway and upstream keys/signing to be inaccessible to the agent. A plugin hook by itself does not prevent direct calls using credentials available elsewhere.

## API-account billing

For supported model, search, image, or other billable APIs, the service already charges an account or deducts prepaid credits when a request is made. Tavrel authorizes that request; the provider handles billing.

A budget in Tavrel is a spending allowance, not a new deposit. No buy integration or wallet transfer is required for this path. Connect the operator's existing provider account, route covered model requests through a custom provider endpoint, and expose covered paid tools through Tavrel adapters.

Existing subscriptions and local/free models must not be reported as new dollar payments per request. Their usage can be tracked in appropriate units when supported.

## Actual wallet payments

An optional wallet adapter could sign payments directly to a service that accepts a supported payment protocol, such as x402. This preserves the original wallet-purchase concept without buy. Exact service, SDK, network, assets, pricing, signing, and settlement compatibility remain unverified and are not selected scope.

API-account charges and actual wallet transfers need distinct records and labels.

## Request lifecycle

1. Operator connects a supported service and creates task/account limits.
2. Hermes sends a model request through the gateway or calls a Tavrel-backed paid tool.
3. The adapter obtains a fixed price or a verified conservative maximum cost. Variable model calls require supported pricing and bounded request/output settings.
4. The gateway atomically reserves budget across the applicable limits so concurrent calls cannot all spend the same balance.
5. An allowed request proceeds; a request above an approval threshold waits for approval bound to the exact request and maximum price; an over-budget request is blocked.
6. The provider bills the account or a supported wallet adapter signs the payment.
7. Tavrel records the returned result and available usage/payment evidence, reconciles the reservation, and distinguishes estimated, confirmed, and uncertain spend.
8. Retries and ambiguous outcomes remain associated with the original operation. An uncertain charge does not release its reservation merely because a timeout occurred.

If a reliable maximum charge is unavailable, do not advertise a hard dollar cap for that route. Unknown pricing cannot be made safe merely by calling an estimate a quote.

## Hermes fit and coverage gate

The official provider guide documents a Custom Endpoint option. The plugin guide documents custom tools and pre-tool/model hooks. The configuration guide documents separate auxiliary models and direct subagent endpoints; all covered paid routes must use the same enforced account/task limits.

Verify main inference, auxiliary inference, subagents, fallback models, tools, background jobs, retries, and direct terminal/network access individually. Do not claim universal coverage from the existence of one hook.

Recommended first proof, not confirmed MVP: one model-provider adapter and one fixed-price paid-tool adapter, with task/account budgets, approval, and grounded spend records.

## Verified documentation findings

- [Hermes plugin system](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins): custom tools and directive hooks exist. Approval transport handles presentation and is not an authorization-policy API.
- [Hermes providers](https://hermes-agent.nousresearch.com/docs/integrations/providers): includes a Custom Endpoint option and separately configurable auxiliary routes.
- [Hermes configuration](https://hermes-agent.nousresearch.com/docs/user-guide/configuration): local token/cost analytics are described as lower-bound estimates excluding auxiliary calls, retries, fallbacks, and cache writes. These figures alone are insufficient for reliable billing enforcement.
- [Hermes billing lifecycle](https://hermes-agent.nousresearch.com/docs/developer-guide/billing-lifecycle): Nous account/remote-spending controls already include monthly-cap and authorization states. Research how proposed cross-provider/task controls differ before making novelty claims.

Official public Markdown sources were read from NousResearch/hermes-agent. Initial source reads failed DNS resolution; escalated read-only retries succeeded. No accounts were connected and no paid requests, transactions, or product installation were performed.

## Open questions

- Supported provider and tool for the first proof.
- Reliable maximum prices and authoritative billing evidence.
- Gateway deployment and credential isolation.
- Session/budget binding and complete route coverage.
- Existing competing plugins/gateways and user demand.
- Exact hackathon rules and eligible extension format.
