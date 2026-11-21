"""A warmed native signature worker; it receives public login data only."""
import json
import os
from pathlib import Path
from queue import Empty, Full, Queue
import shutil
import subprocess
from threading import RLock, Thread
from time import monotonic

from .engine import PolicyError


class SignatureVerifier:
    def __init__(self, timeout=12):
        self.timeout = timeout
        self.lock = RLock()
        self.process = None
        self.reader = None
        self.replies = None
        self.ready = False
        self.closed = False
        self.sequence = 0

    @staticmethod
    def unavailable():
        return PolicyError('wallet_verifier_unavailable', 'Wallet verification is unavailable. Check the Tavrel server and reconnect.', 503)

    @staticmethod
    def _read(process, replies):
        try:
            while True:
                line = process.stdout.readline(8193)
                if not line or len(line) > 8192 or not line.endswith('\n'):
                    break
                replies.put_nowait(json.loads(line))
        except (OSError, ValueError, Full):
            pass
        finally:
            try:
                replies.put_nowait(None)
            except Full:
                pass

    def _stop(self):
        process, reader = self.process, self.reader
        self.process = self.reader = self.replies = None
        self.ready = False
        if process:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            for stream in (process.stdin, process.stdout):
                if stream:
                    stream.close()
        if reader:
            reader.join(timeout=1)

    def _spawn(self):
        if self.closed:
            raise self.unavailable()
        if self.process and self.process.poll() is None:
            return
        self._stop()
        node = shutil.which('node')
        if not node:
            raise self.unavailable()
        script = Path(__file__).with_name('wallet_verify.bundle.mjs')
        if not script.exists():
            script = script.with_name('wallet_verify.mjs')
        self.process = subprocess.Popen([node, str(script), '--serve'], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8', bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.replies = Queue(maxsize=4)
        self.reader = Thread(target=self._read, args=(self.process, self.replies), daemon=True,
            name='tavrel-wallet-verifier')
        self.reader.start()

    def start(self):
        with self.lock:
            try:
                self._spawn()
            except (OSError, PolicyError):
                return False
        return True

    def verify(self, message, signature, account):
        payload = {'message': message, 'signature': signature, 'account': account}
        if not self.lock.acquire(timeout=self.timeout):
            raise self.unavailable()
        try:
            deadline = monotonic() + self.timeout
            self._spawn()
            if not self.ready:
                if self.replies.get(timeout=max(0, deadline - monotonic())) != {'ready': True}:
                    raise ValueError('invalid handshake')
                self.ready = True
            self.sequence += 1
            payload['id'] = self.sequence
            encoded = json.dumps(payload, ensure_ascii=True) + '\n'
            if len(encoded) > 8192:
                return False
            self.process.stdin.write(encoded)
            self.process.stdin.flush()
            result = self.replies.get(timeout=max(0, deadline - monotonic()))
            if not isinstance(result, dict) or type(result.get('id')) is not int or result['id'] != self.sequence or type(result.get('valid')) is not bool:
                raise ValueError('invalid worker response')
            return result['valid']
        except (Empty, OSError, ValueError, subprocess.SubprocessError):
            self._stop()
            raise self.unavailable() from None
        finally:
            self.lock.release()

    def close(self):
        with self.lock:
            self.closed = True
            self._stop()
