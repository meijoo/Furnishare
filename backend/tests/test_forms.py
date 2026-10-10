"""Photo-read design features: only schema-valid values survive, and the catalog merges them into style.form."""
import json

from app import catalog, forms


def test_clean_keeps_only_valid_values():
    raw = {'arm_style': 'rolled', 'back_style': 'spiky', 'seat_cushions': 3, 'back_cushions': 9, 'skirt': 'yes',
           'tufted_seat': True, 'surface': 'velvet', 'headboard': 'tufted'}
    assert forms.clean('sofa', raw) == {'arm_style': 'rolled', 'seat_cushions': 3, 'tufted_seat': True,
                                        'surface': 'velvet'}
    assert forms.clean('tv', {'bezel': 'frame', 'surface': 'plasma'}) == {'bezel': 'frame'}
    assert forms.clean('unknown', {'surface': 'oak', 'x': 1}) == {'surface': 'oak'}
    assert forms.clean('desk', {'primary_hex': ' #b8865a', 'accent_surface': 'black_metal',
                                'accent_hex': 'not-a-color', 'pedestal_open': True}) == {
        'primary_hex': '#B8865A', 'accent_surface': 'black_metal', 'pedestal_open': True}


def test_response_schema_matches_categories():
    for cat in catalog.CATEGORIES:
        props = forms.response_schema(cat)['properties']
        assert set(props) == {'surface', *forms.SCHEMA[cat]}
    assert forms.response_schema('sofa')['properties']['seat_cushions'] == {'type': 'integer', 'minimum': 1, 'maximum': 4}


def test_catalog_merges_forms(tmp_path, monkeypatch):
    path = tmp_path / 'forms.json'
    path.write_text(json.dumps({'demo-fjord-bed': {'headboard': 'slatted', 'surface': 'oak', 'bogus': 1}}))
    monkeypatch.setattr(forms, 'FORMS_PATH', path)
    catalog._cache['mtime'] = None
    try:
        bed = catalog.get('demo-fjord-bed')
        other = catalog.get('demo-cove-bed')
    finally:
        catalog._cache['mtime'] = None
    assert bed['style']['form'] == {'headboard': 'slatted', 'surface': 'oak'}
    assert 'form' not in other['style']
