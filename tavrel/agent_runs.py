"""Deterministic invoice batches with durable actions and exact retry identities."""
import json
import re
from threading import Event, RLock, Thread
import uuid

from .engine import PolicyError, digest, encode, now
from .payments import account_id, units, token_amount

EXECUTOR = 'invoice_rules_v1'
MAX_INVOICES = 20


class AgentRuns:
    def __init__(self, payments):
        self.payments = payments
        self.engine = payments.engine
        self.lock = RLock()
        self.signal = Event()
        self.stopping = Event()
        self.thread = None
        with self.engine.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                    request_key TEXT NOT NULL, input_hash TEXT NOT NULL,
                    goal TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL,
                    conversation TEXT NOT NULL, model_info TEXT NOT NULL,
                    turns INTEGER NOT NULL DEFAULT 0, question TEXT, error TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(task_id,request_key)
                );
                CREATE TABLE IF NOT EXISTS agent_actions (
                    run_id TEXT NOT NULL REFERENCES agent_runs(id), slot INTEGER NOT NULL,
                    call_id TEXT NOT NULL, name TEXT NOT NULL, arguments TEXT NOT NULL,
                    result TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id,slot)
                );
                CREATE TABLE IF NOT EXISTS agent_payment_refs (
                    run_id TEXT NOT NULL REFERENCES agent_runs(id), reference TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, payload TEXT NOT NULL, request_key TEXT NOT NULL,
                    payment_id TEXT, PRIMARY KEY(run_id,reference)
                );
            ''')
            if 'executor' not in {row['name'] for row in db.execute('PRAGMA table_info(agent_runs)')}:
                db.execute("ALTER TABLE agent_runs ADD COLUMN executor TEXT NOT NULL DEFAULT 'legacy_model'")
            db.execute("UPDATE agent_runs SET status='interrupted',error=?,updated_at=? WHERE status IN ('running','queued')",
                ('The app restarted. Resume this task to keep the same invoice requests.', now()))

    def start(self):
        with self.lock:
            if self.thread is None:
                self.thread = Thread(target=self._work, name='tavrel-invoice-agent', daemon=True)
                self.thread.start()

    def close(self):
        self.stopping.set()
        self.signal.set()
        if self.thread:
            self.thread.join(timeout=1)

    def _row(self, db, run_id, task_id=None):
        row = db.execute('SELECT * FROM agent_runs WHERE id=?', (run_id,)).fetchone()
        if row is None or (task_id is not None and row['task_id'] != task_id):
            raise PolicyError('agent_run_not_found', 'Agent task not found.', 404)
        return dict(row)

    def get(self, run_id, task_id=None):
        with self.engine.connection() as db:
            row = self._row(db, run_id, task_id)
            result = {key: row[key] for key in ('id', 'task_id', 'request_key', 'goal', 'status', 'executor', 'error', 'created_at', 'updated_at')}
            result['actions'] = [dict(action) for action in db.execute(
                'SELECT slot,name,arguments,result,status,created_at FROM agent_actions WHERE run_id=? ORDER BY slot', (run_id,))]
            for action in result['actions']:
                try:
                    action['arguments'] = json.loads(action['arguments'])
                except ValueError:
                    action['arguments'] = {'invalid_json': True}
                action['result'] = json.loads(action['result']) if action['result'] else None
            ids = [ref['payment_id'] for ref in db.execute(
                'SELECT DISTINCT payment_id FROM agent_payment_refs WHERE run_id=? AND payment_id IS NOT NULL', (run_id,))]
            result['payments'] = [self.payments._intent(payment_id, db, row['task_id']) for payment_id in ids]
            result['invoices'] = json.loads(row['source']) if row['executor'] == EXECUTOR else []
            return result

    def list(self, task_id):
        with self.engine.connection() as db:
            self.engine.task(task_id, db)
            ids = [row['id'] for row in db.execute('SELECT id FROM agent_runs WHERE task_id=? ORDER BY created_at DESC LIMIT 20', (task_id,))]
        return {'runs': [self.get(run_id, task_id) for run_id in ids], 'executor': EXECUTOR}

    def _invoices(self, task_id, invoices, db):
        if not isinstance(invoices, list) or not 1 <= len(invoices) <= MAX_INVOICES:
            raise PolicyError('invalid_invoice_batch', 'Add 1 to 20 invoices before starting the task.')
        policy = self.payments.policy(task_id, db)
        normalized, references = [], set()
        for item in invoices:
            if not isinstance(item, dict) or set(item) != {'invoice_reference', 'recipient', 'amount', 'purpose'}:
                raise PolicyError('invalid_invoice', 'Each invoice needs a reference, recipient, exact amount, and purpose.')
            if any(not isinstance(value, str) for value in item.values()):
                raise PolicyError('invalid_invoice', 'Use text for each invoice field and an exact decimal amount.')
            reference = item['invoice_reference'].strip()
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', reference) or reference in references:
                raise PolicyError('invalid_invoice_reference', 'Use unique invoice references: up to 80 letters, digits, underscores, or hyphens.')
            references.add(reference)
            purpose = item['purpose'].strip()
            if not 1 <= len(purpose) <= 1000:
                raise PolicyError('invalid_payment_purpose', 'Describe each invoice payment in up to 1,000 characters.')
            recipient = item['recipient'].strip()
            normalized.append({'invoice_reference': reference, 'recipient': account_id(policy['recipients'].get(recipient, recipient)),
                'amount': token_amount(units(item['amount'], False)), 'purpose': purpose})
        return normalized

    def create(self, task_id, goal, request_key, invoices):
        if not isinstance(goal, str) or not 1 <= len(goal.strip()) <= 200:
            raise PolicyError('invalid_agent_goal', 'Give this payment task a name of up to 200 characters.')
        if not isinstance(request_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', request_key):
            raise PolicyError('invalid_request_key', 'Use a stable task key of up to 100 letters, digits, underscores, or hyphens.')
        goal = goal.strip()
        input_hash = digest(encode({'goal': goal, 'invoices': invoices}))
        with self.lock, self.engine.transaction() as db:
            task = self.engine.task(task_id, db)
            existing = db.execute('SELECT id,input_hash FROM agent_runs WHERE task_id=? AND request_key=?', (task_id, request_key)).fetchone()
            if existing:
                if existing['input_hash'] != input_hash:
                    raise PolicyError('idempotency_conflict', 'This task key already identifies different invoices.', 409)
                run_id = existing['id']
            else:
                if task['paused']:
                    raise PolicyError('task_paused', 'Resume this agent before starting a payment task.', 409)
                normalized = self._invoices(task_id, invoices, db)
                if db.execute("SELECT COUNT(*) FROM agent_runs WHERE executor=? AND status IN ('queued','running')", (EXECUTOR,)).fetchone()[0] >= 8:
                    raise PolicyError('agent_queue_full', 'Eight tasks are already active. Wait or stop a task before starting another.', 409)
                run_id = 'run_' + uuid.uuid4().hex[:16]
                stamp = now()
                db.execute('INSERT INTO agent_runs(id,task_id,request_key,input_hash,goal,source,status,conversation,model_info,created_at,updated_at,executor) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                    (run_id, task_id, request_key, input_hash, goal, encode(normalized), 'queued', '[]', '{}', stamp, stamp, EXECUTOR))
                actions = [('read_rules', {}), ('read_source', {})] + [('prepare_payment', invoice) for invoice in normalized] + [('finish', {})]
                for slot, (name, arguments) in enumerate(actions):
                    db.execute('INSERT INTO agent_actions VALUES(?,?,?,?,?,?,?,?)', (run_id, slot, f'action_{slot}', name, encode(arguments), None, 'pending', stamp))
                self.engine.event(db, 'agent_run_created', 'Started a deterministic invoice task with exact payment instructions.', task_id, run_id, 'agent')
        self.signal.set()
        return self.get(run_id, task_id)

    def resume(self, run_id, task_id=None):
        with self.lock, self.engine.transaction() as db:
            row = self._row(db, run_id, task_id)
            if row['executor'] != EXECUTOR:
                raise PolicyError('legacy_agent_task', 'This earlier task is history. Start a new invoice task with exact payment details.', 409)
            if row['status'] in ('queued', 'running'):
                return self.get(run_id, task_id)
            if row['status'] not in ('interrupted', 'failed'):
                raise PolicyError('agent_run_finished', 'This task has ended. Start a new task for new invoices.', 409)
            if self.engine.task(row['task_id'], db)['paused']:
                raise PolicyError('task_paused', 'Resume this agent before continuing its payment task.', 409)
            if db.execute("SELECT COUNT(*) FROM agent_runs WHERE executor=? AND status IN ('queued','running')", (EXECUTOR,)).fetchone()[0] >= 8:
                raise PolicyError('agent_queue_full', 'Wait for an active task to finish before resuming.', 409)
            db.execute("UPDATE agent_actions SET status='pending',result=NULL WHERE run_id=? AND status='error'", (run_id,))
            db.execute("UPDATE agent_runs SET status='queued',error=NULL,updated_at=? WHERE id=?", (now(), run_id))
        self.signal.set()
        return self.get(run_id, task_id)

    def cancel(self, run_id, task_id=None):
        with self.lock, self.engine.transaction() as db:
            row = self._row(db, run_id, task_id)
            if row['status'] not in ('completed', 'cancelled'):
                db.execute("UPDATE agent_runs SET status='cancelled',updated_at=? WHERE id=?", (now(), run_id))
                self.engine.event(db, 'agent_run_cancelled', 'Stopped future invoice preparation. Existing payments and holds are unchanged.', row['task_id'], run_id)
        return self.get(run_id, task_id)

    def _work(self):
        while not self.stopping.is_set():
            self.signal.wait()
            self.signal.clear()
            while not self.stopping.is_set():
                with self.engine.connection() as db:
                    row = db.execute("SELECT id FROM agent_runs WHERE executor=? AND status='queued' ORDER BY created_at LIMIT 1", (EXECUTOR,)).fetchone()
                if row is None:
                    break
                self.advance(row['id'])

    def advance(self, run_id):
        with self.lock, self.engine.transaction() as db:
            row = self._row(db, run_id)
            if row['executor'] != EXECUTOR or row['status'] != 'queued':
                return
            db.execute("UPDATE agent_runs SET status='running',updated_at=? WHERE id=?", (now(), run_id))
        try:
            while not self.stopping.is_set():
                with self.lock:
                    with self.engine.connection() as db:
                        row = self._row(db, run_id)
                        if row['status'] != 'running':
                            return
                        action = db.execute("SELECT * FROM agent_actions WHERE run_id=? AND status='pending' ORDER BY slot LIMIT 1", (run_id,)).fetchone()
                    if action is None:
                        return
                    self._action(row, dict(action))
        except Exception:
            with self.lock, self.engine.transaction() as db:
                db.execute("UPDATE agent_runs SET status='failed',error=?,updated_at=? WHERE id=? AND status='running'",
                    ('The task was interrupted. Resume it to reuse the same invoice requests.', now(), run_id))

    def _action(self, run, action):
        name = action['name']
        try:
            if name == 'read_rules':
                with self.engine.connection() as db:
                    policy = self.payments.policy(run['task_id'], db)
                    account = self.payments._account(db)
                    result = {'network': 'zkVerify Volta', 'asset': 'tVFY', 'policy': policy,
                        'account_available_units': str(int(account['limit_units']) - int(account['reserved_units']) - int(account['spent_units']))}
            elif name == 'read_source':
                result = {'invoice_count': len(json.loads(run['source']))}
            elif name == 'prepare_payment':
                payment = self._prepare(run, json.loads(action['arguments']))
                result = {key: payment[key] for key in ('id', 'recipient', 'sender', 'amount', 'purpose', 'status', 'reason', 'settlement_verified')}
            elif name == 'finish':
                result = {'status': 'preparation_finished'}
            else:
                raise PolicyError('agent_action_forbidden', 'This task contains an unsupported action.', 403)
        except PolicyError as error:
            result = {'error': error.code, 'message': str(error)}
        with self.engine.transaction() as db:
            failed = bool(result.get('error'))
            db.execute('UPDATE agent_actions SET result=?,status=? WHERE run_id=? AND slot=?', (encode(result), 'error' if failed else 'done', run['id'], action['slot']))
            status = 'failed' if failed else 'completed' if name == 'finish' else 'running'
            db.execute('UPDATE agent_runs SET status=?,error=?,turns=turns+1,updated_at=? WHERE id=?',
                (status, result.get('message') if failed else None, now(), run['id']))

    def _prepare(self, run, invoice):
        reference = invoice['invoice_reference']
        payload = {key: invoice[key] for key in ('recipient', 'amount', 'purpose')}
        fingerprint = digest(encode(payload))
        with self.engine.transaction() as db:
            ref = db.execute('SELECT * FROM agent_payment_refs WHERE run_id=? AND reference=?', (run['id'], reference)).fetchone()
            if ref and ref['fingerprint'] != fingerprint:
                raise PolicyError('idempotency_conflict', 'This invoice reference already identifies a different payment.', 409)
            if ref is None:
                key = 'invoice_' + digest(encode({'task': run['task_id'], 'reference': reference}))
                db.execute('INSERT INTO agent_payment_refs VALUES(?,?,?,?,?,?)', (run['id'], reference, fingerprint, encode(payload), key, None))
            ref = dict(db.execute('SELECT * FROM agent_payment_refs WHERE run_id=? AND reference=?', (run['id'], reference)).fetchone())
        if ref['payment_id']:
            return self.payments.intent(ref['payment_id'], run['task_id'])
        payment = self.payments.prepare(run['task_id'], **json.loads(ref['payload']), request_key=ref['request_key'])
        with self.engine.transaction() as db:
            db.execute('UPDATE agent_payment_refs SET payment_id=? WHERE run_id=? AND reference=?', (payment['id'], run['id'], reference))
        return payment
