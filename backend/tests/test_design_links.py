"""Photon shares current design links without changing the design or searching."""
import json
from test_group_invitations import client, invite, bind
from app import core, db, design_links, invitations, agent


def save_sofa_link():
    proposal = core.current_proposal('demo')
    sofa = next(p for p in proposal['items'] if p['category'] == 'sofa')
    sofa['source_url'] = 'https://shop.example/couch-current'
    with db.tx() as c:
        c.execute('UPDATE proposal_items SET product_json=? WHERE household_id=? AND version=? AND product_id=?',
                  (json.dumps(sofa), 'demo', proposal['version'], sofa['id']))
    return sofa


def test_photon_question_returns_current_links_without_preference_mutations(client, monkeypatch):
    invite(client)
    sofa = save_sofa_link()
    def unexpected(*args, **kwargs):
        raise AssertionError('Read-only question must not search or change preferences')
    monkeypatch.setattr(invitations, 'preference', unexpected)
    monkeypatch.setattr(agent, 'interpret', unexpected)
    before = core.current_proposal('demo')['version']
    response = client.post('/messages/inbound', json={'event_id': 'show-current-couches',
        'sender_handle': '+15550000001', 'text': 'Can I see what couches we are considering?'})
    assert response.status_code == 202
    reply = db.one('SELECT text FROM outbound_jobs WHERE dedupe_key=?', 'reply:show-current-couches')['text']
    assert sofa['title'] in reply and sofa['source_url'] in reply
    assert core.current_proposal('demo')['version'] == before
    assert invitations.suggestions('demo') == []


def test_group_questions_include_saved_design_options_and_removed_items(client):
    invitation = invite(client).json()
    bind(client, invitation)
    sofa = save_sofa_link()
    version = core.current_proposal('demo')['version']
    response = client.put('/households/demo/design-links', json={
        'proposal_version': version, 'removed_product_ids': [sofa['id']],
        'items': [{'id': 'my-candidate', 'title': 'Roommate couch option', 'category': 'sofa',
                   'source_url': 'https://shop.example/couch-option'},
                  {'id': 'lamp', 'title': 'Lamp', 'category': 'lamp', 'source_url': 'https://shop.example/lamp'}]})
    assert response.status_code == 200
    response = client.post('/messages/inbound', json={'event_id': 'group-show-couches',
        'sender_handle': '+15550000001', 'conversation_id': 'any;+;test-room',
        'text': 'Send links to the couches in our design'})
    assert response.status_code == 202
    reply = db.one('SELECT * FROM outbound_jobs WHERE dedupe_key=?', 'reply:group-show-couches')
    assert reply['conversation_id'] == 'any;+;test-room'
    assert 'https://shop.example/couch-option' in reply['text']
    assert 'couch-current' not in reply['text'] and 'shop.example/lamp' not in reply['text']


def test_empty_design_and_missing_links_are_honest(client):
    with db.tx() as c:
        c.execute("DELETE FROM proposals WHERE household_id='demo'")
        c.execute("DELETE FROM scene_objects WHERE household_id='demo'")
    assert 'no couches' in design_links.reply('demo', 'What couches are we considering?')
    db.kv_set('design-links:demo', {'items': [{'id': 'no-link', 'category': 'sofa', 'title': 'Custom couch', 'source_url': None}]})
    assert 'no shopping link' in design_links.reply('demo', 'Show our couches')
    assert design_links.reply('demo', 'Find new couches in blue') is None
