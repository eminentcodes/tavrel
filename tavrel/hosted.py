"""Railway entrypoint: one persistent ledger with an explicitly pinned wallet owner."""
import os
from pathlib import Path
import re
import signal
from urllib.parse import urlsplit

from .engine import Engine
from .payments import account_id
from .runtime import GatewayLock, operator_key
from .server import Gateway


def public_origin(value):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.port not in (None, 443) or parsed.path not in ('', '/') or parsed.query or parsed.fragment
                or not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?', parsed.hostname)):
            raise ValueError()
        return 'https://' + parsed.hostname.lower()
    except (ValueError, TypeError):
        raise ValueError('Set TAVREL_PUBLIC_ORIGIN to your HTTPS domain, without a path or custom port.') from None


def settings(environ=None):
    environ = os.environ if environ is None else environ
    domain = environ.get('RAILWAY_PUBLIC_DOMAIN', '')
    origin = public_origin(environ.get('TAVREL_PUBLIC_ORIGIN') or ('https://' + domain if domain else ''))
    owner = environ.get('TAVREL_OWNER_WALLET', '')
    if not owner:
        raise ValueError('Set TAVREL_OWNER_WALLET to the public Substrate address you will connect.')
    owner = account_id(owner)
    try:
        port = int(environ.get('PORT', '8080'))
        if not 1 <= port <= 65535:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('PORT must be between 1 and 65535.') from None
    directory = Path(environ.get('TAVREL_DATA_DIR', '/data')).resolve()
    return {'origin': origin, 'owner': owner, 'port': port, 'directory': directory}


def main():
    config = settings()
    lock = GatewayLock(config['directory'])
    gateway = None
    try:
        key = operator_key(config['directory'], create=True)
        engine = Engine(config['directory'] / 'ledger.sqlite3')
        gateway = Gateway(('0.0.0.0', config['port']), engine, key, quiet=True,
            public_origin=config['origin'], owner_wallet=config['owner'])
        engine.recover_interrupted()
        def stop(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, stop)
        print(f"Tavrel ready at {config['origin']}", flush=True)
        try:
            gateway.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            pass
    finally:
        if gateway:
            gateway.server_close()
        lock.close()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError) as error:
        raise SystemExit(str(error)) from None
