"""Wallet challenge authentication, registered operator ownership, revocable sessions."""
from http.cookies import SimpleCookie
import json
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import time

from .engine import PolicyError, digest
from .payments import account_id, wallet_address


COOKIE = "tavrel_operator"
SESSION_SECONDS = 1800


def verify_signature(message, signature, account):
    node = shutil.which("node")
    if not node:
        raise PolicyError("wallet_verifier_unavailable", "Install Node and run npm install before wallet sign-in.", 503)
    try:
        script = Path(__file__).with_name("wallet_verify.bundle.mjs")
        if not script.exists():
            script = Path(__file__).with_name("wallet_verify.mjs")
        result = subprocess.run([node, str(script)],
            input=json.dumps({"message": message, "signature": signature, "account": account}),
            capture_output=True, text=True, timeout=12, check=True)
        return json.loads(result.stdout).get("valid") is True
    except (OSError, subprocess.SubprocessError, ValueError):
        raise PolicyError("wallet_verifier_unavailable", "Wallet verification is unavailable. Check the local Node dependencies.", 503) from None


class WalletAuth:
    def __init__(self, engine, verifier=verify_signature):
        self.engine = engine
        self.verifier = verifier
        self.pairing_ticket = secrets.token_urlsafe(32)
        self.pairing_expires = time.time() + 900
        with engine.connection() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS operator_wallets(account TEXT PRIMARY KEY, created REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS wallet_challenges(id TEXT PRIMARY KEY, account TEXT NOT NULL,
                message TEXT NOT NULL, origin TEXT NOT NULL, expires REAL NOT NULL,
                consumed INTEGER NOT NULL DEFAULT 0, bootstrap INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS operator_sessions(token_hash TEXT PRIMARY KEY, account TEXT NOT NULL,
                expires REAL NOT NULL);
            """)

    def configured(self):
        with self.engine.connection() as db:
            return db.execute("SELECT 1 FROM operator_wallets LIMIT 1").fetchone() is not None

    def session(self, cookie_header):
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header or "")
            token = cookie[COOKIE].value if COOKIE in cookie else ""
        except Exception:
            return None
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            return None
        with self.engine.connection() as db:
            row = db.execute("SELECT s.account FROM operator_sessions s JOIN operator_wallets w ON s.account=w.account WHERE s.token_hash=? AND s.expires>?", (digest(token), time.time())).fetchone()
            return {"account": row["account"]} if row else None

    def challenge(self, address, origin, ticket=None, *, browser_setup=False):
        account = account_id(address)
        valid_ticket = isinstance(ticket, str) and time.time() < self.pairing_expires and secrets.compare_digest(ticket, self.pairing_ticket)
        with self.engine.transaction() as db:
            registered = db.execute("SELECT 1 FROM operator_wallets WHERE account=?", (account,)).fetchone()
            has_owner = db.execute("SELECT 1 FROM operator_wallets LIMIT 1").fetchone()
            if not registered and has_owner:
                raise PolicyError("operator_wallet_required", "Connect the wallet that was first used with this Tavrel account.", 403)
            if not registered and not (valid_ticket or browser_setup):
                raise PolicyError("operator_wallet_required", "Open the Tavrel app in your browser to connect your first wallet.", 403)
            db.execute("DELETE FROM wallet_challenges WHERE expires<?", (time.time(),))
            if db.execute("SELECT COUNT(*) AS count FROM wallet_challenges WHERE consumed=0").fetchone()["count"] >= 100:
                raise PolicyError("too_many_challenges", "Too many sign-in requests. Wait for earlier requests to expire.", 429)
            challenge_id = secrets.token_hex(16)
            expires = time.time() + 300
            message = ("Tavrel sign-in\n\n" + f"Origin: {origin}\nNetwork: zkverify-volta\nPublic account: {account}\n"
                + f"Nonce: {secrets.token_hex(32)}\nExpires at: {int(expires)}\n\n"
                + "Sign this message to authenticate with Tavrel. This does not authorize a payment or move funds.")
            db.execute("INSERT INTO wallet_challenges(id,account,message,origin,expires,bootstrap) VALUES(?,?,?,?,?,?)",
                (challenge_id, account, message, origin, expires, int(not registered)))
            return {"challenge_id": challenge_id, "message": message, "expires_at": expires}

    def verify(self, challenge_id, signature, origin):
        if not isinstance(challenge_id, str) or not re.fullmatch(r"[a-f0-9]{32}", challenge_id) or not isinstance(signature, str) or not re.fullmatch(r"0x[0-9a-fA-F]{128,132}", signature):
            raise PolicyError("invalid_wallet_signature", "Provide a valid wallet challenge and Substrate signature.")
        with self.engine.connection() as db:
            row = db.execute("SELECT * FROM wallet_challenges WHERE id=?", (challenge_id,)).fetchone()
        if not row or row["consumed"] or row["expires"] <= time.time() or row["origin"] != origin:
            raise PolicyError("wallet_challenge_expired", "This sign-in request expired or was already used. Connect again.", 401)
        if not self.verifier(row["message"], signature, row["account"]):
            raise PolicyError("invalid_wallet_signature", "The signature does not match this account and sign-in request.", 401)
        token = secrets.token_urlsafe(32)
        with self.engine.transaction() as db:
            # Recheck after cryptographic verification to serialize concurrent replies.
            current = db.execute("SELECT * FROM wallet_challenges WHERE id=?", (challenge_id,)).fetchone()
            if current["consumed"] or current["expires"] <= time.time():
                raise PolicyError("wallet_challenge_expired", "This sign-in request expired or was already used.", 401)
            registered = db.execute("SELECT 1 FROM operator_wallets WHERE account=?", (row["account"],)).fetchone()
            if not registered:
                if not row["bootstrap"] or db.execute("SELECT 1 FROM operator_wallets LIMIT 1").fetchone():
                    raise PolicyError("operator_wallet_required", "Connect the wallet that was first used with this Tavrel account.", 403)
                db.execute("INSERT INTO operator_wallets VALUES(?,?)", (row["account"], time.time()))
            db.execute("UPDATE wallet_challenges SET consumed=1 WHERE id=?", (challenge_id,))
            db.execute("DELETE FROM operator_sessions WHERE expires<?", (time.time(),))
            db.execute("INSERT INTO operator_sessions VALUES(?,?,?)", (digest(token), row["account"], time.time() + SESSION_SECONDS))
            self.engine.event(db, "operator_wallet_login", "Verified a native wallet login signature. No payment was signed.")
        return {"authenticated": True, "account": row["account"], "address": wallet_address(row["account"])}, f"{COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_SECONDS}"

    def logout(self, cookie_header):
        cookie = SimpleCookie()
        cookie.load(cookie_header or "")
        if COOKIE in cookie:
            with self.engine.transaction() as db:
                db.execute("DELETE FROM operator_sessions WHERE token_hash=?", (digest(cookie[COOKIE].value),))
        return f"{COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"
