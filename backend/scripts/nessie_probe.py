"""Validate the live Nessie sandbox contract before the demo. Creates throwaway sandbox records only.

  ../.venv/bin/python scripts/nessie_probe.py            # needs NESSIE_API_KEY in the repo-root .env

Prints every request/response so status semantics (pending vs executed, balance updates) can be confirmed.
"""
import json
import sys
import time
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402

if not config.NESSIE_API_KEY:
    raise SystemExit('Set NESSIE_API_KEY in the repo-root .env first.')

c = httpx.Client(base_url=config.NESSIE_BASE_URL, params={'key': config.NESSIE_API_KEY}, timeout=20)
ADDR = {'street_number': '1', 'street_name': 'Probe St', 'city': 'Arlington', 'state': 'VA', 'zip': '22201'}


def call(method, path, body=None):
    r = c.request(method, path, json=body)
    try:
        data = r.json()
    except ValueError:
        data = r.text
    print(f'\n{method} {path} -> {r.status_code}\n  sent: {json.dumps(body) if body else "-"}\n  got:  {json.dumps(data)[:600]}')
    return data


def oid(data):
    return (data.get('objectCreated') or data).get('_id') if isinstance(data, dict) else None


payer = oid(call('POST', '/customers', {'first_name': 'Probe', 'last_name': 'Payer', 'address': ADDR}))
debtor = oid(call('POST', '/customers', {'first_name': 'Probe', 'last_name': 'Debtor', 'address': ADDR}))
pa = oid(call('POST', f'/customers/{payer}/accounts', {'type': 'Checking', 'nickname': 'probe payer', 'rewards': 0, 'balance': 1000}))
da = oid(call('POST', f'/customers/{debtor}/accounts', {'type': 'Checking', 'nickname': 'probe debtor', 'rewards': 0, 'balance': 1000}))
merchant = oid(call('POST', '/merchants', {'name': 'Probe Furniture', 'category': 'furniture', 'address': ADDR,
                                           'geocode': {'lat': 38.88, 'lng': -77.1}}))
today = date.today().isoformat()
purchase = call('POST', f'/accounts/{pa}/purchases', {'merchant_id': merchant, 'medium': 'balance', 'purchase_date': today,
                                                      'amount': 450, 'status': 'completed', 'description': 'RAG to Rooms probe purchase (USD cents)'})
transfer = call('POST', f'/accounts/{da}/transfers', {'amount': 175, 'transaction_date': today, 'status': 'completed',
                                                      'description': f'RAG to Rooms probe transfer to account {pa} (USD cents)'})
for i in range(2):
    time.sleep(5 if i else 1)
    print(f'\n--- observation {i + 1} ---')
    call('GET', f'/accounts/{pa}/purchases')
    call('GET', f'/accounts/{da}/transfers')
    call('GET', f'/accounts/{pa}')
    call('GET', f'/accounts/{da}')
print('\nExpected (2026-10-10): both records 201 with status completed and integer amounts; balances unchanged.')
