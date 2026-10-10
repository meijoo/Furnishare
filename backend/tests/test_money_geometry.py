import math

import pytest

from app.geometry import overlaps, rect, validate_scene
from app.money import InfeasibleSplit, dollars, solve_split, validate_split

M = ['emily', 'maya', 'alex']


def test_signature_split():
    assert solve_split(45000, M, {'emily': 20000, 'maya': 20000, 'alex': 10000}) == {'emily': 17500, 'maya': 17500, 'alex': 10000}


def test_equal_split_with_remainder_cents():
    s = solve_split(10000, M, {})
    assert sum(s.values()) == 10000 and max(s.values()) - min(s.values()) == 1


def test_unlimited_member_absorbs_rest():
    assert solve_split(60000, M, {'emily': 20000, 'maya': 20000, 'alex': None}) == {'emily': 20000, 'maya': 20000, 'alex': 20000}
    assert solve_split(60000, M, {'emily': 10000, 'maya': 10000, 'alex': None})['alex'] == 40000


def test_infeasible_when_limits_too_low():
    with pytest.raises(InfeasibleSplit):
        solve_split(60000, M, {'emily': 20000, 'maya': 20000, 'alex': 10000})


def test_zero_limit_and_odd_cents():
    s = solve_split(10001, M, {'alex': 0})
    assert s['alex'] == 0 and sum(s.values()) == 10001


def test_rejects_float_money():
    with pytest.raises(ValueError):
        solve_split(100.0, M, {})
    with pytest.raises(ValueError):
        validate_split(100, {'a': 50, 'b': 49}, {})
    with pytest.raises(ValueError):
        validate_split(100, {'a': 60, 'b': 40}, {'a': 50})


def test_dollars():
    assert dollars(17500) == '$175' and dollars(10001) == '$100.01'


ROOM = {'width_m': 4.0, 'depth_m': 4.0, 'clearances': [{'label': 'door swing', 'x_m': 1.5, 'z_m': 1.5, 'width_m': 0.9, 'depth_m': 0.9}]}


def obj(oid, cat, x, z, w, d, rot=0.0):
    return {'object_id': oid, 'category': cat, 'position_m': [x, 0, z], 'rotation_y_rad': rot,
            'dimensions_m': {'width': w, 'depth': d, 'height': 0.8}}


def test_overlap_and_bounds():
    v = validate_scene(ROOM, [obj('a', 'sofa', 0, -1.5, 2, 0.9), obj('b', 'coffee_table', 0, -1.2, 1, 0.5)])
    assert [i['kind'] for i in v['issues']] == ['overlap']
    v = validate_scene(ROOM, [obj('a', 'sofa', 1.5, 0, 2, 0.9)])
    assert v['issues'][0]['kind'] == 'out_of_bounds'


def test_rotation_changes_footprint():
    assert validate_scene(ROOM, [obj('a', 'sofa', 1.4, 0, 0.9, 2.0)])['ok']
    assert not validate_scene(ROOM, [obj('a', 'sofa', 1.4, 0, 0.9, 2.0, rot=math.pi / 2)])['ok']


def test_rug_may_sit_under_furniture_but_clearance_blocks():
    assert validate_scene(ROOM, [obj('r', 'rug', 0, 0, 2, 1.6), obj('t', 'coffee_table', 0, 0, 1, 0.5)])['ok']
    v = validate_scene(ROOM, [obj('t', 'coffee_table', 1.4, 1.4, 0.6, 0.6)])
    assert v['issues'][0]['kind'] == 'clearance'


def test_touching_edges_do_not_overlap():
    assert not overlaps(rect(0, 0, 1, 1), rect(1, 0, 1, 1))
