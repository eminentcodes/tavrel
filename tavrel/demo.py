"""Executable plugin-to-gateway proof; no Hermes model or paid service is run."""

import json
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
from threading import Thread

from hermes_plugin import TavrelClient, make_handlers

from .engine import Engine
from .server import Gateway
from .services import SERVICES


def run_demo(output_path=None):
    with TemporaryDirectory(prefix="tavrel-demo-") as temporary:
        engine = Engine(Path(temporary) / "ledger.sqlite3", SERVICES)
        operator_token = "demo_operator_" + secrets.token_urlsafe(32)
        gateway = Gateway(("127.0.0.1", 0), engine, operator_token, quiet=True)
        thread = Thread(target=gateway.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{gateway.server_address[1]}"
            operator = TavrelClient(url, operator_token)
            created = operator.request("POST", "/v1/operator/tasks", {"name": "Competitor research", "description": "Research competitors with an allowance and human approval for larger calls.", "limit_cents": 250, "threshold_cents": 100, "allowed_services": ["search_brief", "research_report"]})
            task_id = created["task"]["id"]
            agent = TavrelClient(url, created["task_token"])
            handlers = make_handlers(lambda: agent)

            def call(tool, arguments):
                response = json.loads(handlers[tool](arguments))
                if not response["ok"]:
                    raise RuntimeError(response["error"]["message"])
                return response["result"]

            print("TAVREL | Hermes plugin spending-control proof")
            print("Simulated services only. Plugin handlers are called directly; Hermes itself is not running.\n")
            print("Operator creates a $2.50 task allowance; purchases above $1 require approval.")
            brief_arguments = {"service": "search_brief", "query": "Find sources for a competitor comparison", "request_key": "competitor_brief"}
            brief = call("tavrel_purchase", brief_arguments)
            print(f"Plugin requests a $0.24 search brief -> {brief['status']}.")
            pending = call("tavrel_purchase", {"service": "research_report", "query": "Write the detailed competitor comparison", "request_key": "competitor_report"})
            print(f"Plugin requests a $1.60 report -> {pending['status']}; $1.60 is held before execution.")
            before = call("tavrel_status", {})
            approved = operator.request("POST", f"/v1/operator/requests/{pending['id']}/decision", {"decision": "approve", "expected_hash": pending["approval_hash"]})
            receipt = call("tavrel_receipt", {"request_id": pending["id"]})
            print(f"Operator approves the exact request -> {receipt['status']}; a simulated receipt is recorded.")
            blocked = call("tavrel_purchase", {"service": "research_report", "query": "Buy another research report", "request_key": "extra_report"})
            print(f"Plugin requests another $1.60 report -> {blocked['status']}: {blocked['reason']}")
            retried = call("tavrel_purchase", brief_arguments)
            after = call("tavrel_status", {})
            print(f"Retrying the original brief returns the same request: {retried['id'] == brief['id']}; no extra spend.")
            print(f"\nFinal task: ${after['task']['spent_cents'] / 100:.2f} simulated spend; ${after['task']['reserved_cents'] / 100:.2f} held; ${after['task']['available_cents'] / 100:.2f} remaining.")
            if not (brief["status"] == "settled" and pending["status"] == "pending_approval" and before["task"]["reserved_cents"] == 160 and approved["status"] == receipt["status"] == "settled" and blocked["status"] == "blocked" and retried["id"] == brief["id"] and after["task"]["spent_cents"] == 184 and after["task"]["reserved_cents"] == 0 and after["task"]["available_cents"] == 66):
                raise RuntimeError("The demo did not satisfy its spending-control assertions.")
            proof = {"mode": "simulation", "live_hermes_session": False, "paid_calls": 0, "wallet_payments": 0, "task": after["task"], "small_purchase": brief, "pending_purchase": pending, "approved_receipt": receipt, "over_budget_request": blocked, "idempotent_retry_same_id": retried["id"] == brief["id"], "events": engine.snapshot(task_id)["events"]}
            if output_path:
                path = Path(output_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(proof, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                print(f"Proof saved to {path} (no access credentials).")
            return proof
        finally:
            gateway.shutdown()
            gateway.server_close()
            thread.join(timeout=5)


def run_live_demo(output_path=None):
    """Exercise real public research with a zero-dollar allowance and no model."""
    with TemporaryDirectory(prefix="tavrel-live-demo-") as temporary:
        engine = Engine(Path(temporary) / "ledger.sqlite3")
        operator_token = "demo_operator_" + secrets.token_urlsafe(32)
        gateway = Gateway(("127.0.0.1", 0), engine, operator_token, quiet=True)
        thread = Thread(target=gateway.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{gateway.server_address[1]}"
            operator = TavrelClient(url, operator_token, timeout=25)
            created = operator.request("POST", "/v1/operator/tasks", {
                "name": "Free agent research", "limit_cents": 0, "threshold_cents": 0,
                "allowed_services": ["search_brief", "research_report", "summary"],
            })
            task_id = created["task"]["id"]
            agent = TavrelClient(url, created["task_token"], timeout=25)
            handlers = make_handlers(lambda: agent)

            def call(tool, arguments):
                response = json.loads(handlers[tool](arguments))
                if not response["ok"]:
                    raise RuntimeError(response["error"]["message"])
                return response["result"]

            def require_result(request):
                if request["status"] != "settled" or not request["output"]:
                    raise RuntimeError(request.get("reason") or "The free service did not return a verified result.")

            print("TAVREL | real free research | $0 allowance")
            print("Public APIs and local extraction. Plugin handlers are called directly; no Hermes model is running.\n")
            brief_arguments = {"service": "search_brief", "query": "topic:ai-agents", "request_key": "free_repositories"}
            brief = call("tavrel_purchase", brief_arguments)
            require_result(brief)
            print(f"GitHub: retrieved {len(brief['output']['sources'])} real repositories; recorded cost $0.00.")
            operator.request("PATCH", f"/v1/operator/tasks/{task_id}", {"require_approval": True})
            pending = call("tavrel_purchase", {
                "service": "research_report", "query": "autonomous AI agents", "request_key": "free_publications",
            })
            if pending["status"] != "pending_approval" or pending["output"] is not None:
                raise RuntimeError("The free publication request bypassed operator approval.")
            print("Crossref request waits for operator approval before contacting the provider.")
            approved = operator.request("POST", f"/v1/operator/requests/{pending['id']}/decision", {
                "decision": "approve", "expected_hash": pending["approval_hash"],
            })
            receipt = call("tavrel_receipt", {"request_id": pending["id"]})
            require_result(receipt)
            print(f"Crossref: retrieved {len(receipt['output']['sources'])} real publications after approval; recorded cost $0.00.")
            operator.request("PATCH", f"/v1/operator/tasks/{task_id}", {
                "require_approval": False, "allowed_services": ["search_brief", "summary"],
            })
            summary_text = " ".join(source["description"] for source in brief["output"]["sources"] if source["description"])
            if not summary_text:
                summary_text = " ".join(source["title"] + "." for source in receipt["output"]["sources"])
            summary = call("tavrel_purchase", {
                "service": "summary", "query": summary_text[:4000] or "No source descriptions were supplied.",
                "request_key": "free_extraction",
            })
            require_result(summary)
            blocked = call("tavrel_purchase", {
                "service": "research_report", "query": "Additional publication research", "request_key": "free_blocked",
            })
            retried = call("tavrel_purchase", brief_arguments)
            after = call("tavrel_status", {})
            task = after["task"]
            if not (approved["id"] == receipt["id"] and blocked["status"] == "blocked"
                    and retried["id"] == brief["id"] and task["spent_cents"] == 0
                    and task["reserved_cents"] == 0 and task["available_cents"] == 0
                    and all(item["billing"] == "free" and item["actual_cents"] == 0
                            for item in (brief, receipt, summary))):
                raise RuntimeError("The live demo did not satisfy its authorization and zero-cost assertions.")
            print("Removed service permission blocks a new request before execution.")
            print("An identical GitHub retry returns the saved result and retrieval evidence.")
            print("Final: $0.00 recorded cost, $0.00 held; no paid calls or payments.")
            proof = {
                "mode": "live_free", "live_hermes_session": False, "paid_calls": 0, "wallet_payments": 0,
                "note": "Actual free HTTP retrieval and local processing, not paid billing or settlement evidence.",
                "task": task, "repository_search": brief, "pending_publications": pending,
                "publication_receipt": receipt, "local_summary": summary, "blocked_request": blocked,
                "idempotent_retry_same_id": retried["id"] == brief["id"],
                "idempotent_retry_same_evidence": retried["evidence"] == brief["evidence"],
                "events": engine.snapshot(task_id)["events"],
            }
            if output_path:
                path = Path(output_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(proof, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                print(f"Proof saved to {path} (no access credentials).")
            return proof
        finally:
            gateway.shutdown()
            gateway.server_close()
            thread.join(timeout=5)

