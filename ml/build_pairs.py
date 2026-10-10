"""Turn human labels into identity-disjoint train/validation/test pair files.

    ml/.venv/bin/python ml/build_pairs.py

Reads data/labels.jsonl + artifacts/{catalog,room}_embeddings.pt. Writes:
  data/{train,validation,test}.pt   (format train.py expects, plus id metadata)
  data/ties.jsonl                   (tie judgments, excluded from the binary model)
  data/split_manifest.json          (pool of every room/product identity, duplicate groups, stats)

Rooms and products are split into pools BEFORE examples are built; near-duplicate images
(cosine > 0.97) share a pool. An example is kept only if its room and both products are in the
same pool; others are dropped and counted. Repeated judgments of the same (room, pair) are
majority-voted into one example; exact splits are dropped.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import torch

from common import (ARTIFACTS_DIR, DATA_DIR, LABELS_PATH, ROOMS_DIR, SPLIT_MANIFEST_PATH, atomic_write_bytes,
                    atomic_write_json, read_jsonl, utc_now)
from splits import DEFAULT_FRACTIONS, DUPLICATE_COSINE, POOLS, compute_pools, load_manifest

REQUIRED = ("room_id", "product_a_id", "product_b_id", "furniture_category", "preferred_product", "annotator_id")


def pair_key(row: dict) -> tuple[str, str, str]:
    return (row["room_id"], *sorted((row["product_a_id"], row["product_b_id"])))


def annotator_disagreement(rows: list[dict]) -> dict:
    """Pairs judged by >=2 distinct annotators and how many of those have conflicting answers."""
    answers: dict[tuple, dict[str, str]] = defaultdict(dict)
    for row in rows:
        answers[pair_key(row)][row["annotator_id"]] = row["preferred_product"]
    multi = {k: v for k, v in answers.items() if len(v) >= 2}
    conflicting = [k for k, v in multi.items() if len(set(v.values())) > 1]
    opposite = [k for k, v in multi.items() if len(set(v.values()) - {"tie"}) > 1]
    return {"pairs_with_multiple_annotators": len(multi),
            "pairs_with_conflicting_answers": len(conflicting),
            "pairs_with_opposite_winners": len(opposite),
            "conflict_rate": (len(conflicting) / len(multi)) if multi else None,
            "examples": [list(k) for k in conflicting[:10]]}


def validate_rows(labels: list[dict], room_emb: dict, product_emb: dict, product_cat: dict):
    valid, invalid = [], Counter()
    for row in labels:
        if any(not row.get(k) for k in REQUIRED):
            invalid["missing_field"] += 1
        elif row["product_a_id"] == row["product_b_id"]:
            invalid["identical_products"] += 1
        elif row["room_id"] not in room_emb:
            invalid["unknown_room_or_unembedded"] += 1
        elif row["product_a_id"] not in product_emb or row["product_b_id"] not in product_emb:
            invalid["unknown_product_or_unembedded"] += 1
        elif not (product_cat[row["product_a_id"]] == product_cat[row["product_b_id"]] == row["furniture_category"]):
            invalid["category_mismatch"] += 1
        elif row["preferred_product"] not in (row["product_a_id"], row["product_b_id"], "tie"):
            invalid["bad_preferred_product"] += 1
        else:
            valid.append(row)
    return valid, dict(invalid)


def build(labels: list[dict], room_emb: dict[str, torch.Tensor], product_emb: dict[str, torch.Tensor],
          product_cat: dict[str, str], manifest: dict | None = None, seed: int = 0,
          fractions: dict[str, float] = DEFAULT_FRACTIONS, threshold: float = DUPLICATE_COSINE) -> dict:
    """Pure function: returns {"splits": {pool: payload}, "ties": [...], "pools": ..., "stats": ...}."""
    valid, invalid = validate_rows(labels, room_emb, product_emb, product_cat)
    disagreement = annotator_disagreement(valid)
    ties = [r for r in valid if r["preferred_product"] == "tie"]
    binary = [r for r in valid if r["preferred_product"] != "tie"]

    votes: dict[tuple, Counter] = defaultdict(Counter)
    meta: dict[tuple, dict] = {}
    for row in binary:
        key = pair_key(row)
        votes[key][row["preferred_product"]] += 1
        meta.setdefault(key, row)
    aggregated, unresolved = [], 0
    for key, counter in votes.items():
        (winner, n1), *rest = counter.most_common()
        if rest and rest[0][1] == n1:
            unresolved += 1
            continue
        room_id, p1, p2 = key
        aggregated.append({"room_id": room_id, "winner": winner, "loser": p2 if winner == p1 else p1,
                           "category": meta[key]["furniture_category"], "votes": sum(counter.values())})

    room_ids = sorted(room_emb)
    product_ids = sorted(product_emb)
    pools = compute_pools(room_ids, torch.stack([room_emb[r] for r in room_ids]) if room_ids else torch.empty(0),
                          product_ids, torch.stack([product_emb[p] for p in product_ids]),
                          [product_cat[p] for p in product_ids], manifest or {}, threshold, fractions)
    room_pool, product_pool = pools["rooms"], pools["products"]

    rng = random.Random(seed)
    per_split = {p: [] for p in POOLS}
    crossing = Counter()
    for ex in sorted(aggregated, key=lambda e: (e["room_id"], e["winner"], e["loser"])):
        assigned = {room_pool[ex["room_id"]], product_pool[ex["winner"]], product_pool[ex["loser"]]}
        if len(assigned) == 1:
            per_split[assigned.pop()].append(ex)
        else:
            room_in_neither = room_pool[ex["room_id"]] not in (product_pool[ex["winner"]], product_pool[ex["loser"]])
            crossing["room_pool_matches_neither_product" if room_in_neither else "products_in_different_pools"] += 1

    splits = {}
    dim = next(iter(product_emb.values())).shape[0]
    for pool, rows in per_split.items():
        room_t, a_t, b_t, pref, a_ids, b_ids = [], [], [], [], [], []
        for ex in rows:
            swap = rng.random() < 0.5
            a, b = (ex["loser"], ex["winner"]) if swap else (ex["winner"], ex["loser"])
            room_t.append(room_emb[ex["room_id"]]); a_t.append(product_emb[a]); b_t.append(product_emb[b])
            pref.append(0.0 if swap else 1.0); a_ids.append(a); b_ids.append(b)
        stack = lambda xs: torch.stack(xs).float() if xs else torch.empty(0, dim)
        splits[pool] = {"room": stack(room_t), "a": stack(a_t), "b": stack(b_t),
                        "preference": torch.tensor(pref, dtype=torch.float32),
                        "room_ids": [ex["room_id"] for ex in rows], "a_ids": a_ids, "b_ids": b_ids,
                        "categories": [ex["category"] for ex in rows], "embedding_dim": int(dim)}

    stats = {"label_rows": len(labels), "invalid_rows": invalid, "valid_rows": len(valid), "tie_rows": len(ties),
             "binary_rows": len(binary), "unique_binary_pairs": len(votes), "unresolved_vote_splits": unresolved,
             "dropped_crossing_pools": sum(crossing.values()), "dropped_crossing_breakdown": dict(crossing),
             "examples": {p: len(per_split[p]) for p in POOLS},
             "rooms_by_pool": dict(Counter(room_pool.values())),
             "products_by_pool": dict(Counter(product_pool.values())),
             "annotator_disagreement": disagreement}
    return {"splits": splits, "ties": ties, "pools": pools, "stats": stats}


def check_disjoint(splits: dict) -> None:
    """Raise if any room or product identity appears in more than one split."""
    for field, keys in (("room", ("room_ids",)), ("product", ("a_ids", "b_ids"))):
        seen: dict[str, str] = {}
        for pool, payload in splits.items():
            for key in keys:
                for identity in payload[key]:
                    if seen.setdefault(identity, pool) != pool:
                        raise AssertionError(f"{field} {identity} in both {seen[identity]} and {pool}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--labels", default=str(LABELS_PATH))
    parser.add_argument("--artifacts", default=str(ARTIFACTS_DIR))
    parser.add_argument("--rooms", default=str(ROOMS_DIR))
    parser.add_argument("--out", default=str(DATA_DIR))
    parser.add_argument("--manifest", default=str(SPLIT_MANIFEST_PATH))
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    from dataset import load_rooms
    from embed import load_catalog_embeddings, load_room_embeddings
    catalog = load_catalog_embeddings(Path(args.artifacts))
    if not catalog:
        print("No catalog embeddings. Run `embed.py catalog` first.", file=sys.stderr)
        return 1
    model_id = catalog["model_id"]
    product_emb = {p: torch.nn.functional.normalize(e.float(), dim=0)
                   for p, e in zip(catalog["product_ids"], catalog["embeddings"])}
    product_cat = dict(zip(catalog["product_ids"], catalog["categories"]))

    rooms = load_rooms(Path(args.rooms), Path(args.artifacts), model_id)
    by_sha = rooms.by_sha or (load_room_embeddings(Path(args.artifacts)) or {}).get("items", {})
    room_emb = {rid: by_sha[sha].float() for rid, sha in zip(rooms.ids, rooms.shas) if sha in by_sha}
    labels = read_jsonl(Path(args.labels))
    for row in labels:
        if row.get("room_id") and row["room_id"] not in room_emb and row.get("room_sha256") in by_sha:
            room_emb[row["room_id"]] = by_sha[row["room_sha256"]].float()
    if not labels:
        print(f"No labels in {args.labels}. Collect some with label/server.py first.", file=sys.stderr)
        return 1

    manifest = load_manifest(Path(args.manifest))
    result = build(labels, room_emb, product_emb, product_cat, manifest, args.seed)
    check_disjoint(result["splits"])

    out = Path(args.out)
    for pool, payload in result["splits"].items():
        payload["model_id"] = model_id
        atomic_write_bytes(out / f"{pool}.pt", lambda h, p=payload: torch.save(p, h))
    atomic_write_bytes(out / "ties.jsonl", lambda h: h.write("".join(json.dumps(r) + "\n" for r in result["ties"]).encode()))
    pools = result["pools"]
    manifest.update({"rooms": pools["rooms"], "products": pools["products"],
                     "near_duplicate_groups": {"rooms": pools["room_groups"], "products": pools["product_groups"]},
                     "pool_conflicts": pools["conflicts"], "duplicate_cosine_threshold": DUPLICATE_COSINE,
                     "model_id": model_id, "built_at": utc_now(), "build_stats": result["stats"]})
    atomic_write_json(Path(args.manifest), manifest)

    print(json.dumps(result["stats"], indent=2))
    s = result["stats"]
    print(f"\nDropped {s['dropped_crossing_pools']} pair(s) whose room/products crossed pools; "
          f"{s['tie_rows']} tie row(s) -> ties.jsonl; examples train/val/test = "
          f"{s['examples']['train']}/{s['examples']['validation']}/{s['examples']['test']}")
    d = s["annotator_disagreement"]
    print(f"Annotator disagreement: {d['pairs_with_conflicting_answers']} of {d['pairs_with_multiple_annotators']} "
          f"multiply-judged pairs conflict ({d['pairs_with_opposite_winners']} with opposite winners).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
