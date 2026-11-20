"""Account CLI. Server credentials stay separate from task-scoped agent access."""

import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlencode

from .client import GatewayError, TavrelClient

from .engine import Engine, PolicyError
from .runtime import GatewayLock, operator_key, read_task_connection, save_task_connection
from .server import Gateway


def amount(value):
    if re.fullmatch(r"\d{1,7}(?:\.\d{1,2})?", value) is None:
        raise argparse.ArgumentTypeError("Use a dollar amount with at most two decimal places, such as 5 or 1.25.")
    whole, _, fractional = value.partition(".")
    result = int(whole) * 100 + int(fractional.ljust(2, "0") or "0")
    if result > 100_000_000:
        raise argparse.ArgumentTypeError("The amount is outside the supported range.")
    return result


def money(value):
    return "-" if value is None else f"${value / 100:.2f}"


def output(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def print_status(value):
    tasks = value.get("tasks", [])
    mode = value.get("mode") or (tasks[0].get("mode") if tasks else None)
    label = "SIMULATION" if mode == "simulation" else "FREE SERVICES"
    print(f"Tavrel | {label} | paid execution disabled")
    if value.get("account"):
        account = value["account"]
        print(f"Workspace: {money(account['limit_cents'])} allowance; {money(account['spent_cents'])} spent; {money(account['reserved_cents'])} held; {money(account['available_cents'])} available")
    if not tasks:
        print("No tasks yet. Create one with 'python -m tavrel task create'.")
    for task in tasks:
        print(f"\n{task['name']} [{task['id']}]{' (paused)' if task['paused'] else ''}")
        spend_label = "simulated spend" if mode == "simulation" else "recorded cost"
        print(f"  Budget {money(task['limit_cents'])}; {spend_label} {money(task['spent_cents'])}; held {money(task['reserved_cents'])}; available {money(task['available_cents'])}")
        approval = "Ask before every request" if task.get("require_approval") else f"Ask above {money(task['threshold_cents'])}"
        print(f"  {approval}; services: {', '.join(task['allowed_services']) or 'none'}")
    pending = [item for item in value.get("requests", []) if item["status"] == "pending_approval"]
    if pending:
        print("\nWaiting for operator approval:")
        for item in pending:
            print(f"  {item['id']} | {item['task_name']} | {item['service_name']} | maximum {money(item['quote_cents'])}")
    uncertain = [item for item in value.get("requests", []) if item["status"] == "uncertain"]
    if uncertain:
        print("\nUncertain requests retain their full reservations:")
        for item in uncertain:
            print(f"  {item['id']} | held {money(item['quote_cents'])}")


def print_receipt(value):
    print(f"{value['id']} | {value['status']} | {value['service_name']}")
    print(f"Task: {value['task_name']}")
    billing = value.get("billing", "simulated")
    print(f"Maximum: {money(value['quote_cents'])}; recorded cost: {money(value['actual_cents'])}; billing: {billing}")
    if value.get("reason"):
        print(value["reason"])
    if value.get("output"):
        output(value["output"])
    if value.get("evidence"):
        print(f"Evidence: {value['evidence']['kind']} | {value['evidence'].get('reference', 'no reference')}")


def parser():
    root = argparse.ArgumentParser(prog="tavrel", description="Agent payments, spending rules, wallet signing, and finalized receipts.")
    root.add_argument("--url", default="http://127.0.0.1:8787", help="Gateway origin for CLI calls")
    root.add_argument("--data-dir", default=".tavrel", help="Local operator data directory; never share it with an agent for live use")
    commands = root.add_subparsers(dest="command")
    serve = commands.add_parser("serve", help="Start the loopback gateway")
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument("--quiet", action="store_true")
    status = commands.add_parser("status", help="Show workspace/task budgets and pending requests")
    status.add_argument("--task", dest="task_id")
    status.add_argument("--json", action="store_true")
    services = commands.add_parser("services", help="List connected services, billing modes, and fixed prices")
    services.add_argument("--json", action="store_true")
    account = commands.add_parser("account", help="Set the workspace allowance")
    account.add_argument("--budget", type=amount, required=True)
    account.add_argument("--json", action="store_true")
    task = commands.add_parser("task", help="Create tasks and manage their policies or restricted tokens")
    task_commands = task.add_subparsers(dest="task_command", required=True)
    create = task_commands.add_parser("create")
    create.add_argument("name")
    create.add_argument("--budget", required=True, type=amount)
    create.add_argument("--approval", type=amount, default=100)
    create.add_argument("--allow", default="search_brief,research_report,summary", help="Comma-separated supported service IDs")
    create.add_argument("--description", default="")
    create.add_argument("--require-approval", action="store_true", help="Ask before every request, including free services")
    create.add_argument("--json", action="store_true")
    policy = task_commands.add_parser("policy")
    policy.add_argument("task_id")
    policy.add_argument("--budget", type=amount)
    policy.add_argument("--approval", type=amount)
    policy.add_argument("--allow")
    policy.add_argument("--name")
    policy.add_argument("--description")
    policy.add_argument("--require-approval", action=argparse.BooleanOptionalAction, default=None, help="Require approval for every request, or return to the price threshold")
    pause = policy.add_mutually_exclusive_group()
    pause.add_argument("--pause", dest="paused", action="store_const", const=True, default=None)
    pause.add_argument("--resume", dest="paused", action="store_const", const=False)
    policy.add_argument("--json", action="store_true")
    token = task_commands.add_parser("token", help="Rotate and save a task token without printing it")
    token.add_argument("task_id")
    token.add_argument("--json", action="store_true")
    ledger = commands.add_parser("ledger", help="List durable requests, including pending and blocked attempts")
    ledger.add_argument("--task", dest="task_id")
    ledger.add_argument("--limit", type=int, default=20)
    ledger.add_argument("--offset", type=int, default=0)
    ledger.add_argument("--json", action="store_true")
    inspect = commands.add_parser("inspect", help="Review an exact request and its receipt")
    inspect.add_argument("request_id")
    inspect.add_argument("--json", action="store_true")
    for name in ("approve", "deny"):
        decision = commands.add_parser(name, help=f"{name.capitalize()} an exact pending purchase as the operator")
        decision.add_argument("request_id")
        decision.add_argument("--confirm", help="Exact approval_hash from inspection, for an explicitly reviewed scripted decision")
        decision.add_argument("--json", action="store_true")
    reconcile = commands.add_parser("reconcile", help="Record an operator's observed cost for an uncertain request without retrying it")
    reconcile.add_argument("request_id")
    reconcile.add_argument("--cost", required=True, type=amount, help="Observed dollar cost, within the original maximum; free services require 0")
    reconcile.add_argument("--reference", required=True, help="Reference to the evidence reviewed by the operator")
    reconcile.add_argument("--note", required=True, help="Explain the observed outcome; this is an operator attestation")
    reconcile.add_argument("--confirm", help="Exact approval_hash from inspection")
    reconcile.add_argument("--json", action="store_true")
    request = commands.add_parser("request", help="Exercise a task-scoped purchase from its saved connection file")
    request.add_argument("task_id")
    request.add_argument("--service", required=True)
    request.add_argument("--query", required=True)
    request.add_argument("--key", required=True, help="Stable idempotency key; reuse it for a retry of the same request")
    request.add_argument("--json", action="store_true")
    payment = commands.add_parser("payment", help="Native zkVerify Volta tVFY payment requests; send with your wallet in the app")
    payment_commands = payment.add_subparsers(dest="payment_command", required=True)
    payment_status = payment_commands.add_parser("status")
    payment_status.add_argument("--task", dest="task_id")
    payment_account = payment_commands.add_parser("account")
    payment_account.add_argument("--budget", required=True, help="Exact decimal tVFY allowance, not a deposit")
    payment_policy = payment_commands.add_parser("policy")
    payment_policy.add_argument("task_id")
    payment_policy.add_argument("--sender", required=True, help="Public native Substrate signing account; never a private key")
    payment_policy.add_argument("--budget", required=True)
    payment_policy.add_argument("--approval", required=True)
    payment_policy.add_argument("--per-payment", required=True)
    payment_policy.add_argument("--recipient", action="append", default=[], help="Approved NAME=SS58_ADDRESS; repeat for each recipient")
    payment_policy.add_argument("--require-approval", action="store_true")
    payment_prepare = payment_commands.add_parser("prepare")
    payment_prepare.add_argument("task_id")
    payment_prepare.add_argument("--recipient", required=True)
    payment_prepare.add_argument("--amount", required=True)
    payment_prepare.add_argument("--purpose", required=True)
    payment_prepare.add_argument("--key", required=True)
    payment_task = payment_commands.add_parser("task")
    payment_task.add_argument("task_id")
    payment_task.add_argument("--file", required=True, help="JSON array of recipient/amount/purpose instructions")
    payment_task.add_argument("--key", required=True)
    for name in ("inspect", "approve", "deny", "export"):
        action = payment_commands.add_parser(name)
        action.add_argument("payment_id")
        if name != "inspect":
            action.add_argument("--confirm", help="Exact approval_hash from payment inspect for a reviewed scripted operation")
    return root


def run(args):
    directory = Path(args.data_dir).resolve()
    if args.command == "payment":
        return run_payment(args, directory)
    if args.command in (None, "serve"):
        port = getattr(args, "port", 8787)
        if not 0 <= port <= 65535:
            raise RuntimeError("Choose a port between 0 and 65535.")
        lock = GatewayLock(directory)
        gateway = None
        try:
            key = operator_key(directory, create=True)
            engine = Engine(directory / "ledger.sqlite3")
            gateway = Gateway(("127.0.0.1", port), engine, key, getattr(args, "quiet", False))
            engine.recover_interrupted()
            print(f"Tavrel gateway ready at http://127.0.0.1:{gateway.server_address[1]}", flush=True)
            if not gateway.wallet_auth.configured():
                print("Connect your first wallet in the app and sign the login message.", flush=True)
            print("Native Volta payments enabled. Sign transfers in your wallet; Tavrel verifies finalized chain receipts.", flush=True)
            print(f"CLI access key saved at {directory / 'operator.key'}; keep it separate from agent connections.", flush=True)
            print("Use another terminal for 'python -m tavrel task create' and other operator commands.", flush=True)
            try:
                gateway.serve_forever(poll_interval=0.2)
            except KeyboardInterrupt:
                print("\nStopping the Tavrel gateway.")
        finally:
            if gateway:
                gateway.server_close()
            lock.close()
        return 0
    if args.command == "request":
        connection = read_task_connection(directory, args.task_id)
        client = TavrelClient(connection["gateway_url"], connection["task_token"])
        result = client.request("POST", "/v1/agent/requests", {"service": args.service, "payload": {"query": args.query}, "request_key": args.key})
        output(result) if args.json else print_receipt(result)
        return 0
    client = TavrelClient(args.url, operator_key(directory))
    if args.command == "status":
        suffix = "?" + urlencode({"task_id": args.task_id}) if args.task_id else ""
        result = client.request("GET", "/v1/operator/status" + suffix)
        output(result) if args.json else print_status(result)
    elif args.command == "services":
        result = client.request("GET", "/v1/operator/services")
        if args.json:
            output(result)
        else:
            print(f"CONNECTED SERVICES | {result['mode']} | paid execution disabled")
            for service in result["services"]:
                print(f"{service['id']:<20} {money(service['price_cents'])} fixed | {service['billing']} | {service['description']}")
    elif args.command == "account":
        result = client.request("PATCH", "/v1/operator/account", {"limit_cents": args.budget})
        output(result) if args.json else print_status(result)
    elif args.command == "task":
        if args.task_command == "create":
            result = client.request("POST", "/v1/operator/tasks", {"name": args.name, "limit_cents": args.budget, "threshold_cents": args.approval, "allowed_services": [item for item in args.allow.split(",") if item], "description": args.description, "require_approval": args.require_approval})
            task = result["task"]
            connection_path = save_task_connection(directory, task["id"], result["task_token"], args.url)
            safe_result = {"task": task, "connection_file": str(connection_path)}
            if args.json:
                output(safe_result)
            else:
                print_status({"tasks": [task]})
                print(f"\nRestricted task connection saved to {connection_path}. Its token was not printed.")
        elif args.task_command == "token":
            result = client.request("POST", f"/v1/operator/tasks/{args.task_id}/token", {})
            connection_path = save_task_connection(directory, args.task_id, result["task_token"], args.url)
            safe_result = {"task_id": args.task_id, "connection_file": str(connection_path), "rotated": True}
            output(safe_result) if args.json else print(f"Task token rotated and saved to {connection_path}. Update Hermes with this restricted token.")
        else:
            changes = {}
            for arg_name, field_name in (("budget", "limit_cents"), ("approval", "threshold_cents"), ("name", "name"), ("description", "description"), ("paused", "paused"), ("require_approval", "require_approval")):
                if getattr(args, arg_name) is not None:
                    changes[field_name] = getattr(args, arg_name)
            if args.allow is not None:
                changes["allowed_services"] = [item for item in args.allow.split(",") if item]
            if not changes:
                raise RuntimeError("Specify at least one policy change.")
            result = client.request("PATCH", f"/v1/operator/tasks/{args.task_id}", changes)
            output(result) if args.json else print_status({"tasks": [result]})
    elif args.command == "ledger":
        query = {"limit": args.limit, "offset": args.offset}
        if args.task_id:
            query["task_id"] = args.task_id
        result = client.request("GET", "/v1/operator/requests?" + urlencode(query))
        if args.json:
            output(result)
        else:
            print(f"REQUEST LEDGER | {result['mode']} | {result['total']} total; offset {result['offset']}")
            for request in result["requests"]:
                print(f"{request['id']} | {request['status']:<16} | {request['billing']} | {request['service_name']:<16} | quote {money(request['quote_cents'])} | recorded {money(request['actual_cents'])} | {request['task_name']}")
    elif args.command == "inspect":
        result = client.request("GET", f"/v1/operator/requests/{args.request_id}")
        if args.json:
            output(result)
        else:
            print_receipt(result)
            print("Exact input:")
            output(result["payload"])
            print(f"Approval fingerprint: {result['approval_hash']}")
    elif args.command in ("approve", "deny"):
        request = client.request("GET", f"/v1/operator/requests/{args.request_id}")
        if request["status"] != "pending_approval":
            raise RuntimeError("This request is no longer waiting for approval.")
        if args.confirm is not None:
            if args.confirm != request["approval_hash"]:
                raise RuntimeError("Confirmation does not match this exact request and maximum price.")
        else:
            print_receipt(request)
            print("Exact input:")
            output(request["payload"])
            if args.json or not sys.stdin.isatty():
                raise RuntimeError("Review the request with 'inspect', then pass its exact approval_hash with --confirm, or run this command in an interactive operator terminal.")
            confirmation = input(f"Type {args.command.upper()} to {args.command} this exact purchase: ").strip()
            if confirmation != args.command.upper():
                print("No decision submitted.")
                return 0
        result = client.request("POST", f"/v1/operator/requests/{args.request_id}/decision", {"decision": args.command, "expected_hash": request["approval_hash"]})
        output(result) if args.json else print_receipt(result)
    elif args.command == "reconcile":
        request = client.request("GET", f"/v1/operator/requests/{args.request_id}")
        if request["status"] != "uncertain":
            raise RuntimeError("Only uncertain requests can be reconciled.")
        if args.cost > request["quote_cents"] or (request["billing"] == "free" and args.cost != 0):
            raise RuntimeError("The observed cost must fit the original maximum; free services require 0.")
        if args.confirm is not None:
            if args.confirm != request["approval_hash"]:
                raise RuntimeError("Confirmation does not match this exact request and maximum price.")
        else:
            print_receipt(request)
            print("Exact input:")
            output(request["payload"])
            print(f"Operator attestation: cost {money(args.cost)}; reference {args.reference}; note {args.note}")
            if args.json or not sys.stdin.isatty():
                raise RuntimeError("Review with 'inspect', then pass its exact approval_hash with --confirm, or use an interactive operator terminal.")
            if input("Type RECONCILE to record this attestation without retrying work: ").strip() != "RECONCILE":
                print("No reconciliation submitted.")
                return 0
        result = client.request("POST", f"/v1/operator/requests/{args.request_id}/reconcile", {"actual_cents": args.cost, "reference": args.reference, "note": args.note, "expected_hash": request["approval_hash"]})
        output(result) if args.json else print_receipt(result)
    return 0


def run_payment(args, directory):
    if args.payment_command in ("prepare", "task"):
        connection = read_task_connection(directory, args.task_id)
        client = TavrelClient(connection["gateway_url"], connection["task_token"])
        if args.payment_command == "prepare":
            result = client.request("POST", "/v1/agent/payments/prepare", {
                "recipient": args.recipient, "amount": args.amount,
                "purpose": args.purpose, "request_key": args.key})
        else:
            source = Path(args.file)
            if source.stat().st_size > 32_768:
                raise RuntimeError("Payment instruction files must be at most 32 KB.")
            instructions = json.loads(source.read_text(encoding="utf-8"))
            result = client.request("POST", "/v1/agent/payments/task", {"task_key": args.key, "payments": instructions})
        output(result)
        return 0
    client = TavrelClient(args.url, operator_key(directory))
    base = "/v1/operator/payments"
    if args.payment_command == "status":
        suffix = "?" + urlencode({"task_id": args.task_id}) if args.task_id else ""
        result = client.request("GET", base + "/status" + suffix)
    elif args.payment_command == "account":
        result = client.request("PATCH", base + "/account", {"budget": args.budget})
    elif args.payment_command == "policy":
        recipients = {}
        for item in args.recipient:
            label, separator, address = item.partition("=")
            if not separator or label in recipients:
                raise RuntimeError("Provide unique recipient names as NAME=SS58_ADDRESS.")
            recipients[label] = address
        result = client.request("PATCH", base + "/policies/" + args.task_id, {
            "sender": args.sender, "budget": args.budget, "approval": args.approval,
            "per_payment": args.per_payment, "recipients": recipients,
            "require_approval": args.require_approval})
    else:
        if re.fullmatch(r"pay_[a-f0-9]{16}", args.payment_id) is None:
            raise RuntimeError("Provide a payment ID returned by Tavrel.")
        path = base + "/" + args.payment_id
        payment = client.request("GET", path)
        if args.payment_command == "inspect":
            output(payment)
            return 0
        if args.confirm is not None:
            if args.confirm != payment["approval_hash"]:
                raise RuntimeError("Confirmation does not match the exact payment intent and policy version.")
        else:
            output(payment)
            if not sys.stdin.isatty():
                raise RuntimeError("Inspect the payment first, then pass its exact approval_hash with --confirm, or use an interactive operator terminal.")
            try:
                confirmation = input(f"Type {args.payment_command.upper()} for this exact payment: ").strip()
            except EOFError:
                raise RuntimeError("No confirmation was received. No action submitted.") from None
            if confirmation != args.payment_command.upper():
                print("No action submitted.")
                return 0
        if args.payment_command == "export":
            result = client.request("POST", path + "/export", {"expected_hash": payment["approval_hash"]})
        else:
            result = client.request("POST", path + "/decision", {"decision": args.payment_command, "expected_hash": payment["approval_hash"]})
    output(result)
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return run(args)
    except (GatewayError, PolicyError, RuntimeError) as exc:
        print(f"Tavrel: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError):
        print("Tavrel: could not read/write the local runtime files or bind the gateway. Verify the data directory, connection file, and port.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

