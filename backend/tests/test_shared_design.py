"""Three demo devices share independent edits and reject changes from before reset."""
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app import catalog, core
from app.main import app


def test_three_devices_share_edits_and_approvals():
    with TestClient(app) as emily:
        maya, alex = TestClient(app), TestClient(app)
        try:
            emily.post('/demo/reset', params={'full_reset': 'true'})
            initial = emily.get('/households/demo/state').json()
            epoch = initial['design_edits']['epoch']
            version = initial['proposal']['version']
            sofa_slot = f'proposal-{version}-sofa-blue'
            edits = [
                (emily, 'emily', {'poses': {'obj-sofa': {'x': 0.1, 'z': -1.0, 'rotation': 0.5}}}),
                (maya, 'maya', {'applied': {'obj-sofa': 'sofa-compact'}, 'hiddenItems': ['obj-rug']}),
                (alex, 'alex', {'removedItems': ['obj-tv'], 'dismissedOptions': {sofa_slot: ['sofa-green']}}),
            ]

            def update(entry):
                device, member, after = entry
                return device.patch('/households/demo/design-edits', json={
                    'member_id': member, 'epoch': epoch, 'before': {}, 'after': after})

            with ThreadPoolExecutor(max_workers=3) as pool:
                responses = list(pool.map(update, edits))
            assert all(response.status_code == 200 for response in responses)
            snapshots = [device.get('/households/demo/state', params={'member_id': member}).json()
                         for device, member in [(emily, 'emily'), (maya, 'maya'), (alex, 'alex')]]
            assert all(state['design_edits'] == snapshots[0]['design_edits'] for state in snapshots)
            shared = snapshots[0]['design_edits']['edits']
            assert shared['poses']['obj-sofa']['x'] == 0.1
            assert shared['applied']['obj-sofa'] == 'sofa-compact'
            assert shared['hiddenItems'] == ['obj-rug']
            assert shared['removedItems'] == ['obj-tv']
            assert shared['dismissedOptions'][sofa_slot] == ['sofa-green']
            assert snapshots[0]['state_version'] == initial['state_version'] + 3
            for device, member in [(emily, 'emily'), (maya, 'maya'), (alex, 'alex')]:
                assert device.post(f'/households/demo/proposals/{version}/approve', json={'member_id': member}).status_code == 200
            assert alex.get('/households/demo/state').json()['proposal']['status'] == 'approved'
            bedroom = maya.get('/households/demo-bed-emily/state').json()
            assert maya.patch('/households/demo-bed-emily/design-edits', json={
                'member_id': 'maya', 'epoch': bedroom['design_edits']['epoch'],
                'before': {}, 'after': {'hiddenItems': ['obj-bed']}}).status_code == 403

            emily.post('/demo/reset', params={'full_reset': 'true'})
            fresh = maya.get('/households/demo/state').json()
            assert fresh['design_edits']['epoch'] != epoch
            assert fresh['design_edits']['edits'] == {}
            stale = alex.patch('/households/demo/design-edits', json={
                'member_id': 'alex', 'epoch': epoch, 'before': {}, 'after': {'removedItems': ['obj-sofa']}})
            assert stale.status_code == 409
            assert core.scene_objects('demo')
        finally:
            maya.close()
            alex.close()


def test_concurrent_changes_to_same_option_group_preserve_both():
    with TestClient(app) as client:
        client.post('/demo/reset')
        epoch = client.get('/households/demo/state').json()['design_edits']['epoch']
        original = {'groups': [{'id': 'options', 'productIDs': ['first', 'second'], 'showingProductID': 'first'}]}

        def patch(before, after, member):
            return client.patch('/households/demo/design-edits', json={
                'member_id': member, 'epoch': epoch, 'before': before, 'after': after})

        assert patch({}, original, 'emily').status_code == 200
        added = {'groups': [{'id': 'options', 'productIDs': ['first', 'second', 'third'], 'showingProductID': 'first'}]}
        removed = {'groups': [{'id': 'options', 'productIDs': ['first'], 'showingProductID': 'first'}]}
        assert patch(original, added, 'maya').status_code == 200
        assert patch(original, removed, 'alex').status_code == 200
        shared = client.get('/households/demo/state').json()['design_edits']['edits']
        assert shared['groups'][0]['productIDs'] == ['first', 'third']


def test_reset_seeds_mock_furniture_without_shopping(monkeypatch):
    def no_shopping(*args, **kwargs):
        raise AssertionError('The mock demo must not search for products')

    monkeypatch.setattr(catalog, 'live_search', no_shopping)
    with TestClient(app) as client:
        response = client.post('/demo/reset', params={'full_reset': 'true'})
        assert response.status_code == 200
        for hid in ('demo', 'demo-bed-emily', 'demo-bed-maya', 'demo-bed-alex'):
            state = client.get(f'/households/{hid}/state').json()
            assert len(state['scene']['objects']) == 4
            assert state['scene']['validation']['ok']
            assert all(catalog.get(item['product_id'])['source_type'] == 'demo' for item in state['scene']['objects'])
