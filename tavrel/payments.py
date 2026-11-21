"""Exact-unit native payment policy, reservations, and settlement accounting."""

import hashlib
import json
import re
import secrets
import uuid

from .engine import PolicyError, digest, encode, now


NETWORK = {
    "id": "zkverify-volta", "name": "zkVerify Volta", "symbol": "tVFY",
    "decimals": 18, "testnet": True,
    "websocket": "wss://zkverify-volta-rpc.zkverify.io",
    "explorer": "https://zkverify-testnet.subscan.io",
}
MAX_UNITS = 2**128 - 1
HELD = {"pending_approval", "ready_for_signature", "exported", "submitting", "submitted"}
ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def units(value, allow_zero=True):
    """Parse a decimal token string exactly, including 18-decimal dust."""
    if not isinstance(value, str) or re.fullmatch(r"(?:0|[1-9][0-9]{0,20})(?:\.[0-9]{1,18})?", value) is None:
        raise PolicyError("invalid_payment_amount", "Use a decimal tVFY string with at most 18 decimal places.")
    whole, _, fractional = value.partition(".")
    result = int(whole) * 10**18 + int(fractional.ljust(18, "0") or "0")
    if result > MAX_UNITS or (not allow_zero and result == 0):
        raise PolicyError("invalid_payment_amount", "The amount must fit a positive uint128 token balance.")
    return result


def token_amount(value):
    whole, fraction = divmod(int(value), 10**18)
    suffix = f"{fraction:018d}".rstrip("0")
    return str(whole) + ("." + suffix if suffix else "")


