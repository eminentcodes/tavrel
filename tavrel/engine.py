"""Atomic, durable spending policy. Money is represented only as integer cents."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Any
import uuid

from .services import ProviderRejected, SERVICES, UncertainCharge
from .live_services import FREE_SERVICES


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def encode(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class PolicyError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def cents(value: Any, label: str = "Amount", allow_zero: bool = True) -> int:
    if type(value) is not int or value < (0 if allow_zero else 1) or value > 100_000_000:
        raise PolicyError("invalid_amount", f"{label} must be an integer number of cents within the supported range.")
    return value


class Engine:
    def __init__(self, database: str | Path, services=None):
        self.database = str(database)
        self.services = FREE_SERVICES if services is None else services
        if not self.services:
            raise PolicyError("invalid_services", "Configure at least one supported service.")
        for service in self.services.values():
            cents(service.price_cents, "Service quote")
        self.mode = "simulation" if all(service.public()["billing"] == "simulated" for service in self.services.values()) else "live_free"
        if self.mode == "live_free" and any(service.price_cents != 0 or service.public()["billing"] != "free" for service in self.services.values()):
            raise PolicyError("paid_services_disabled", "This gateway supports free live services only. Paid execution is disabled.")
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS account (
                    id INTEGER PRIMARY KEY CHECK(id = 1), limit_cents INTEGER NOT NULL,
                    spent_cents INTEGER NOT NULL DEFAULT 0, reserved_cents INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
                    limit_cents INTEGER NOT NULL, threshold_cents INTEGER NOT NULL,
                    spent_cents INTEGER NOT NULL DEFAULT 0, reserved_cents INTEGER NOT NULL DEFAULT 0,
                    allowed_services TEXT NOT NULL, paused INTEGER NOT NULL DEFAULT 0,
                    token_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                    request_key TEXT NOT NULL, intent_hash TEXT NOT NULL, approval_hash TEXT NOT NULL,
                    service_id TEXT NOT NULL, payload TEXT NOT NULL, quote_cents INTEGER NOT NULL,
                    actual_cents INTEGER, status TEXT NOT NULL, reason TEXT,
                    actor TEXT NOT NULL, output TEXT, evidence TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(task_id, request_key)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, request_id TEXT,
                    kind TEXT NOT NULL, actor TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS requests_task ON requests(task_id, created_at);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
        with self.transaction() as db:
            previous = db.execute("SELECT value FROM metadata WHERE key='mode'").fetchone()
            legacy = db.execute("SELECT 1 FROM account LIMIT 1").fetchone()
            previous_mode = previous["value"] if previous else ("simulation" if legacy else self.mode)
            if previous_mode != self.mode:
                raise PolicyError("database_mode_mismatch", f"This ledger belongs to {previous_mode}. Use --mode simulation for a simulated ledger, or a separate --data-dir for {self.mode}; existing receipts must keep their original billing mode.", 409)
            task_columns = {row["name"] for row in db.execute("PRAGMA table_info(tasks)")}
            if "require_approval" not in task_columns:
                db.execute("ALTER TABLE tasks ADD COLUMN require_approval INTEGER NOT NULL DEFAULT 0")
            request_columns = {row["name"] for row in db.execute("PRAGMA table_info(requests)")}
            for name, definition in (("billing", "TEXT NOT NULL DEFAULT 'simulated'"), ("service_name", "TEXT NOT NULL DEFAULT ''")):
                if name not in request_columns:
                    db.execute(f"ALTER TABLE requests ADD COLUMN {name} {definition}")
            for service in self.services.values():
                db.execute("UPDATE requests SET service_name=? WHERE service_id=? AND service_name=''", (service.name, service.id))
            db.execute("INSERT OR IGNORE INTO metadata(key,value) VALUES('mode',?)", (self.mode,))
            db.execute("INSERT OR IGNORE INTO account(id,limit_cents) VALUES(1,?)", (2500 if self.mode == "simulation" else 0,))

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.database, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.rollback()
                raise
            else:
                db.commit()

    def event(self, db, kind: str, message: str, task_id=None, request_id=None, actor="operator"):
        db.execute("INSERT INTO events(task_id, request_id, kind, actor, message, created_at) VALUES(?,?,?,?,?,?)", (task_id, request_id, kind, actor, message, now()))

    def service_list(self):
        return [service.public() for service in self.services.values()]

    def validate_services(self, value):
        if not isinstance(value, list) or any(not isinstance(item, str) or item not in self.services for item in value):
            raise PolicyError("invalid_services", "Choose services from the supported catalog.")
        return sorted(set(value))

    def create_task(self, name: str, limit_cents: int, threshold_cents: int, allowed_services: list, description="", require_approval=False):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise PolicyError("invalid_name", "Give the task a name between 1 and 100 characters.")
        if not isinstance(description, str) or len(description) > 1000:
            raise PolicyError("invalid_description", "The task description is too long.")
        cents(limit_cents, "Task budget")
        cents(threshold_cents, "Approval threshold")
        if type(require_approval) is not bool:
            raise PolicyError("invalid_policy", "Require approval must be true or false.")
        allowed = self.validate_services(allowed_services)
        task_id = "tsk_" + uuid.uuid4().hex[:16]
        token = "tvr_" + secrets.token_urlsafe(32)
        with self.transaction() as db:
            db.execute("INSERT INTO tasks(id,name,description,limit_cents,threshold_cents,allowed_services,token_hash,created_at) VALUES(?,?,?,?,?,?,?,?)", (task_id, name.strip(), description.strip(), limit_cents, threshold_cents, encode(allowed), digest(token), now()))
            db.execute("UPDATE tasks SET require_approval=? WHERE id=?", (int(require_approval), task_id))
            self.event(db, "task_created", f"Created {name.strip()} with a ${limit_cents / 100:.2f} allowance.", task_id)
        return {"task": self.task(task_id), "task_token": token}

    def task(self, task_id, db=None):
        if db is None:
            with self.connection() as conn:
                return self.task(task_id, conn)
        row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise PolicyError("task_not_found", "Task not found.", 404)
        result = dict(row)
        result.pop("token_hash")
        result["allowed_services"] = json.loads(result["allowed_services"])
        result["paused"] = bool(result["paused"])
        result["require_approval"] = bool(result["require_approval"])
        result["mode"] = self.mode
        result["available_cents"] = result["limit_cents"] - result["spent_cents"] - result["reserved_cents"]
        return result

    def authenticate_task(self, token):
        if not isinstance(token, str) or not token:
            raise PolicyError("unauthorized", "A valid task token is required.", 401)
        with self.connection() as db:
            row = db.execute("SELECT id FROM tasks WHERE token_hash=?", (digest(token),)).fetchone()
        if row is None:
            raise PolicyError("unauthorized", "The task token is invalid or has been rotated.", 401)
        return row["id"]

    def rotate_token(self, task_id):
        token = "tvr_" + secrets.token_urlsafe(32)
        with self.transaction() as db:
            self.task(task_id, db)
            db.execute("UPDATE tasks SET token_hash=? WHERE id=?", (digest(token), task_id))
            self.event(db, "token_rotated", "Rotated the task's Hermes access token.", task_id)
        return {"task_token": token, "task_id": task_id}

    def update_task(self, task_id, changes):
        permitted = {"name", "description", "limit_cents", "threshold_cents", "allowed_services", "paused", "require_approval"}
        if not isinstance(changes, dict) or set(changes) - permitted:
            raise PolicyError("invalid_policy", "The policy contains unsupported fields.")
        with self.transaction() as db:
            current = self.task(task_id, db)
            value = {**current, **changes}
            if not isinstance(value["name"], str) or not 1 <= len(value["name"].strip()) <= 100:
                raise PolicyError("invalid_name", "Give the task a name between 1 and 100 characters.")
            if not isinstance(value["description"], str) or len(value["description"]) > 1000:
                raise PolicyError("invalid_description", "The task description is too long.")
            cents(value["limit_cents"], "Task budget")
            cents(value["threshold_cents"], "Approval threshold")
            if type(value["paused"]) is not bool:
                raise PolicyError("invalid_policy", "Paused must be true or false.")
            if type(value["require_approval"]) is not bool:
                raise PolicyError("invalid_policy", "Require approval must be true or false.")
            if value["limit_cents"] < current["spent_cents"] + current["reserved_cents"]:
                raise PolicyError("budget_in_use", "The budget must cover settled spend and existing reservations.", 409)
            allowed = self.validate_services(value["allowed_services"])
            db.execute("UPDATE tasks SET name=?, description=?, limit_cents=?, threshold_cents=?, allowed_services=?, paused=? WHERE id=?", (value["name"].strip(), value["description"].strip(), value["limit_cents"], value["threshold_cents"], encode(allowed), int(value["paused"]), task_id))
            db.execute("UPDATE tasks SET require_approval=? WHERE id=?", (int(value["require_approval"]), task_id))
            self.event(db, "policy_updated", "Updated the task's spending policy.", task_id)
        return self.task(task_id)

    def update_account(self, limit_cents):
        cents(limit_cents, "Workspace budget")
        with self.transaction() as db:
            account = db.execute("SELECT * FROM account WHERE id=1").fetchone()
            if limit_cents < account["spent_cents"] + account["reserved_cents"]:
                raise PolicyError("budget_in_use", "The workspace budget must cover settled spend and existing reservations.", 409)
            db.execute("UPDATE account SET limit_cents=? WHERE id=1", (limit_cents,))
            self.event(db, "account_updated", f"Set the workspace allowance to ${limit_cents / 100:.2f}.")

    def request(self, request_id, task_id=None, db=None):
        if db is None:
            with self.connection() as conn:
                return self.request(request_id, task_id, conn)
        row = db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        if row is None or (task_id is not None and row["task_id"] != task_id):
            raise PolicyError("request_not_found", "Request not found.", 404)
        result = dict(row)
        for key in ("payload", "output", "evidence"):
            result[key] = json.loads(result[key]) if result[key] else None
        result.pop("intent_hash")
        result["service_name"] = result["service_name"] or (self.services[result["service_id"]].name if result["service_id"] in self.services else result["service_id"])
        result["task_name"] = self.task(result["task_id"], db)["name"]
        return result

    def purchase(self, task_id, service_id, payload, request_key, actor="agent"):
        if not isinstance(service_id, str) or service_id not in self.services:
            raise PolicyError("unknown_service", "This service is not supported. Unknown prices cannot be authorized.")
        if not isinstance(payload, dict) or set(payload) != {"query"} or not isinstance(payload["query"], str) or not 1 <= len(payload["query"].strip()) <= 4000:
            raise PolicyError("invalid_input", "Provide a query between 1 and 4,000 characters.")
        if not isinstance(request_key, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,100}", request_key) is None:
            raise PolicyError("invalid_request_key", "Use a stable request key containing up to 100 letters, digits, underscores, or hyphens.")
        service = self.services[service_id]
        quote = cents(service.price_cents, "Service quote")
        if self.mode == "live_free" and (quote != 0 or service.public()["billing"] != "free"):
            raise PolicyError("paid_services_disabled", "Paid services are disabled in this gateway.")
        intent_hash = digest(encode({"service": service_id, "payload": payload}))
        should_execute = False
        with self.transaction() as db:
            task = self.task(task_id, db)
            existing = db.execute("SELECT * FROM requests WHERE task_id=? AND request_key=?", (task_id, request_key)).fetchone()
            if existing is not None:
                if existing["intent_hash"] != intent_hash:
                    raise PolicyError("idempotency_conflict", "This request key already belongs to a different purchase.", 409)
                request_id = existing["id"]
                should_execute = existing["status"] == "reserved"
            else:
                account = db.execute("SELECT * FROM account WHERE id=1").fetchone()
                reason = None
                if task["paused"]:
                    reason = "Task is paused."
                elif service_id not in task["allowed_services"]:
                    reason = "Service is not permitted by this task's policy."
                elif quote > task["available_cents"]:
                    reason = "Purchase exceeds the task's remaining budget."
                elif quote > account["limit_cents"] - account["spent_cents"] - account["reserved_cents"]:
                    reason = "Purchase exceeds the workspace's remaining budget."
                status = "blocked" if reason else ("pending_approval" if task["require_approval"] or quote > task["threshold_cents"] else "reserved")
                request_id = "req_" + uuid.uuid4().hex[:16]
                approval_hash = digest(encode({"id": request_id, "task": task_id, "intent": intent_hash, "maximum_cents": quote}))
                stamp = now()
                db.execute("INSERT INTO requests(id,task_id,request_key,intent_hash,approval_hash,service_id,payload,quote_cents,status,reason,actor,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (request_id, task_id, request_key, intent_hash, approval_hash, service_id, encode(payload), quote, status, reason, actor, stamp, stamp))
                db.execute("UPDATE requests SET billing=?, service_name=? WHERE id=?", (service.public()["billing"], service.name, request_id))
                if not reason:
                    db.execute("UPDATE tasks SET reserved_cents=reserved_cents+? WHERE id=?", (quote, task_id))
                    db.execute("UPDATE account SET reserved_cents=reserved_cents+? WHERE id=1", (quote,))
                self.event(db, status, reason or ("Waiting for operator approval; maximum cost reserved." if status == "pending_approval" else "Budget reserved before service execution."), task_id, request_id, actor)
                should_execute = status == "reserved"
        if should_execute:
            self.execute(request_id)
        return self.request(request_id)

    def release(self, db, request):
        db.execute("UPDATE tasks SET reserved_cents=reserved_cents-? WHERE id=?", (request["quote_cents"], request["task_id"]))
        db.execute("UPDATE account SET reserved_cents=reserved_cents-? WHERE id=1", (request["quote_cents"],))

    def decide(self, request_id, decision, expected_hash):
        if decision not in ("approve", "deny"):
            raise PolicyError("invalid_decision", "Choose approve or deny.")
        execute = False
        with self.transaction() as db:
            request = self.request(request_id, db=db)
            if not isinstance(expected_hash, str) or not expected_hash.isascii() or not secrets.compare_digest(expected_hash, request["approval_hash"]):
                raise PolicyError("approval_mismatch", "The approval does not match the exact request and maximum price.", 409)
            if request["status"] != "pending_approval":
                raise PolicyError("request_not_pending", "This request is no longer waiting for approval.", 409)
            task = self.task(request["task_id"], db)
            if decision == "approve" and task["paused"]:
                raise PolicyError("task_paused", "Resume the task before approving its purchase.", 409)
            reason = "Operator declined this purchase." if decision == "deny" else None
            if decision == "approve" and request["service_id"] not in task["allowed_services"]:
                reason = "Service permission was removed before approval."
            if reason:
                status = "denied" if decision == "deny" else "blocked"
                self.release(db, request)
            else:
                status = "reserved"
                execute = True
            db.execute("UPDATE requests SET status=?, reason=?, updated_at=? WHERE id=?", (status, reason, now(), request_id))
            self.event(db, "approved" if execute else status, reason or "Operator approved the exact request and reserved maximum price.", request["task_id"], request_id)
        if execute:
            self.execute(request_id)
        return self.request(request_id)

    def execute(self, request_id):
        with self.transaction() as db:
            request = self.request(request_id, db=db)
            if request["status"] != "reserved":
                return
            task = self.task(request["task_id"], db)
            if task["paused"] or request["service_id"] not in task["allowed_services"]:
                self.release(db, request)
                db.execute("UPDATE requests SET status='blocked', reason=?, updated_at=? WHERE id=?", ("Policy changed before service execution.", now(), request_id))
                self.event(db, "blocked", "Policy changed before service execution.", request["task_id"], request_id)
                return
            service = self.services[request["service_id"]]
            if (type(service.price_cents) is not int or service.price_cents != request["quote_cents"]
                    or service.public()["billing"] != request["billing"]
                    or (self.mode == "live_free" and service.price_cents != 0)):
                self.release(db, request)
                reason = "Service price or billing mode changed after reservation. Submit a new request for a fresh quote and authorization."
                db.execute("UPDATE requests SET status='blocked', reason=?, updated_at=? WHERE id=?", (reason, now(), request_id))
                self.event(db, "blocked", reason, request["task_id"], request_id)
                return
            db.execute("UPDATE requests SET status='executing', updated_at=? WHERE id=?", (now(), request_id))
            self.event(db, "executing", "Service execution started with the full quote held.", request["task_id"], request_id, request["actor"])
        try:
            receipt = service.execute(request["payload"], request_id)
            if type(receipt.cost_cents) is not int or not 0 <= receipt.cost_cents <= request["quote_cents"]:
                raise UncertainCharge("The service receipt violated its reserved maximum cost.")
            if not isinstance(receipt.output, dict) or not isinstance(receipt.evidence, dict):
                raise UncertainCharge("The service returned an invalid result or evidence.")
            if receipt.evidence.get("billing", request["billing"]) != request["billing"]:
                raise UncertainCharge("The service evidence conflicts with the request's billing mode.")
            evidence = encode(receipt.evidence)
            output = encode(receipt.output)
        except ProviderRejected as exc:
            with self.transaction() as db:
                current = self.request(request_id, db=db)
                self.release(db, current)
                reason = str(exc) if request["billing"] == "free" else "The service confirmed no billable work occurred."
                db.execute("UPDATE requests SET status='failed', reason=?, updated_at=? WHERE id=?", (reason, now(), request_id))
                self.event(db, "failed", "Service confirmed no charge; reservation released.", request["task_id"], request_id)
            return
        except Exception:
            with self.transaction() as db:
                db.execute("UPDATE requests SET status='uncertain', reason=?, updated_at=? WHERE id=?", ("The outcome is uncertain. The maximum cost remains reserved; this request will not be retried automatically.", now(), request_id))
                self.event(db, "uncertain", "Uncertain service outcome; reservation retained.", request["task_id"], request_id)
            return
        with self.transaction() as db:
            self.release(db, request)
            db.execute("UPDATE tasks SET spent_cents=spent_cents+? WHERE id=?", (receipt.cost_cents, request["task_id"]))
            db.execute("UPDATE account SET spent_cents=spent_cents+? WHERE id=1", (receipt.cost_cents,))
            db.execute("UPDATE requests SET status='settled', actual_cents=?, output=?, evidence=?, updated_at=? WHERE id=?", (receipt.cost_cents, output, evidence, now(), request_id))
            message = "Simulated receipt recorded; unused reservation released." if request["billing"] == "simulated" else "Real free-service result recorded; no charge occurred."
            self.event(db, "settled", message, request["task_id"], request_id, request["actor"])

    def recover_interrupted(self):
        """Call once at gateway startup, never on a concurrent running engine."""
        with self.transaction() as db:
            interrupted = db.execute("SELECT id, task_id FROM requests WHERE status='executing'").fetchall()
            for request in interrupted:
                db.execute("UPDATE requests SET status='uncertain', reason=?, updated_at=? WHERE id=?", ("Gateway stopped during execution. Maximum cost stays reserved until the outcome is verified.", now(), request["id"]))
                self.event(db, "uncertain", "Recovered an interrupted execution without releasing its reservation.", request["task_id"], request["id"])

    def reconcile(self, request_id, actual_cents, reference, note, expected_hash):
        """Record an operator's observed cost without reexecuting unknown work.

        This is an explicit operator attestation, not independent provider billing
        verification. Only simulation and zero-cost adapters exist in this build.
        """
        cents(actual_cents, "Observed cost")
        if not isinstance(reference, str) or not 1 <= len(reference.strip()) <= 500:
            raise PolicyError("invalid_evidence", "Provide an evidence reference between 1 and 500 characters.")
        if not isinstance(note, str) or not 1 <= len(note.strip()) <= 2000:
            raise PolicyError("invalid_evidence", "Explain the observed outcome in 1 to 2,000 characters.")
        with self.transaction() as db:
            request = self.request(request_id, db=db)
            if not isinstance(expected_hash, str) or not expected_hash.isascii() or not secrets.compare_digest(expected_hash, request["approval_hash"]):
                raise PolicyError("approval_mismatch", "Confirmation does not match the exact request and maximum price.", 409)
            if request["status"] != "uncertain":
                raise PolicyError("request_not_uncertain", "Only uncertain requests can be reconciled.", 409)
            if actual_cents > request["quote_cents"] or (request["billing"] == "free" and actual_cents != 0):
                raise PolicyError("invalid_reconciliation_cost", "The observed cost must fit the original reserved maximum and billing mode.", 409)
            evidence = {"kind": "operator_reconciliation", "provider_verified": False,
                        "reference": reference.strip(), "note": note.strip(),
                        "billing": request["billing"], "charge_cents": actual_cents,
                        "recorded_at": now(), "source": "operator_attestation"}
            self.release(db, request)
            db.execute("UPDATE tasks SET spent_cents=spent_cents+? WHERE id=?", (actual_cents, request["task_id"]))
            db.execute("UPDATE account SET spent_cents=spent_cents+? WHERE id=1", (actual_cents,))
            db.execute("UPDATE requests SET status='reconciled', actual_cents=?, evidence=?, reason=?, updated_at=? WHERE id=?",
                       (actual_cents, encode(evidence), "Operator recorded the observed cost. Service output remains unverified; no work was retried.", now(), request_id))
            self.event(db, "reconciled", "Operator attested to the observed cost; unused reservation released without reexecution.", request["task_id"], request_id)
        return self.request(request_id)

    def snapshot(self, task_id=None):
        with self.transaction() as db:
            tasks = [self.task(row["id"], db) for row in db.execute("SELECT id FROM tasks ORDER BY created_at DESC").fetchall()] if task_id is None else [self.task(task_id, db)]
            sql = "SELECT id FROM requests" + (" WHERE task_id=?" if task_id else "") + " ORDER BY created_at DESC, rowid DESC LIMIT 200"
            rows = db.execute(sql, (task_id,) if task_id else ()).fetchall()
            requests = [self.request(row["id"], task_id, db) for row in rows]
            event_sql = "SELECT * FROM events" + (" WHERE task_id=?" if task_id else "") + " ORDER BY id DESC LIMIT 100"
            events = [dict(row) for row in db.execute(event_sql, (task_id,) if task_id else ()).fetchall()]
            account = dict(db.execute("SELECT * FROM account WHERE id=1").fetchone()) if task_id is None else None
            if account:
                account["available_cents"] = account["limit_cents"] - account["spent_cents"] - account["reserved_cents"]
            return {"account": account, "tasks": tasks, "requests": requests, "events": events, "services": self.service_list(), "mode": self.mode, "paid_execution_enabled": False}

    def ledger(self, task_id=None, limit=50, offset=0):
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
            raise PolicyError("invalid_pagination", "Use a limit between 1 and 200 and a nonnegative offset.")
        with self.transaction() as db:
            if task_id is not None:
                self.task(task_id, db)
            where = " WHERE task_id=?" if task_id else ""
            params = (task_id,) if task_id else ()
            total = db.execute("SELECT COUNT(*) FROM requests" + where, params).fetchone()[0]
            rows = db.execute("SELECT id FROM requests" + where + " ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?", params + (limit, offset)).fetchall()
            return {"requests": [self.request(row["id"], task_id, db) for row in rows], "total": total, "limit": limit, "offset": offset, "mode": self.mode}

    def agent_status(self, task_id):
        with self.transaction() as db:
            task = self.task(task_id, db)
            rows = db.execute("SELECT id,service_id,quote_cents,actual_cents,status,reason FROM requests WHERE task_id=? ORDER BY created_at DESC, rowid DESC LIMIT 10", (task_id,)).fetchall()
            return {"task": task, "requests": [dict(row) for row in rows], "services": self.service_list(), "mode": self.mode, "paid_execution_enabled": False, "coverage": "Only requests made through Tavrel's connected services. Native model calls and other tools are outside this gateway."}

    def seed_demo(self):
        if self.mode != "simulation":
            raise PolicyError("simulation_required", "Demo seeding requires serve --simulation.")
        with self.connection() as db:
            if db.execute("SELECT 1 FROM tasks LIMIT 1").fetchone():
                return
        first = self.create_task("AI framework comparison", 800, 100, list(self.services), "Compare agent memory, integrations, and documented pricing.")["task"]["id"]
        for index, query in enumerate(("Compare Hermes agent memory", "Compare agent extension systems", "Compare framework setup effort")):
            self.purchase(first, "search_brief", {"query": query}, f"seed_search_{index}", "demo")
        self.purchase(first, "research_report", {"query": "Prepare the full agent-framework comparison"}, "seed_pending_report", "demo")
        second = self.create_task("Product launch brief", 500, 200, list(self.services), "Prepare a product positioning brief and supporting research.")["task"]["id"]
        self.purchase(second, "search_brief", {"query": "Research agent-tool spending workflows"}, "seed_launch_search", "demo")
        self.purchase(second, "research_report", {"query": "Draft a launch research brief for Tavrel"}, "seed_launch_report", "demo")
        third = self.create_task("Weekly release digest", 40, 100, ["summary", "search_brief"], "Summarize a recurring release report with a small allowance.")["task"]["id"]
        for index in range(3):
            self.purchase(third, "summary", {"query": "The gateway checks every connected purchase. Operators can approve requests. Spend remains traceable to its task."}, f"seed_digest_{index}", "demo")
        self.purchase(third, "search_brief", {"query": "Find additional release context"}, "seed_blocked", "demo")

    def start_walkthrough(self):
        if self.mode != "simulation":
            raise PolicyError("simulation_required", "The spending walkthrough requires simulation mode.")
        task = self.create_task("Competitor research walkthrough", 250, 100, list(self.services), "Research competitors with a $2.50 allowance and approval above $1.")["task"]
        self.purchase(task["id"], "search_brief", {"query": "Find sources for a competitor comparison"}, "walkthrough_brief", "demo")
        report = self.purchase(task["id"], "research_report", {"query": "Write the detailed competitor comparison"}, "walkthrough_report", "demo")
        return {"task_id": task["id"], "request_id": report["id"]}

