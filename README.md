# Tavrel

Give a Hermes task a spending allowance, require approval for larger purchases, and keep a ledger of every attempt. Tavrel includes a native plugin, a local budget gateway, and an operator CLI.

The default gateway uses **real free services**: GitHub repository search, Crossref publication metadata, and local text extraction. Paid execution is disabled. A separate simulation demonstrates nonzero spending and budget limits. An allowance is a policy limit, not a deposit; Hermes model billing and tools outside Tavrel are outside its coverage.

## Try real research for $0

Requires Python 3.11 or newer and internet access. No account, API key, payment, or Hermes installation is required:

```powershell
python -m tavrel demo --live --output artifacts/live-demo-proof.json
```

This retrieves five repository matches from GitHub, waits for request-bound operator approval before retrieving Crossref publications, extracts text locally, blocks a removed service permission, and reuses the original result on an identical retry. Expected final recorded cost and held amount: **$0.00**. Results carry the actual request endpoint, retrieval time, HTTP status, response hash, and provider request reference where available.

Repository descriptions and publication metadata are provider data. The publication digest includes abstracts only when supplied by the publisher and does not retrieve full texts. The local summary extracts the first three sentences; it does not invoke a model. Free APIs can rate-limit or fail, and those failures stay visible rather than becoming simulated results.

The [live proof](artifacts/live-demo-proof.json) and [Hermes loader proof](artifacts/hermes-loader-proof.json) contain real free HTTP evidence. The latter also verifies actual Hermes discovery and registry dispatch. Neither proof runs a language-model session or establishes paid billing or payment settlement.

## Try simulated spending

No runtime dependencies, account, API key, internet access, or Hermes installation are needed for the separate spending simulation:

```powershell
python -m tavrel demo --output artifacts/demo-proof.json
```

The demo creates a temporary gateway, invokes the plugin's tool handlers over HTTP, and checks the full workflow:

1. Create a $2.50 task with approval required above $1.
2. Settle a $0.24 search brief automatically.
3. Hold a $1.60 report while waiting for operator approval.
4. Approve that exact report and record its simulated receipt.
5. Block another $1.60 report before execution.
6. Retry the original brief and return the same receipt without another charge.

Expected final balance: **$1.84 simulated spend, $0 held, $0.66 available**. The saved proof contains no access tokens. This exercises the plugin handlers; it does not run a Hermes model session.

## Run the operator workflow

Start the gateway in one terminal:

```powershell
python -m tavrel serve
```

In another terminal, from the same project directory:

```powershell
python -m tavrel services
$tavrelTask = python -m tavrel task create "Agent research" --budget 0 --approval 0 --require-approval --allow "search_brief,research_report,summary" --json | ConvertFrom-Json
$tavrelPending = python -m tavrel request $tavrelTask.task.id --service search_brief --query "topic:ai-agents" --key repository_research --json | ConvertFrom-Json
python -m tavrel inspect $tavrelPending.id
python -m tavrel approve $tavrelPending.id
python -m tavrel status
python -m tavrel ledger --task $tavrelTask.task.id
```

The task has a zero allowance and requires approval before every request. GitHub is contacted only after the operator approves the exact query. To permit later free requests automatically, run `python -m tavrel task policy TASK_ID --no-require-approval`. Publication requests use `--service research_report --query "autonomous AI agents"`; local extraction uses `--service summary` with the text as the query.

Approval prints the exact input and maximum cost and asks you to type `APPROVE` in an interactive terminal. A scripted decision requires `--confirm` with the exact `approval_hash` obtained from inspection. A fingerprint identifies a request; operator authentication still authorizes the action. `deny` releases a pending reservation.

The default free workspace allowance is **$0** across all tasks; the simulation defaults to $25. Change an allowance with `python -m tavrel account --budget 10`; this changes policy and does not enable paid services. Pause a task with `python -m tavrel task policy TASK_ID --pause`; resume with `--resume`. Use `--allow ""` to remove all service permissions. Task-token rotation uses `python -m tavrel task token TASK_ID` and revokes the previous token for subsequent requests.

All CLI amounts are dollars with at most two decimal places; the gateway stores integer cents. Threshold-based approval is required strictly **above** the threshold. A purchase equal to the threshold can proceed automatically if policy and allowances permit it. `--require-approval` instead asks before every request, including zero-cost requests.

Runtime files live in `.tavrel/`: the SQLite ledger, `operator.key`, a process lock, and restricted task connection files. Tokens are saved locally rather than printed. Stop the gateway with Ctrl+C and start it again to reuse the ledger. `--data-dir PATH` and `--url ORIGIN` go before the subcommand; `serve --port PORT` selects a different port.

To operate the spending simulation, start `python -m tavrel --data-dir .tavrel/simulation serve --mode simulation` and use `--data-dir .tavrel/simulation` before each CLI subcommand. Modes have separate ledgers: a simulated ledger cannot be reopened as free, or vice versa. For an existing pre-extension `.tavrel` simulation ledger, keep using `serve --mode simulation`, or start free mode with a separate `--data-dir .tavrel/free`. Legacy migration preserves existing spend, holds, task tokens, and simulated receipt labels.

## Install the Hermes plugin

The distributable plugin is just `hermes_plugin/__init__.py` and `hermes_plugin/plugin.yaml`, using only Python's standard library. Its manifest and `register(ctx)` use the [documented Hermes interface](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins). Actual discovery, all three registry-dispatched tools, and `/budget` pass against unmodified official Hermes revision `e0f07847b8f38ac72890cf98e0d344c372ae7ee8`. A model-driven Hermes session remains unverified.

The same two files are available in [the plugin archive](artifacts/tavrel-hermes-plugin.zip). Extract its `tavrel/` directory into the active profile's user-plugin directory, or copy the source files as shown below. Rebuild the archive after plugin changes with `python scripts/package_plugin.py`.

