"""Invoice payment task runner. Reads real instructions; cannot approve or sign."""
import argparse
import json
from pathlib import Path
import time

from .client import TavrelClient, GatewayError
from .runtime import read_task_connection


def run_task(connection, instructions, task_key):
    client = TavrelClient(connection['gateway_url'], connection['task_token'])
    planned = client.request('POST', '/v1/agent/payments/task', {'task_key': task_key, 'payments': instructions})
    return client, planned


def main():
    parser = argparse.ArgumentParser(description='Route invoice payments through your Tavrel agent’s rules and follow their result.')
    parser.add_argument('task_id')
    parser.add_argument('--file', required=True, help='JSON array of actual recipient/amount/purpose instructions')
    parser.add_argument('--key', required=True, help='Stable task key; reuse it when retrying the same invoices')
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--connection', help='Agent connection JSON downloaded from the app')
    source.add_argument('--data-dir', default='.tavrel', help='Directory containing this agent’s saved connection file')
    parser.add_argument('--watch', type=int, default=0, help='Watch for up to this many seconds while a person reviews and signs')
    args = parser.parse_args()
    if not 0 <= args.watch <= 3600:
        parser.error('Choose a watch duration between 0 and 3600 seconds.')
    try:
        if args.connection:
            connection = json.loads(Path(args.connection).read_text(encoding='utf-8'))
            if connection.get('task_id') != args.task_id:
                raise ValueError('Connection file belongs to another agent.')
        else:
            connection = read_task_connection(Path(args.data_dir), args.task_id)
        path = Path(args.file)
        if path.stat().st_size > 32768:
            raise ValueError('Invoice instruction files must be at most 32 KB.')
        invoices = json.loads(path.read_text(encoding='utf-8'))
        client, planned = run_task(connection, invoices, args.key)
        intents = planned['intents']
        print(json.dumps({'task_key': args.key, 'intents': intents}, indent=2))
        for payment in intents:
            print(f"{payment['status']}: {payment['amount']} tVFY — {payment['purpose']}\n{connection['gateway_url']}/payments/{payment['id']}", flush=True)
        deadline = time.monotonic() + args.watch
        states = {p['id']: p['status'] for p in intents}
        while args.watch and time.monotonic() < deadline and any(state not in ('settled','failed','expired','denied','blocked') for state in states.values()):
            time.sleep(min(5, max(0, deadline - time.monotonic())))
            for payment_id in states:
                payment = client.request('GET', '/v1/agent/payments/' + payment_id)
                if payment['status'] != states[payment_id]:
                    states[payment_id] = payment['status']
                    print(f"{payment_id}: {payment['status']}", flush=True)
        return 0
    except (OSError, ValueError, RuntimeError, GatewayError, KeyError) as error:
        parser.exit(2, f'Tavrel agent: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
