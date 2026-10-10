import pytest
from fastapi.testclient import TestClient

from app import catalog, realize
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_parse_listing_dimensions():
    sofa = catalog.parse_listing_dimensions('Article sofa 84" W x 36" D x 33" H', 'sofa')
    assert sofa == {'width': round(84 * 0.0254, 3), 'depth': round(36 * 0.0254, 3), 'height': round(33 * 0.0254, 3)}
    inches = catalog.parse_listing_dimensions('KIVIK 90" x 37" x 35"', 'sofa')
    assert inches['width'] == round(90 * 0.0254, 3)
    cm = catalog.parse_listing_dimensions('Sofa 218 x 95 x 83 cm', 'sofa')
    assert cm['width'] == round(2.18, 3)
    assert catalog.parse_listing_dimensions('navy velvet sofa', 'sofa') is None


def test_infer_form_from_title():
    sofa = realize.infer_form('sofa', 'Article Dark Blue Velvet 3 Seater Sofa Tufted Seat')
    assert sofa['surface'] == 'velvet'
    assert sofa['back_style'] == 'tufted'
    assert sofa['seat_cushions'] == 3
    assert realize.infer_form('sofa', 'English rolled-arm sofa')['arm_style'] == 'rolled'
    assert realize.infer_form('bed', 'platform bed with tufted headboard')['headboard'] == 'tufted'
    assert realize.infer_form('desk', 'oak trestle desk with drawers')['leg_style'] == 'trestle'


def test_realize_endpoint_uses_title_form(client, monkeypatch):
    monkeypatch.setattr(realize._pool, 'submit', lambda *a, **k: None)
    r = client.post('/products/realize', json={
        'id': 'live-test-sofa',
        'title': 'Rolled arm velvet sofa',
        'category': 'sofa',
        'dimensions_m': {'width': 2.1, 'depth': 0.9, 'height': 0.85},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['form']['arm_style'] == 'rolled'
    assert body['form']['surface'] == 'velvet'
    assert body['status'] in ('building', 'ready')
    assert client.get('/products/realize/live-test-sofa').status_code == 200
    assert client.get('/products/realize/missing').status_code == 404
