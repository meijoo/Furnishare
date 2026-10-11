import pytest
from fastapi.testclient import TestClient

from app import catalog, realize
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_lamp_kind_and_default_dims():
    assert catalog.lamp_kind_from_text('arc floor lamp') == 'arc'
    assert catalog.lamp_kind_from_text('torchiere uplight') == 'torchiere'
    assert catalog.lamp_kind_from_text('standing lamp') == 'floor'
    assert catalog.lamp_kind_from_text('task lamp') == 'desk'
    assert catalog.lamp_kind_from_text('mini accent lamp') == 'accent'
    assert catalog.default_dims_for('lamp', 'arc floor lamp') == catalog.LAMP_DIMS['arc']
    assert catalog.default_dims_for('lamp', 'green lamp') == catalog.LAMP_DIMS['table']
    assert catalog.infer_category('brass torchiere') == 'lamp'
    assert catalog.infer_category('arc lamp') == 'lamp'


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
    plump = realize.infer_form('sofa', 'Overstuffed cloud couch deep seat')
    assert plump['arm_bulk'] == 'plump' and plump['back_bulk'] == 'thick'
    slim = realize.infer_form('sofa', 'Mid-century tuxedo apartment sofa')
    assert slim['arm_bulk'] == 'slim' and slim['seat_rise'] == 'low'
    assert realize.infer_form('bed', 'platform bed with tufted headboard')['headboard'] == 'tufted'
    assert realize.infer_form('desk', 'oak trestle desk with drawers')['leg_style'] == 'trestle'
    arc = realize.infer_form('lamp', 'Brushed brass arc floor lamp')
    assert arc['kind'] == 'arc'
    mushroom = realize.infer_form('lamp', 'Ceramic gourd table lamp mushroom shade')
    assert mushroom['kind'] == 'table' and mushroom['shade'] == 'mushroom' and mushroom['base'] == 'gourd'
    torch = realize.infer_form('lamp', 'Black torchiere uplight')
    assert torch['kind'] == 'torchiere'
    desk = realize.infer_form('lamp', 'Adjustable desk lamp cone shade')
    assert desk['kind'] == 'desk' and desk['shade'] == 'cone'
    assert realize.infer_form('lamp', 'Tripod floor lamp wide shade')['base'] == 'tripod'
    assert realize.infer_form('lamp', 'Tripod floor lamp wide shade')['shade_scale'] == 'large'


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
