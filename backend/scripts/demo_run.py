"""Rehearse the signature demo against a running backend, simulating the three roommates' texts.

  ../.venv/bin/python scripts/demo_run.py [--base http://127.0.0.1:8000] [--image ../ml/data/rooms/<file>]

Uses fake handles unless backend/data/members.json already links real numbers.
"""
import argparse
import time

import httpx

HANDLES = {'emily': '+15550000001', 'maya': '+15550000002', 'alex': '+15550000003'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8000')
    ap.add_argument('--image')
    args = ap.parse_args()
    c = httpx.Client(base_url=args.base, timeout=60)
    run = str(time.time_ns())

    def text(who, body):
        t = time.perf_counter()
        c.post('/messages/inbound', json={'event_id': f'{run}-{who}-{body}', 'sender_handle': HANDLES[who], 'text': body})
        print(f'  {who:>5} > {body!r}  ({(time.perf_counter() - t) * 1000:.0f} ms)')

    def state():
        return c.get('/households/demo/state').json()

    def show(label):
        s = state()
        p = s['proposal']
        items = ', '.join(f"{i['title']} ${i['price_cents'] / 100:.2f}" for i in p['items'])
        shares = ', '.join(f"{m} ${v / 100:.2f}" for m, v in p['shares'].items())
        print(f"[{label}] v{p['version']} {p['status']}: {items} | {shares}")
        f = s['finance']
        if f['purchase']:
            print(f"    purchase {f['purchase']['state']} ({f['purchase']['simulator']})")
        for r in f['reimbursements']:
            print(f"    {r['from_member']} -> {r['to_member']} ${r['amount_cents'] / 100:.2f}: {(r['operation'] or {}).get('state', 'awaiting authorization')}")
        return s

    def wait(pred, label, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            s = state()
            if pred(s):
                return show(label)
            time.sleep(0.5)
        show(label + ' (TIMED OUT)')
        raise SystemExit(1)

    print(c.get('/health').json())
    c.post('/demo/reset', params={'clear_handles': 'true'})
    if args.image:
        with open(args.image, 'rb') as f:
            print('inspiration:', c.post('/households/demo/inspiration', files={'file': f}).json())
    show('start')
    for who in HANDLES:
        text(who, f'JOIN {who}')
    t = time.perf_counter()
    text('alex', 'My limit for the sofa is $100')
    s = show('after limit')
    print(f"    revision visible after {(time.perf_counter() - t):.2f}s: {s['proposal']['explanation']}")
    v = s['proposal']['version']
    for who in HANDLES:
        text(who, f'YES v{v}')
    show('approved')
    text('emily', 'PAY')
    wait(lambda s: (s['finance']['purchase'] or {}).get('state') == 'confirmed', 'purchase confirmed')
    text('maya', 'SEND')
    text('alex', 'SEND')
    wait(lambda s: s['finance']['settled'], 'settled')
    print('\nOutbound messages:')
    for m in c.get('/debug/outbound').json()[-12:]:
        print(f"  -> {m['to_handle']}: {m['text'][:140]}")
    print('\nTimings:', c.get('/debug/timings').json())


if __name__ == '__main__':
    main()
