from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

sys.path.insert(0, str(Path.cwd()))
from tavrel.auth import verify_signature
from tavrel.wallet_verifier import SignatureVerifier

message = 'Tavrel verifier timing, offline fixture only'
fixture = subprocess.run(['node', 'tests/wallet-fixture.mjs'], input=json.dumps({'message': message, 'label': 'verifier-benchmark'}),
    capture_output=True, text=True, check=True, timeout=20)
signed = json.loads(fixture.stdout)
args = (message, signed['signature'], signed['account'])
def measure(work):
    start = perf_counter()
    assert work(*args) is True
    return round((perf_counter() - start) * 1000, 3)
cold = [measure(verify_signature) for _ in range(3)]
worker = SignatureVerifier()
try:
    worker.start()
    startup = measure(worker.verify)
    warm = [measure(worker.verify) for _ in range(3)]
    assert worker.verify('Changed login message', signed['signature'], signed['account']) is False
finally:
    worker.close()
result = {'observed_at': datetime.now(timezone.utc).isoformat(), 'native_crypto': True,
    'public_offline_fixture': True, 'actual_signature_verified': True, 'changed_message_rejected': True,
    'separate_process_milliseconds': cold, 'first_worker_verification_milliseconds': startup,
    'reused_worker_milliseconds': warm, 'installed_wallet_tested': False,
    'network_requests': False, 'signed_transfer': False, 'submitted_transfer': False,
    'timing_limit': 'Three calls per mode on this Windows host; excludes extension and human signing time.'}
Path('artifacts/wallet-verifier-check.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
