"""Wallet-owned ledgers and opaque task-token routing for the public service."""
from pathlib import Path
from threading import RLock

from .agent_runs import AgentRuns
from .agent_wallets import AgentWallets
from .engine import Engine, PolicyError, digest
from .payments import PaymentLedger, account_id
from .proofs import PolicyProofs
from .settlement import Settlement


class AccountRuntime:
    def __init__(self, engine, source=None):
        self.engine = engine
        self.payments = source.payments if source else PaymentLedger(engine)
        self.settlement = source.settlement if source else Settlement(self.payments)
        self.policy_proofs = source.policy_proofs if source else PolicyProofs(self.settlement)
        self.agent_runs = source.agent_runs if source else AgentRuns(self.payments)
        self.agent_wallets = source.agent_wallets if source else AgentWallets(self.settlement)
        self.started = False

    def start(self):
        if not self.started:
            self.engine.recover_interrupted()
            self.settlement.start()
            self.agent_runs.start()
            self.agent_wallets.start()
            self.started = True

    def close(self):
        self.agent_wallets.close()
        self.agent_runs.close()
        self.settlement.close()


class WalletAccounts:
    def __init__(self, gateway, legacy_owner=None):
        self.gateway = gateway
        self.registry = gateway.engine
        self.directory = Path(self.registry.database).resolve().parent
        self.lock = RLock()
        self.contexts = {}
        self.running = False
        self.closed = False
        with self.registry.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS public_accounts (
                    account TEXT PRIMARY KEY, legacy INTEGER NOT NULL DEFAULT 0 CHECK(legacy IN (0,1))
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_legacy_account ON public_accounts(legacy) WHERE legacy=1;
                CREATE TABLE IF NOT EXISTS public_task_tokens (
                    token_hash TEXT PRIMARY KEY, account TEXT NOT NULL REFERENCES public_accounts(account),
                    task_id TEXT NOT NULL, UNIQUE(account,task_id)
                );
            ''')
        with self.registry.transaction() as db:
            if not db.execute('SELECT 1 FROM public_accounts LIMIT 1').fetchone():
                owners = [row['account'] for row in db.execute('SELECT account FROM operator_wallets')]
                has_data = (db.execute('SELECT 1 FROM tasks LIMIT 1').fetchone()
                    or db.execute("SELECT 1 FROM payment_account WHERE limit_units!='0' OR spent_units!='0' OR reserved_units!='0'").fetchone())
                if len(owners) > 1 and has_data:
                    raise ValueError('The existing shared ledger has multiple owners; migrate it before public account startup.')
                owner = owners[0] if len(owners) == 1 else account_id(legacy_owner) if legacy_owner else None
                if owners and legacy_owner and account_id(legacy_owner) not in owners:
                    raise ValueError('The legacy wallet does not match the existing ledger owner. Existing data was preserved.')
                if has_data and not owner:
                    raise ValueError('Set TAVREL_OWNER_WALLET once to associate the existing unowned ledger with its wallet.')
                if owner:
                    db.execute('INSERT OR IGNORE INTO operator_wallets VALUES(?,strftime(\'%s\',\'now\'))', (owner,))
                    db.execute('INSERT INTO public_accounts VALUES(?,1)', (owner,))

    @staticmethod
    def register(db, account):
        # Registration and its account mapping commit with the same verified login.
        db.execute('INSERT OR IGNORE INTO public_accounts(account) VALUES(?)', (account,))

    def start(self):
        with self.lock:
            self.running = True
            with self.registry.connection() as db:
                accounts = [row['account'] for row in db.execute('SELECT account FROM public_accounts')]
            for account in accounts:
                self.for_wallet(account)

    def for_wallet(self, wallet):
        account = account_id(wallet)
        with self.lock:
            if self.closed:
                raise PolicyError('account_unavailable', 'The app is restarting. Reconnect shortly.', 503)
            with self.registry.transaction() as db:
                if not db.execute('SELECT 1 FROM operator_wallets WHERE account=?', (account,)).fetchone():
                    raise PolicyError('unauthorized', 'Sign in with this wallet first.', 401)
                db.execute('INSERT OR IGNORE INTO public_accounts(account) VALUES(?)', (account,))
                legacy = bool(db.execute('SELECT legacy FROM public_accounts WHERE account=?', (account,)).fetchone()['legacy'])
            if account not in self.contexts:
                if legacy:
                    context = AccountRuntime(self.registry, self.gateway)
                else:
                    directory = self.directory / 'accounts' / account[2:]
                    engine = Engine(directory / 'ledger.sqlite3', self.registry.services)
                    context = AccountRuntime(engine)
                self.contexts[account] = context
                self.sync_tokens(account, context)
            context = self.contexts[account]
            if self.running:
                context.start()
            return context

    def sync_tokens(self, account, context):
        with self.lock:
            with context.engine.connection() as db:
                tasks = [(row['token_hash'], account, row['id']) for row in db.execute('SELECT id,token_hash FROM tasks')]
            with self.registry.transaction() as db:
                db.execute('DELETE FROM public_task_tokens WHERE account=?', (account,))
                db.executemany('INSERT INTO public_task_tokens VALUES(?,?,?)', tasks)

    def for_token(self, token):
        with self.registry.connection() as db:
            row = db.execute('SELECT account FROM public_task_tokens WHERE token_hash=?', (digest(token),)).fetchone()
        if not row:
            raise PolicyError('unauthorized', 'The task token is invalid or has been rotated.', 401)
        context = self.for_wallet(row['account'])
        # The owning ledger remains authoritative, even if an index update was interrupted.
        context.engine.authenticate_task(token)
        return context

    def close(self):
        with self.lock:
            self.closed = True
            contexts = list(self.contexts.values())
        for context in contexts:
            context.close()
