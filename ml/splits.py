"""Identity-disjoint pool assignment shared by the labeling tool and build_pairs.py.

Rooms and products are each grouped by near-duplicate embeddings (cosine > threshold) and
whole groups are assigned to train/validation/test. Assignments are persisted in
data/split_manifest.json and never changed once made, so labels collected for a pool stay valid.
New groups are assigned deterministically (sha256 order) to the pool furthest below its target
fraction within their stratum (category for products), which keeps every category represented.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import torch

POOLS = ("train", "validation", "test")
DEFAULT_FRACTIONS = {"train": 0.7, "validation": 0.15, "test": 0.15}
DUPLICATE_COSINE = 0.97
MIN_GROUPS_PER_POOL = 2  # a pool needs >= 2 products of a category to form any pair


def near_duplicate_groups(ids: list[str], embeddings: torch.Tensor, threshold: float = DUPLICATE_COSINE,
                          identity_key=None) -> list[list[str]]:
    """Union-find over pairs with cosine > threshold (and ids sharing identity_key(id), if given).
    Returns groups of ids (sorted)."""
    n = len(ids)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    if n > 1:
        emb = torch.nn.functional.normalize(embeddings.float(), dim=-1)
        sims = emb @ emb.T
        rows, cols = torch.nonzero(torch.triu(sims > threshold, diagonal=1), as_tuple=True)
        for i, j in zip(rows.tolist(), cols.tolist()):
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[max(ri, rj)] = min(ri, rj)
    if identity_key is not None:
        first: dict[str, int] = {}
        for i, identity in enumerate(ids):
            j = first.setdefault(identity_key(identity), i)
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[max(ri, rj)] = min(ri, rj)
    groups: dict[int, list[str]] = {}
    for i, identity in enumerate(ids):
        groups.setdefault(find(i), []).append(identity)
    return sorted((sorted(g) for g in groups.values()), key=lambda g: g[0])


def _hash_key(group: list[str], seed: int) -> str:
    return hashlib.sha256(f"{seed}:{group[0]}".encode()).hexdigest()


def assign_pools(groups: list[list[str]], existing: dict[str, str], strata: dict[str, str] | None = None,
                 fractions: dict[str, float] = DEFAULT_FRACTIONS, seed: int = 0) -> tuple[dict[str, str], list[list[str]]]:
    """Return ({id: pool}, conflicted_groups). Existing assignments win; a near-duplicate group whose
    members were previously split across pools is moved entirely to its majority pool (reported)."""
    assignment: dict[str, str] = {}
    conflicted = []
    counts: dict[str, Counter] = {}
    stratum_of = lambda g: (strata or {}).get(g[0], "_all")
    new_groups = []
    for group in groups:
        prior = Counter(existing[i] for i in group if existing.get(i) in POOLS)
        if prior:
            if len(prior) > 1:
                conflicted.append(group)
            pool = sorted(prior.items(), key=lambda kv: (-kv[1], POOLS.index(kv[0])))[0][0]
            for i in group:
                assignment[i] = pool
            counts.setdefault(stratum_of(group), Counter())[pool] += 1
        else:
            new_groups.append(group)
    totals = Counter(stratum_of(g) for g in groups)
    for group in sorted(new_groups, key=lambda g: _hash_key(g, seed)):
        stratum = stratum_of(group)
        c = counts.setdefault(stratum, Counter())
        placed = sum(c.values())
        target_total = max(totals[stratum], placed + 1)
        candidates = POOLS
        if totals[stratum] >= MIN_GROUPS_PER_POOL * len(POOLS):
            needy = tuple(p for p in POOLS if c[p] < MIN_GROUPS_PER_POOL)
            candidates = needy or POOLS
        pool = max(candidates, key=lambda p: (fractions[p] * target_total - c[p], fractions[p]))
        for i in group:
            assignment[i] = pool
        c[pool] += 1
    return assignment, conflicted


def room_identity(room_id: str) -> str:
    """Images in a subfolder of data/rooms/ are views of one room: data/rooms/<room>/<view>.jpg."""
    return room_id.split("/", 1)[0]


def load_manifest(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass
    return {"rooms": {}, "products": {}}


def compute_pools(room_ids: list[str], room_emb: torch.Tensor, product_ids: list[str], product_emb: torch.Tensor,
                  product_categories: list[str], manifest: dict, threshold: float = DUPLICATE_COSINE,
                  fractions: dict[str, float] = DEFAULT_FRACTIONS) -> dict:
    """Extend manifest pools with any new identities. Returns {rooms, products, room_groups, product_groups, conflicts}."""
    room_groups = near_duplicate_groups(room_ids, room_emb, threshold, room_identity) if room_ids else []
    rooms, room_conflicts = assign_pools(room_groups, manifest.get("rooms", {}), None, fractions)
    product_groups = []
    for category in sorted(set(product_categories)):
        idx = [i for i, c in enumerate(product_categories) if c == category]
        product_groups += near_duplicate_groups([product_ids[i] for i in idx], product_emb[idx], threshold)
    strata = dict(zip(product_ids, product_categories))
    products, product_conflicts = assign_pools(product_groups, manifest.get("products", {}), strata, fractions)
    return {"rooms": rooms, "products": products,
            "room_groups": [g for g in room_groups if len(g) > 1],
            "product_groups": [g for g in product_groups if len(g) > 1],
            "conflicts": {"rooms": room_conflicts, "products": product_conflicts}}
