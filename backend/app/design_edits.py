"""Room-scoped collaborative scene edits, separate from approved payment proposals."""
import copy
import json
import uuid

from . import catalog, core, db

FIELDS = {'objects', 'products', 'groups', 'owned', 'applied', 'poses',
          'hiddenItems', 'removedItems', 'dismissedOptions'}


def key(hid):
    return f'design-edits:{hid}'


def reset(hid):
    db.kv_set(key(hid), {'epoch': str(uuid.uuid4()), 'edits': {}})


def snapshot(hid):
    with db.LOCK:
        saved = db.kv_get(key(hid))
        if saved is None:
            reset(hid)
            saved = db.kv_get(key(hid))
    result = copy.deepcopy(saved)
    for product in result['edits'].get('products', []):
        known = catalog.get(product['id'])
        if known:
            for field in ('asset_url', 'local_image'):
                if known.get(field):
                    product[field] = known[field]
    return result


def _merge(current, before, after):
    """Apply only this client's changes; preserve other clients' independent edits."""
    if before == after:
        return copy.deepcopy(current)
    if isinstance(before, dict) and isinstance(after, dict):
        result = copy.deepcopy(current) if isinstance(current, dict) else {}
        for field in before.keys() - after.keys():
            result.pop(field, None)
        for field, value in after.items():
            if field not in before:
                result[field] = copy.deepcopy(value)
            elif before[field] != value:
                result[field] = _merge(result.get(field), before[field], value)
        return result
    if isinstance(before, list) and isinstance(after, list):
        current = current if isinstance(current, list) else []
        values = before + after + current
        if values and all(isinstance(v, dict) and ('id' in v or 'object_id' in v) for v in values):
            def index(items):
                return {v.get('object_id', v.get('id')): v for v in items}
            return list(_merge(index(current), index(before), index(after)).values())
        if all(isinstance(v, str) for v in values):
            removed = set(before) - set(after)
            return list(dict.fromkeys([v for v in current if v not in removed] + [v for v in after if v not in before]))
    return copy.deepcopy(after)


def _validate(edits):
    if edits.keys() - FIELDS or len(json.dumps(edits)) > 2_000_000:
        raise ValueError('Invalid or oversized room edits.')
    for field in ('objects', 'products', 'groups', 'owned'):
        items = edits.get(field, [])
        identity = 'object_id' if field == 'objects' else 'id'
        if not isinstance(items, list) or len(items) > 500 or any(
                not isinstance(item, dict) or not isinstance(item.get(identity), str) for item in items):
            raise ValueError(f'Invalid {field}.')
    for field in ('hiddenItems', 'removedItems'):
        if not isinstance(edits.get(field, []), list) or any(not isinstance(v, str) for v in edits.get(field, [])):
            raise ValueError(f'Invalid {field}.')
    for field in ('applied', 'poses', 'dismissedOptions'):
        if not isinstance(edits.get(field, {}), dict):
            raise ValueError(f'Invalid {field}.')


def patch(hid, member_id, epoch, before, after):
    core.member(hid, member_id)
    _validate(before)
    _validate(after)
    with db.tx() as connection:
        saved = db.kv_get(key(hid))
        if not saved or saved['epoch'] != epoch:
            raise core.Conflict('This room was reset. Reload its current design.')
        merged = _merge(saved['edits'], before, after)
        _validate(merged)
        saved['edits'] = merged
        connection.execute('UPDATE kv SET value=? WHERE key=?', (json.dumps(saved), key(hid)))
        db.bump(connection, hid)
    return snapshot(hid)
