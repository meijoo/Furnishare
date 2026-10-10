"""Identity disjointness of build_pairs. Embeddings and labels here are SYNTHETIC fixtures."""
import itertools
import random
from collections import Counter

import pytest
import torch

from build_pairs import annotator_disagreement, build, check_disjoint
from splits import near_duplicate_groups

DIM = 12


def _random_unit(gen):
    return torch.nn.functional.normalize(torch.randn(DIM, generator=gen), dim=0)


@pytest.fixture
def world():
    gen = torch.Generator().manual_seed(0)
    rooms = {f"room{i}.jpg": _random_unit(gen) for i in range(20)}
    rooms["room0_copy.jpg"] = rooms["room0.jpg"].clone()  # near duplicate of room0
    products, cats = {}, {}
    for cat in ("sofa", "rug"):
        for i in range(12):
            pid = f"{cat}-{i}"
            products[pid], cats[pid] = _random_unit(gen), cat
    products["sofa-0-dup"] = products["sofa-0"] + 0.001 * torch.randn(DIM, generator=gen)
    cats["sofa-0-dup"] = "sofa"
    rng = random.Random(0)
    labels = []
    for room in rooms:
        for cat in ("sofa", "rug"):
            ids = [p for p in products if cats[p] == cat]
            for a, b in rng.sample(list(itertools.combinations(ids, 2)), 8):
                labels.append({"room_id": room, "product_a_id": a, "product_b_id": b, "furniture_category": cat,
                               "preferred_product": rng.choice([a, b, a, b, "tie"]), "annotator_id": "x"})
    return rooms, products, cats, labels


def test_splits_are_identity_disjoint(world):
    rooms, products, cats, labels = world
    result = build(labels, rooms, products, cats)
    check_disjoint(result["splits"])
    pools = result["pools"]
    for pool, payload in result["splits"].items():
        assert all(pools["rooms"][r] == pool for r in payload["room_ids"])
        assert all(pools["products"][p] == pool for p in payload["a_ids"] + payload["b_ids"])
        n = len(payload["preference"])
        assert payload["room"].shape == payload["a"].shape == payload["b"].shape == (n, DIM)
    stats = result["stats"]
    kept = sum(stats["examples"].values())
    assert kept + stats["dropped_crossing_pools"] + stats["unresolved_vote_splits"] == stats["unique_binary_pairs"]
    assert stats["dropped_crossing_pools"] > 0
    assert stats["tie_rows"] == len(result["ties"]) > 0


def test_near_duplicates_share_a_pool(world):
    rooms, products, cats, labels = world
    pools = build(labels, rooms, products, cats)["pools"]
    assert pools["rooms"]["room0.jpg"] == pools["rooms"]["room0_copy.jpg"]
    assert pools["products"]["sofa-0"] == pools["products"]["sofa-0-dup"]
    assert ["sofa-0", "sofa-0-dup"] in pools["product_groups"]


def test_existing_manifest_assignments_are_kept(world):
    rooms, products, cats, labels = world
    first = build(labels, rooms, products, cats)["pools"]
    manifest = {"rooms": first["rooms"], "products": first["products"]}
    rooms_more = dict(rooms, **{"new_room.jpg": torch.nn.functional.normalize(torch.ones(DIM), dim=0)})
    second = build(labels, rooms_more, products, cats, manifest)["pools"]
    assert all(second["rooms"][r] == p for r, p in first["rooms"].items())
    assert second["products"] == first["products"]


def test_every_category_gets_products_in_every_pool(world):
    rooms, products, cats, labels = world
    pools = build(labels, rooms, products, cats)["pools"]["products"]
    for cat in ("sofa", "rug"):
        assert {pools[p] for p in products if cats[p] == cat} == {"train", "validation", "test"}


def test_small_category_still_gets_two_products_per_pool():
    from splits import assign_pools
    groups = [[f"p{i}"] for i in range(7)]
    pools, _ = assign_pools(groups, {}, {f"p{i}": "rug" for i in range(7)})
    counts = Counter(pools.values())
    assert counts["validation"] >= 2 and counts["test"] >= 2 and counts["train"] >= 2


def test_check_disjoint_detects_leak():
    leaky = {"train": {"room_ids": ["r1"], "a_ids": ["p1"], "b_ids": ["p2"]},
             "test": {"room_ids": ["r1"], "a_ids": ["p3"], "b_ids": ["p4"]}}
    with pytest.raises(AssertionError):
        check_disjoint(leaky)


def test_annotator_disagreement_counts_conflicts():
    rows = [
        {"room_id": "r", "product_a_id": "p", "product_b_id": "q", "preferred_product": "p", "annotator_id": "u1"},
        {"room_id": "r", "product_a_id": "q", "product_b_id": "p", "preferred_product": "q", "annotator_id": "u2"},
        {"room_id": "r", "product_a_id": "p", "product_b_id": "s", "preferred_product": "p", "annotator_id": "u1"},
        {"room_id": "r", "product_a_id": "p", "product_b_id": "s", "preferred_product": "p", "annotator_id": "u2"},
    ]
    d = annotator_disagreement(rows)
    assert d["pairs_with_multiple_annotators"] == 2
    assert d["pairs_with_conflicting_answers"] == 1
    assert d["pairs_with_opposite_winners"] == 1


def test_near_duplicate_groups_threshold():
    v = torch.nn.functional.normalize(torch.randn(3, DIM, generator=torch.Generator().manual_seed(3)), dim=1)
    emb = torch.stack([v[0], v[0] * 1.0001, v[1], v[2]])
    groups = near_duplicate_groups(["a", "b", "c", "d"], emb)
    assert ["a", "b"] in groups and ["c"] in groups and ["d"] in groups


def test_room_subfolder_views_share_a_group():
    gen = torch.Generator().manual_seed(5)
    emb = torch.nn.functional.normalize(torch.randn(3, DIM, generator=gen), dim=1)
    from splits import room_identity
    groups = near_duplicate_groups(["loft/a.jpg", "loft/b.jpg", "other.jpg"], emb, identity_key=room_identity)
    assert ["loft/a.jpg", "loft/b.jpg"] in groups and ["other.jpg"] in groups
