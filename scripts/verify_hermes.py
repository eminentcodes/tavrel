"""Verify discovery and tool dispatch in an unmodified Hermes source checkout.

No model is invoked. --live adds the two unauthenticated public API requests.
Hermes settings, plugin installation, and the ledger use a temporary profile.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread


ROOT = Path(__file__).resolve().parents[1]


def verify(source, dependencies=None, live=False, output_path=None):
    source = Path(source).resolve()
    if not (source / "hermes_cli" / "plugins.py").is_file():
        raise RuntimeError("--hermes-source must be a Hermes Agent source checkout.")
    sys.path.insert(0, str(source))
    if dependencies:
        sys.path.insert(0, str(Path(dependencies).resolve()))
    sys.path.insert(0, str(ROOT))
    from hermes_plugin import GatewayError, TavrelClient
    from tavrel.engine import Engine
    from tavrel.server import Gateway

    with TemporaryDirectory(prefix="tavrel-hermes-verify-") as temporary:
        directory = Path(temporary)
        profile = directory / "profile"
        plugin_directory = profile / "plugins" / "tavrel"
        plugin_directory.mkdir(parents=True)
        bundled = directory / "empty-bundled-plugins"
        bundled.mkdir()
        for name in ("__init__.py", "plugin.yaml"):
            shutil.copyfile(ROOT / "hermes_plugin" / name, plugin_directory / name)
        (profile / "config.yaml").write_text(
            "plugins:\n  enabled: [tavrel]\n  disabled: []\n", encoding="utf-8")

        engine = Engine(directory / "ledger.sqlite3")
        created = engine.create_task("Hermes free research verification", 0, 0,
                                     ["search_brief", "research_report", "summary"])
        task_id = created["task"]["id"]
        operator_token = "hermes_verification_operator_only"
        gateway = Gateway(("127.0.0.1", 0), engine, operator_token, quiet=True)
        thread = Thread(target=gateway.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{gateway.server_address[1]}"
        environment = {
            "HERMES_HOME": str(profile), "HERMES_BUNDLED_PLUGINS": str(bundled),
            "HERMES_ENABLE_PROJECT_PLUGINS": "0",
            "TAVREL_URL": url, "TAVREL_TASK_TOKEN": created["task_token"],
        }
        previous = {key: os.environ.get(key) for key in environment}
        os.environ.update(environment)
        manager = None
        try:
            # These are the actual upstream loader and registry, without test doubles.
            from hermes_cli.plugins import get_plugin_command_handler, get_plugin_manager
            from tools.registry import registry
            manager = get_plugin_manager()
            manager.discover_and_load()
            plugins = [item for item in manager.list_plugins() if item["name"] == "tavrel"]
            if len(plugins) != 1 or not plugins[0]["enabled"] or plugins[0].get("error"):
                raise RuntimeError("Hermes did not load Tavrel successfully: " + json.dumps(plugins))
            names = sorted(name for name in registry.get_all_tool_names() if name.startswith("tavrel_"))
            if names != ["tavrel_purchase", "tavrel_receipt", "tavrel_status"]:
                raise RuntimeError("Hermes did not register all three Tavrel tools.")

            def call(name, arguments):
                raw = registry.dispatch(name, arguments, scope=manager.scope_key,
                                        session_id="tavrel-verification-session", task_id="hermes-runtime-task")
                value = json.loads(raw)
                if value.get("ok") is not True:
                    raise RuntimeError("Hermes tool call failed: " + json.dumps(value))
                return value["result"]

            def require_result(request):
                if request["status"] != "settled" or not request["output"]:
                    raise RuntimeError(request.get("reason") or "The service did not produce a settled result.")
                if request["billing"] != "free" or request["actual_cents"] != 0:
                    raise RuntimeError("The verification violated its zero-cost constraint.")

            status = call("tavrel_status", {})
            if status["task"]["id"] != task_id:
                raise RuntimeError("The Hermes plugin used the wrong Tavrel task.")
            summary_arguments = {"service": "summary", "query": "Budgets are deterministic. Approval stays with the operator. Receipts are durable. Fourth sentence.", "request_key": "hermes_summary"}
            summary = call("tavrel_purchase", summary_arguments)
            require_result(summary)
            retried = call("tavrel_purchase", summary_arguments)
            if retried["id"] != summary["id"] or retried["evidence"] != summary["evidence"]:
                raise RuntimeError("Hermes retry did not reuse the original receipt.")

            operator = TavrelClient(url, operator_token, timeout=25)
            operator.request("PATCH", f"/v1/operator/tasks/{task_id}", {"require_approval": True})
            pending_arguments = {"service": "research_report" if live else "summary",
                                 "query": "autonomous AI agents" if live else "Operator approval precedes execution.",
                                 "request_key": "hermes_approval"}
            pending = call("tavrel_purchase", pending_arguments)
            if pending["status"] != "pending_approval" or pending["output"] is not None:
                raise RuntimeError("Hermes request bypassed approval.")
            try:
                TavrelClient(url, created["task_token"]).request(
                    "POST", f"/v1/operator/requests/{pending['id']}/decision",
                    {"decision": "approve", "expected_hash": pending["approval_hash"]})
            except GatewayError as error:
                if error.status != 403:
                    raise
            else:
                raise RuntimeError("A task token authorized operator approval.")
            operator.request("POST", f"/v1/operator/requests/{pending['id']}/decision",
                             {"decision": "approve", "expected_hash": pending["approval_hash"]})
            approved = call("tavrel_receipt", {"request_id": pending["id"]})
            require_result(approved)

            repository = None
            if live:
                operator.request("PATCH", f"/v1/operator/tasks/{task_id}", {"require_approval": False})
                repository = call("tavrel_purchase", {"service": "search_brief", "query": "topic:ai-agents", "request_key": "hermes_repositories"})
                require_result(repository)

            operator.request("PATCH", f"/v1/operator/tasks/{task_id}", {"require_approval": False, "allowed_services": ["summary"]})
            blocked = call("tavrel_purchase", {"service": "research_report", "query": "Removed permission", "request_key": "hermes_blocked"})
            if blocked["status"] != "blocked":
                raise RuntimeError("Removed service permission was not enforced.")
            command = get_plugin_command_handler("budget")
            if command is None:
                raise RuntimeError("Hermes did not register /budget.")
            budget = command("", session_id="tavrel-verification-session")
            if "available $0.00" not in budget:
                raise RuntimeError("The Hermes /budget command returned an unexpected balance.")
            after = call("tavrel_status", {})
            if after["task"]["spent_cents"] or after["task"]["reserved_cents"]:
                raise RuntimeError("The Hermes verification recorded a nonzero cost or hold.")
            revision = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                                      capture_output=True, text=True, timeout=10, check=True).stdout.strip()
            proof = {
                "mode": "live_free", "hermes_revision": revision,
                "actual_hermes_loader": True, "actual_hermes_registry_dispatch": True,
                "live_public_api_calls": 2 if live else 0,
                "live_hermes_model_session": False, "model_calls": 0,
                "paid_calls": 0, "wallet_payments": 0,
                "plugin": {key: plugins[0][key] for key in ("name", "version", "source", "enabled", "tools", "error") if key in plugins[0]},
                "plugin_files_sha256": {name: hashlib.sha256((plugin_directory / name).read_bytes()).hexdigest()
                                        for name in ("__init__.py", "plugin.yaml")},
                "registered_tools": names, "budget_command": budget,
                "task": after["task"], "summary_receipt": summary,
                "pending_request": pending, "approved_receipt": approved,
                "repository_receipt": repository, "blocked_request": blocked,
                "idempotent_retry_same_receipt": True, "agent_approval_rejected": True,
                "note": "Real Hermes discovery and registry execution with an isolated profile. No language model ran; free HTTP evidence does not prove paid settlement.",
            }
            serialized = json.dumps(proof, indent=2, ensure_ascii=False) + "\n"
            if created["task_token"] in serialized or operator_token in serialized:
                raise RuntimeError("The proof contains a credential.")
            if output_path:
                target = Path(output_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(serialized, encoding="utf-8")
            print(f"Hermes {revision[:12]} loaded Tavrel and registered all three tools and /budget.")
            print("Registry dispatch, operator approval, removed permissions, and identical retry passed.")
            print(f"Free public API calls: {proof['live_public_api_calls']}; model calls: 0; recorded cost: $0.00.")
            if output_path:
                print(f"Sanitized proof saved to {output_path}.")
            return proof
        finally:
            if manager:
                manager.unload()
            gateway.shutdown()
            gateway.server_close()
            thread.join(timeout=5)
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-source", default=str(ROOT / ".cache" / "hermes-agent"))
    parser.add_argument("--hermes-deps", help="Optional directory of locally installed Hermes dependencies")
    parser.add_argument("--live", action="store_true", help="Make two free public GitHub/Crossref requests through Hermes")
    parser.add_argument("--output", default=str(ROOT / "artifacts" / "hermes-loader-proof.json"))
    arguments = parser.parse_args()
    try:
        verify(arguments.hermes_source, arguments.hermes_deps, arguments.live, arguments.output)
    except (RuntimeError, OSError, ImportError) as error:
        print(f"Hermes verification: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