def account_id(address):
    """Normalize public AccountId32 hex or a checksum-verified SS58 address."""
    if not isinstance(address, str) or not 2 <= len(address) <= 70:
        raise PolicyError("invalid_payment_address", "Use a Substrate SS58 address or 32-byte public account ID.")
    if re.fullmatch(r"0x[0-9a-fA-F]{64}", address):
        result = bytes.fromhex(address[2:])
    else:
        try:
            number = 0
            for character in address:
                number = number * 58 + ALPHABET.index(character)
            raw = number.to_bytes((number.bit_length() + 7) // 8, "big")
            raw = b"\0" * (len(address) - len(address.lstrip("1"))) + raw
            prefix_length = 1 if raw[0] < 64 else 2
            if raw[0] >= 128 or len(raw) != prefix_length + 34:
                raise ValueError("unsupported account")
            checksum = hashlib.blake2b(b"SS58PRE" + raw[:-2]).digest()[:2]
            if not secrets.compare_digest(checksum, raw[-2:]):
                raise ValueError("checksum")
            result = raw[prefix_length:-2]
        except (ValueError, IndexError, OverflowError):
            raise PolicyError("invalid_payment_address", "The address is not a checksum-valid AccountId32 SS58 address.") from None
    if not any(result):
        raise PolicyError("invalid_payment_address", "A zero account cannot receive a governed payment.")
    return "0x" + result.hex()


def wallet_address(address):
    """Display the same public account using Volta's checksum-valid SS58 prefix."""
    key = bytes.fromhex(account_id(address)[2:])
    prefix = 251
    raw = bytes([((prefix & 0xfc) >> 2) | 0x40, (prefix >> 8) | ((prefix & 3) << 6)]) + key
    raw += hashlib.blake2b(b'SS58PRE' + raw).digest()[:2]
    value = int.from_bytes(raw, 'big')
    encoded = ''
    while value:
        value, digit = divmod(value, 58)
        encoded = ALPHABET[digit] + encoded
    return encoded


class PaymentLedger:
    """Reuse Engine's atomic SQLite boundary with separate exact-unit budgets.

    Balances are decimal text in SQLite: native 18-decimal amounts can exceed
    signed 64-bit SQLite integers. Arithmetic runs as Python integers under
    BEGIN IMMEDIATE. This ledger never calls a wallet or moves funds.
    """

    def __init__(self, engine):
        self.engine = engine
        with engine.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS payment_account (
                    id INTEGER PRIMARY KEY CHECK(id=1), network TEXT NOT NULL,
                    limit_units TEXT NOT NULL DEFAULT '0', reserved_units TEXT NOT NULL DEFAULT '0'
                );
                CREATE TABLE IF NOT EXISTS payment_policies (
                    task_id TEXT PRIMARY KEY REFERENCES tasks(id), sender TEXT NOT NULL,
                    limit_units TEXT NOT NULL, threshold_units TEXT NOT NULL, per_payment_units TEXT NOT NULL,
                    recipients TEXT NOT NULL, require_approval INTEGER NOT NULL,
                    reserved_units TEXT NOT NULL DEFAULT '0', version INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS payment_intents (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                    request_key TEXT NOT NULL, intent_hash TEXT NOT NULL, approval_hash TEXT NOT NULL,
                    recipient TEXT NOT NULL, sender TEXT NOT NULL, amount_units TEXT NOT NULL,
                    purpose TEXT NOT NULL, status TEXT NOT NULL, reason TEXT,
                    policy_version INTEGER NOT NULL, authorization TEXT, unsigned_call TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(task_id,request_key)
                );
            """)
            db.execute("INSERT OR IGNORE INTO payment_account(id,network) VALUES(1,?)", (NETWORK["id"],))
            for table in ("payment_account", "payment_policies"):
                columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
                if "spent_units" not in columns:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN spent_units TEXT NOT NULL DEFAULT '0'")
            if db.execute("SELECT network FROM payment_account WHERE id=1").fetchone()["network"] != NETWORK["id"]:
                raise PolicyError("payment_network_mismatch", "Use a separate ledger for another payment network.", 409)

    def _account(self, db):
        return dict(db.execute("SELECT * FROM payment_account WHERE id=1").fetchone())

    def set_account(self, budget):
        limit = units(budget)
        with self.engine.transaction() as db:
            current = self._account(db)
            if limit < int(current["reserved_units"]) + int(current["spent_units"]):
                raise PolicyError("payment_budget_in_use", "The account limit must cover sent payments and existing holds.", 409)
            db.execute("UPDATE payment_account SET limit_units=? WHERE id=1", (str(limit),))
            self.engine.event(db, "payment_account_updated", "Updated the native-token payment allowance; no deposit or transfer occurred.")
        return self.status()

    def policy(self, task_id, db):
        self.engine.task(task_id, db)
        row = db.execute("SELECT * FROM payment_policies WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise PolicyError("payment_policy_missing", "The operator must configure this task's payment policy first.", 409)
        result = dict(row)
        result["recipients"] = json.loads(result["recipients"])
        result['sender_address'] = wallet_address(result['sender'])
        result['recipient_addresses'] = {label: wallet_address(address) for label, address in result['recipients'].items()}
        result["require_approval"] = bool(result["require_approval"])
        result["available_units"] = str(int(result["limit_units"]) - int(result["reserved_units"]) - int(result["spent_units"]))
        return result

    def configure(self, task_id, sender, budget, approval, per_payment, recipients, require_approval=False):
        sender = account_id(sender)
        limit, threshold, cap = units(budget), units(approval), units(per_payment, False)
        if type(require_approval) is not bool or not isinstance(recipients, dict) or len(recipients) > 100:
            raise PolicyError("invalid_payment_policy", "Provide up to 100 named recipients and a boolean approval policy.")
        allowed = {}
        for label, address in recipients.items():
            if not isinstance(label, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,60}", label) is None:
                raise PolicyError("invalid_payment_policy", "Recipient names use up to 60 letters, digits, underscores, or hyphens.")
            allowed[label] = account_id(address)
        with self.engine.transaction() as db:
            self.engine.task(task_id, db)
            existing = db.execute("SELECT * FROM payment_policies WHERE task_id=?", (task_id,)).fetchone()
            reserved = int(existing["reserved_units"]) if existing else 0
            spent = int(existing["spent_units"]) if existing else 0
            if limit < reserved + spent:
                raise PolicyError("payment_budget_in_use", "The agent limit must cover sent payments and existing holds.", 409)
            if existing and sender != existing["sender"] and reserved:
                raise PolicyError("payment_sender_in_use", "Resolve existing payment holds before changing the signing account.", 409)
            db.execute("""INSERT INTO payment_policies(task_id,sender,limit_units,threshold_units,per_payment_units,recipients,require_approval)
                          VALUES(?,?,?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET sender=excluded.sender,
                          limit_units=excluded.limit_units,threshold_units=excluded.threshold_units,
                          per_payment_units=excluded.per_payment_units,recipients=excluded.recipients,
                          require_approval=excluded.require_approval,version=payment_policies.version+1""",
                       (task_id, sender, str(limit), str(threshold), str(cap), encode(allowed), int(require_approval)))
            self.engine.event(db, "payment_policy_updated", "Updated recipient permissions and exact native-token limits.", task_id)
            return self.policy(task_id, db)

    def _intent(self, payment_id, db, task_id=None):
        row = db.execute("SELECT * FROM payment_intents WHERE id=?", (payment_id,)).fetchone()
        if row is None or (task_id is not None and row["task_id"] != task_id):
            raise PolicyError("payment_not_found", "Payment intent not found.", 404)
        result = dict(row)
        result.pop("intent_hash")
        result["amount"] = token_amount(result["amount_units"])
        result['sender_address'] = wallet_address(result['sender'])
        result['recipient_address'] = wallet_address(result['recipient'])
        result["network"] = NETWORK
        result["unsigned_call"] = json.loads(result["unsigned_call"]) if result["unsigned_call"] else None
        result["transaction"] = None
        result["policy_proof"] = None
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='payment_proofs'").fetchone():
            proof = db.execute('SELECT bundle FROM payment_proofs WHERE payment_id=? AND approval_hash=?', (payment_id, result['approval_hash'])).fetchone()
            if proof:
                result['policy_proof'] = json.loads(proof['bundle'])
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='payment_transactions'").fetchone():
            transaction = db.execute("SELECT tx_hash,nonce,status,error,receipt,created_at,updated_at FROM payment_transactions WHERE payment_id=?", (payment_id,)).fetchone()
            if transaction:
                result["transaction"] = dict(transaction)
                result["transaction"]["receipt"] = json.loads(transaction["receipt"]) if transaction["receipt"] else None
        result["broadcast"] = result["status"] in {"submitted", "settled", "failed"}
        result["settlement_verified"] = result["status"] == "settled"
        return result

    def intent(self, payment_id, task_id=None):
        with self.engine.connection() as db:
            return self._intent(payment_id, db, task_id)

    def _reason(self, db, policy, recipient, amount):
        task = self.engine.task(policy["task_id"], db)
        if task["paused"]:
            return "TASK_PAUSED"
        if recipient not in policy["recipients"].values():
            return "RECIPIENT_NOT_ALLOWED"
        if amount > int(policy["per_payment_units"]):
            return "PER_PAYMENT_LIMIT"
        return None

    def _hold(self, db, policy, amount):
        account = self._account(db)
        db.execute("UPDATE payment_policies SET reserved_units=? WHERE task_id=?",
                   (str(int(policy["reserved_units"]) + amount), policy["task_id"]))
        db.execute("UPDATE payment_account SET reserved_units=? WHERE id=1",
                   (str(int(account["reserved_units"]) + amount),))

    def prepare(self, task_id, recipient, amount, purpose, request_key, actor="agent"):
        if not isinstance(purpose, str) or not 1 <= len(purpose.strip()) <= 1000:
            raise PolicyError("invalid_payment_purpose", "Describe the payment purpose in 1 to 1,000 characters.")
        if not isinstance(request_key, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,100}", request_key) is None:
            raise PolicyError("invalid_request_key", "Use a stable payment request key of up to 100 letters, digits, underscores, or hyphens.")
        value = units(amount, False)
        if not isinstance(recipient, str):
            raise PolicyError("invalid_payment_address", "Provide a recipient name or native Substrate address.")
        with self.engine.transaction() as db:
            policy = self.policy(task_id, db)
            target = account_id(policy["recipients"].get(recipient, recipient))
            intent_hash = digest(encode({"network": NETWORK["id"], "sender": policy["sender"],
                                       "recipient": target, "amount_units": str(value), "purpose": purpose.strip()}))
            existing = db.execute("SELECT * FROM payment_intents WHERE task_id=? AND request_key=?", (task_id, request_key)).fetchone()
            if existing:
                if existing["intent_hash"] != intent_hash:
                    raise PolicyError("idempotency_conflict", "This key already identifies a different payment intent.", 409)
                return self._intent(existing["id"], db)
            reason = self._reason(db, policy, target, value)
            account = self._account(db)
            if not reason and value > int(policy["available_units"]):
                reason = "TASK_PAYMENT_BUDGET"
            if not reason and value > int(account["limit_units"]) - int(account["reserved_units"]) - int(account["spent_units"]):
                reason = "WORKSPACE_PAYMENT_BUDGET"
            needs_approval = policy["require_approval"] or value > int(policy["threshold_units"])
            status = "blocked" if reason else ("pending_approval" if needs_approval else "ready_for_signature")
            payment_id = "pay_" + uuid.uuid4().hex[:16]
            approval_hash = digest(encode({"id": payment_id, "task_id": task_id,
                                          "intent": intent_hash, "policy_version": policy["version"]}))
            stamp = now()
            db.execute("""INSERT INTO payment_intents(id,task_id,request_key,intent_hash,approval_hash,recipient,sender,
                          amount_units,purpose,status,reason,policy_version,authorization,created_at,updated_at)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (payment_id, task_id, request_key, intent_hash, approval_hash, target, policy["sender"],
                        str(value), purpose.strip(), status, reason, policy["version"],
                        "policy" if status == "ready_for_signature" else None, stamp, stamp))
            if not reason:
                self._hold(db, policy, value)
            self.engine.event(db, "payment_" + status, reason or "Payment allowance held; no token transfer occurred.", task_id, payment_id, actor)
            return self._intent(payment_id, db)

    def _release(self, db, payment):
        policy = self.policy(payment["task_id"], db)
        self._hold(db, policy, -int(payment["amount_units"]))

    def _refresh(self, db, payment):
        policy = self.policy(payment["task_id"], db)
        reason = self._reason(db, policy, payment["recipient"], int(payment["amount_units"]))
        if payment["sender"] != policy["sender"]:
            reason = "SIGNER_CHANGED"
        if reason:
            self._release(db, payment)
            db.execute("UPDATE payment_intents SET status='blocked',reason=?,authorization=NULL,updated_at=? WHERE id=?",
                       (reason, now(), payment["id"]))
        elif payment["policy_version"] != policy["version"]:
            raw = db.execute("SELECT intent_hash FROM payment_intents WHERE id=?", (payment["id"],)).fetchone()
            approval_hash = digest(encode({"id": payment["id"], "task_id": payment["task_id"],
                                          "intent": raw["intent_hash"], "policy_version": policy["version"]}))
            needs_approval = policy["require_approval"] or int(payment["amount_units"]) > int(policy["threshold_units"])
            status = "pending_approval" if needs_approval else "ready_for_signature"
            db.execute("UPDATE payment_intents SET status=?,reason='POLICY_CHANGED_REVIEW_AGAIN',policy_version=?,approval_hash=?,authorization=?,updated_at=? WHERE id=?",
                       (status, policy["version"], approval_hash, "policy" if not needs_approval else None, now(), payment["id"]))
        return self._intent(payment["id"], db)

    def _confirm(self, payment, expected_hash):
        if not isinstance(expected_hash, str) or not expected_hash.isascii() or not secrets.compare_digest(expected_hash, payment["approval_hash"]):
            raise PolicyError("approval_mismatch", "Confirmation must match the exact payment intent and policy version.", 409)

    def decide(self, payment_id, decision, expected_hash):
        if decision not in ("approve", "deny"):
            raise PolicyError("invalid_decision", "Choose approve or deny.")
        with self.engine.transaction() as db:
            payment = self._intent(payment_id, db)
            self._confirm(payment, expected_hash)
            if payment["status"] not in {"pending_approval", "ready_for_signature"}:
                raise PolicyError("payment_not_pending", "This intent cannot receive a new decision. Exported calls retain their holds.", 409)
            if decision == "deny":
                self._release(db, payment)
                db.execute("UPDATE payment_intents SET status='denied',reason='OPERATOR_DENIED',authorization=NULL,updated_at=? WHERE id=?", (now(), payment_id))
            else:
                refreshed = self._refresh(db, payment)
                if refreshed["status"] == "blocked" or refreshed["policy_version"] != payment["policy_version"]:
                    return refreshed
                if payment["status"] != "pending_approval":
                    raise PolicyError("payment_not_pending", "The payment already meets its policy; export it after review.", 409)
                db.execute("UPDATE payment_intents SET status='ready_for_signature',reason=NULL,authorization='operator',updated_at=? WHERE id=?", (now(), payment_id))
            self.engine.event(db, "payment_" + decision, "Operator decided the exact intent; no signing occurred.", payment["task_id"], payment_id)
            return self._intent(payment_id, db)

    def export(self, payment_id, expected_hash):
        with self.engine.transaction() as db:
            payment = self._intent(payment_id, db)
            self._confirm(payment, expected_hash)
            if payment["status"] == "exported":
                return payment
            if payment["status"] != "ready_for_signature":
                raise PolicyError("payment_not_authorized", "Only an authorized payment can be exported for external signing.", 409)
            refreshed = self._refresh(db, payment)
            if refreshed["status"] != "ready_for_signature" or refreshed["approval_hash"] != expected_hash:
                return refreshed
            call = {"network": NETWORK["id"], "sender": payment["sender"], "pallet": "balances",
                    "method": "transferKeepAlive", "args": {"dest": payment["recipient"], "value": payment["amount_units"]},
                    "payment_id": payment_id, "approval_hash": expected_hash,
                    "note": "Unsigned call description. Runtime metadata, nonce, mortality, fees, signing, and broadcast are supplied by the operator wallet. This is not encoded transaction data."}
            db.execute("UPDATE payment_intents SET status='exported',unsigned_call=?,updated_at=? WHERE id=?", (encode(call), now(), payment_id))
            self.engine.event(db, "payment_exported", "Exported an unsigned native transfer description; the full allowance stays held.", payment["task_id"], payment_id)
            return self._intent(payment_id, db)

    def status(self, task_id=None):
        with self.engine.connection() as db:
            account = self._account(db)
            account["available_units"] = str(int(account["limit_units"]) - int(account["reserved_units"]) - int(account["spent_units"]))
            if task_id:
                policies = [self.policy(task_id, db)]
                rows = db.execute("SELECT id FROM payment_intents WHERE task_id=? ORDER BY rowid DESC LIMIT 100", (task_id,)).fetchall()
            else:
                policies = [self.policy(row["task_id"], db) for row in db.execute("SELECT task_id FROM payment_policies").fetchall()]
                rows = db.execute("SELECT id FROM payment_intents ORDER BY rowid DESC LIMIT 100").fetchall()
            return {"network": NETWORK, "account": account, "policies": policies,
                    "intents": [self._intent(row["id"], db) for row in rows],
                    "signing_enabled": True, "broadcast_enabled": True, "settled_units": account["spent_units"],
                    "coverage": "Tavrel validates its payment routes. Wallet signatures authorize transfers; finalized chain events verify settlement. Direct wallet transfers are outside Tavrel's policy boundary. Network fees are additional to the principal allowance."}

    def plan_batch(self, task_id, task_key, payments):
        if not isinstance(task_key, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,70}", task_key) is None:
            raise PolicyError("invalid_request_key", "Use a task key of up to 70 letters, digits, underscores, or hyphens.")
        if not isinstance(payments, list) or not 1 <= len(payments) <= 20:
            raise PolicyError("invalid_payment_batch", "Provide 1 to 20 payment instructions.")
        # Validate the complete task before reserving any instructions. Policy
        # verdicts are still per-payment; batches are not an all-or-none payout.
        for item in payments:
            if not isinstance(item, dict) or set(item) != {"recipient", "amount", "purpose"}:
                raise PolicyError("invalid_payment_batch", "Each payment needs recipient, amount, and purpose.")
            units(item["amount"], False)
            if not isinstance(item["recipient"], str):
                raise PolicyError("invalid_payment_address", "Provide a recipient name or native Substrate address.")
            if not isinstance(item["purpose"], str) or not 1 <= len(item["purpose"].strip()) <= 1000:
                raise PolicyError("invalid_payment_purpose", "Describe each payment purpose.")
            with self.engine.connection() as db:
                policy = self.policy(task_id, db)
                account_id(policy["recipients"].get(item["recipient"], item["recipient"]))
        # Bind the task key to the full ordered instruction list across restarts.
        task_hash = digest(encode(payments))
        with self.engine.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS payment_batches(task_id TEXT NOT NULL,task_key TEXT NOT NULL,payload_hash TEXT NOT NULL,PRIMARY KEY(task_id,task_key))")
            existing = db.execute("SELECT payload_hash FROM payment_batches WHERE task_id=? AND task_key=?", (task_id, task_key)).fetchone()
            if existing and existing["payload_hash"] != task_hash:
                raise PolicyError("idempotency_conflict", "This task key already identifies different payment instructions.", 409)
            db.execute("INSERT OR IGNORE INTO payment_batches VALUES(?,?,?)", (task_id, task_key, task_hash))
        prepared = [self.prepare(task_id, request_key=f"{task_key}_{index}", **item) for index, item in enumerate(payments)]
        return {"task_key": task_key, "agent": "Deterministic payment task executor; no language model is invoked.",
                "intents": prepared, "summary": {state: sum(item["status"] == state for item in prepared) for state in ("ready_for_signature", "pending_approval", "blocked", "exported", "denied")},
                "broadcast": False, "settlement_verified": False}
