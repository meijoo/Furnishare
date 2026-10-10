"""Capital One Nessie sandbox client plus a clearly labeled local simulator.

Observed against https://api.nessieisreal.com with a real key on 2026-10-10:
- `amount` is an integer (149.99 is truncated to 149), so amounts are sent as integer USD cents.
- `status` is one of pending | cancelled | completed. Records never leave `pending` on their own and cannot be
  updated (no PUT/PATCH), and account balances never change. Records are therefore created as `completed` once the
  member has explicitly authorized the operation; the sandbox is a record of the authorized simulated movement.
- POST /accounts/{id}/purchases requires merchant_id, medium, amount.
- POST /accounts/{id}/transfers requires transaction_date, status, amount, description and rejects any recipient
  field (medium, payee_id, ...), so the payee account is recorded in the description.
- POST /merchants requires `category` as a string.
- GET /purchases/{id} returns an API-gateway auth error, so lookups list the account's records. Transfer listings
  use `id` rather than `_id`.
"""
import threading
import time
import uuid
from datetime import date

import httpx

from . import config


class Uncertain(Exception):
    """The request may or may not have been applied (timeout, connection reset, 5xx)."""


class Rejected(Exception):
    """The API definitively refused the request (4xx validation, auth, insufficient funds)."""


def map_status(raw: str | None) -> str:
    s = (raw or '').lower()
    if s in ('executed', 'completed', 'complete', 'posted', 'confirmed', 'success'):
        return 'confirmed'
    if s in ('cancelled', 'canceled', 'failed', 'declined', 'rejected'):
        return 'failed'
    if s == 'pending':
        return 'pending'
    return 'unknown'


def _object(body):
    if isinstance(body, dict):
        return body.get('objectCreated') or body
    return {}


class LiveNessie:
    mode = 'live'

    def __init__(self, key: str, base: str):
        self.key, self.base = key, base
        self.http = httpx.Client(timeout=httpx.Timeout(15, connect=5))

    def _req(self, method, path, json=None):
        try:
            r = self.http.request(method, f'{self.base}{path}', params={'key': self.key}, json=json)
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            raise Uncertain(f'{type(e).__name__}: {e}') from e
        if r.status_code >= 500:
            raise Uncertain(f'HTTP {r.status_code}: {r.text[:200]}')
        if r.status_code >= 400:
            raise Rejected(f'HTTP {r.status_code}: {r.text[:300]}')
        try:
            return r.json()
        except ValueError:
            return {}

    # Setup
    def create_customer(self, first, last):
        return _object(self._req('POST', '/customers', {
            'first_name': first, 'last_name': last,
            'address': {'street_number': '1', 'street_name': 'Demo St', 'city': 'Arlington', 'state': 'VA', 'zip': '22201'}}))['_id']

    def create_account(self, customer_id, nickname, balance_cents):
        return _object(self._req('POST', f'/customers/{customer_id}/accounts', {
            'type': 'Checking', 'nickname': nickname, 'rewards': 0, 'balance': balance_cents // 100}))['_id']

    def create_merchant(self, name):
        return _object(self._req('POST', '/merchants', {
            'name': name, 'category': 'furniture',
            'address': {'street_number': '1', 'street_name': 'Demo St', 'city': 'Arlington', 'state': 'VA', 'zip': '22201'},
            'geocode': {'lat': 38.88, 'lng': -77.1}}))['_id']

    def get_account(self, account_id):
        return self._req('GET', f'/accounts/{account_id}')

    def balance_cents(self, account_id) -> int | None:
        bal = self.get_account(account_id).get('balance')
        return round(bal * 100) if isinstance(bal, (int, float)) else None

    # Money movement
    def create_purchase(self, account_id, merchant_id, amount_cents, description):
        body = self._req('POST', f'/accounts/{account_id}/purchases', {
            'merchant_id': merchant_id, 'medium': 'balance', 'purchase_date': date.today().isoformat(),
            'amount': int(amount_cents), 'status': 'completed', 'description': f'{description} (USD cents)'})
        obj = _object(body)
        return obj.get('_id'), map_status(obj.get('status')), body

    def create_transfer(self, account_id, payee_account_id, amount_cents, description):
        body = self._req('POST', f'/accounts/{account_id}/transfers', {
            'amount': int(amount_cents), 'transaction_date': date.today().isoformat(), 'status': 'completed',
            'description': f'{description} to account {payee_account_id} (USD cents)'})
        obj = _object(body)
        return obj.get('_id'), map_status(obj.get('status')), body

    def find(self, kind, account_id, external_id=None, description=None):
        """Locate a purchase/transfer by id, or by our op key embedded in the description."""
        if external_id:
            try:
                obj = self._req('GET', f'/{kind}s/{external_id}')
                if isinstance(obj, dict) and obj.get('_id'):
                    return obj
            except (Rejected, Uncertain):
                pass
        try:
            listing = self._req('GET', f'/accounts/{account_id}/{kind}s')
        except Rejected as e:
            if 'HTTP 404' in str(e):
                return None
            raise
        for obj in listing if isinstance(listing, list) else []:
            obj.setdefault('_id', obj.get('id'))
            if (external_id and obj.get('_id') == external_id) or (description and description in (obj.get('description') or '')):
                return obj
        return None


class MockNessie:
    """In-process simulator for development without a key. Every state it reports is labeled 'mock'."""
    mode = 'mock'

    def __init__(self):
        self.lock = threading.Lock()
        self.accounts, self.txns = {}, {}

    def create_customer(self, first, last):
        return f'mockcust-{first.lower()}'

    def create_account(self, customer_id, nickname, balance_cents):
        aid = f'mockacct-{customer_id.split("-")[-1]}'
        with self.lock:
            self.accounts.setdefault(aid, balance_cents)
        return aid

    def create_merchant(self, name):
        return 'mockmerchant-furniture'

    def balance_cents(self, account_id):
        return self.accounts.get(account_id)

    def _txn(self, kind, account_id, amount_cents, description, payee=None):
        tid = f'mock{kind}-{uuid.uuid4().hex[:10]}'
        with self.lock:
            self.txns[tid] = {'_id': tid, 'kind': kind, 'account': account_id, 'payee': payee, 'amount': amount_cents,
                              'description': description, 'status': 'pending', 'created': time.time()}
        return tid, 'pending', {'objectCreated': self.txns[tid]}

    def create_purchase(self, account_id, merchant_id, amount_cents, description):
        return self._txn('purchase', account_id, amount_cents, description)

    def create_transfer(self, account_id, payee_account_id, amount_cents, description):
        return self._txn('transfer', account_id, amount_cents, description, payee_account_id)

    def find(self, kind, account_id, external_id=None, description=None):
        with self.lock:
            for t in self.txns.values():
                if t['kind'] != kind or (external_id and t['_id'] != external_id):
                    continue
                if not external_id and (not description or description not in t['description']):
                    continue
                if t['status'] == 'pending' and time.time() - t['created'] > 2:
                    t['status'] = 'executed'
                    self.accounts[t['account']] = self.accounts.get(t['account'], 0) - t['amount']
                    if t['payee']:
                        self.accounts[t['payee']] = self.accounts.get(t['payee'], 0) + t['amount']
                return dict(t)
        return None


_client = None


def client():
    global _client
    if _client is None:
        _client = LiveNessie(config.NESSIE_API_KEY, config.NESSIE_BASE_URL) if config.NESSIE_MODE == 'live' else MockNessie()
    return _client