After creating a task, copy the two plugin files into the active Hermes profile's user-plugin directory. For the default profile on Windows:

```powershell
$tavrelPluginDirectory = Join-Path $env:USERPROFILE ".hermes/plugins/tavrel"
New-Item -ItemType Directory -Force -Path $tavrelPluginDirectory | Out-Null
Copy-Item -LiteralPath .\hermes_plugin\__init__.py -Destination $tavrelPluginDirectory
Copy-Item -LiteralPath .\hermes_plugin\plugin.yaml -Destination $tavrelPluginDirectory
$tavrelConnection = Get-Content -LiteralPath $tavrelTask.connection_file -Raw | ConvertFrom-Json
$env:TAVREL_URL = $tavrelConnection.gateway_url
$env:TAVREL_TASK_TOKEN = $tavrelConnection.task_token
hermes plugins enable tavrel
```

Restart the Hermes gateway with these environment variables available to its process. If you use a different Hermes profile or operating system, use that profile's `plugins/tavrel/` directory. The Tavrel gateway must keep running. Environment changes in a terminal do not update an already-running Hermes process.

The plugin exposes:

| Tool or command | Purpose |
| --- | --- |
| `tavrel_status` | Read the configured task's allowance, policy, and recent requests. |
| `tavrel_purchase` | Request a connected service using an exact query and stable request key. |
| `tavrel_receipt` | Read one request's status and result within the configured task. |
| `/budget` | Show the task's current balance in Hermes. |

Example instruction for a Hermes session: "Check Tavrel's budget and service catalog. Search GitHub for agent frameworks with search_brief, and retrieve publication metadata with research_report. Cite the supplied sources. If a request needs approval, report its ID and wait. Reuse the same request key and exact arguments on retries."

The task token is configured once per Hermes process. Sessions in that process share that task; per-session task selection is not implemented. Operators approve from the companion CLI. The plugin has no approval or policy-editing tool.

## What the limits enforce

Both task and workspace allowances include settled spend **plus reservations**. SQLite transactions atomically reserve the maximum before execution. Pending approvals consume available allowance immediately. Approval cannot increase the budget or override a removed service permission, a pause, or a changed price.

A stable request key is unique within its task. Retrying identical arguments returns the existing request; different arguments conflict. Failed, denied, blocked, pending, executing, and uncertain requests are not new purchases. Use `tavrel_receipt` to check their status. A new key creates a separate purchase attempt.

Confirmed no-charge failures release their reservation; the free adapters explicitly report connection failures and rate limits as no-charge failures. Invalid receipts and unexpected exceptions retain the maximum as `uncertain`. At startup, interrupted `executing` requests become uncertain without automatic reexecution. A request interrupted before execution can resume through an identical retry, after another policy check.

An operator can reconcile an uncertain request after reviewing its outcome:

```powershell
python -m tavrel inspect REQUEST_ID
python -m tavrel reconcile REQUEST_ID --cost 0 --reference "Reviewed local processing log" --note "The local operation had no external charge; its output could not be confirmed."
```

The CLI asks for `RECONCILE` in an interactive operator terminal. A scripted action requires the exact `approval_hash` from inspection via `--confirm`. The recorded cost must fit the original reserved maximum; free services require zero. Reconciliation releases the unused reservation once, preserves an explicit **operator attestation**, and leaves the service output unverified. It never retries work, creates a synthetic successful result, or claims independently verified provider billing. Agent tokens cannot reconcile requests.

The HTTP gateway binds to loopback, checks Host and browser Origin, and uses separate operator and task bearer tokens. Task tokens cannot read another task, approve or reconcile requests, or change allowances. Clients refuse redirects and bypass environment proxies for loopback calls. Free-provider requests use an HTTPS origin/path allowlist, bounded responses, no authentication, and no redirects.

This is an application-level local proof. A Hermes process with terminal or filesystem access under the operator's Windows account can read operator files or modify the ledger. Keeping the operator key out of tool arguments does not create operating-system isolation. A future live deployment needs a separately isolated gateway, exclusive provider credentials, verified adapter price ceilings, and authoritative billing reconciliation. The local simulators perform no signing or settlement; receipts are synthetic evidence.

## Verify

```powershell
python -W error::ResourceWarning -m unittest discover -s tests -v
python -m tavrel demo --output artifacts/demo-proof.json
python -m tavrel demo --live --output artifacts/live-demo-proof.json
```

Tests cover concurrent task/workspace limits, retry execution, request-bound approval, approval of free requests, policy changes, uncertain outcomes, bounded reconciliation, ledger-mode migration, restart recovery, HTTP authorization, free-provider contracts, plugin registration, and CLI subprocesses. Automated service fixtures stay local; the live demo is a separate explicit network check.

With a Hermes source checkout and its dependencies available in the current Python environment, reproduce actual loader verification using:

```powershell
python scripts/verify_hermes.py --hermes-source PATH_TO_HERMES --live --output artifacts/hermes-loader-proof.json
```

For the cached checkout used here, add `--hermes-source .cache/hermes-agent --hermes-deps .cache/hermes-deps`. Omit `--live` for offline registry verification with local extraction. The script creates a temporary Hermes profile, copies only the two plugin files, loads the actual upstream manager, dispatches registered tools, and invokes `/budget`. It does not start a model or alter the operator's existing Hermes profile.

See [the project plan](projectplan.md), [progress log](agent.md), and [verification record](artifacts/verification.md) for milestone status. ARCANUM supplied conceptual inspiration; no ARCANUM source code or assets were copied into this implementation. Research snapshots retain their upstream provenance and are not part of the plugin distribution.
