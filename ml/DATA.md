# Preference data contract

Frozen image encoder: `google/siglip2-base-patch16-224` (SigLIP2, `get_image_features`, 768-d, L2-normalized).
Every embedding artifact records `model_id`; checkpoints record `model_id` + `embedding_dim`, and
`infer.py` only uses `ranker.pt` when both match the catalog embeddings.

## Images
- Products: `backend/data/catalog_verified.json` + `backend/static/<local_image>` (identity = product `id`).
- Rooms: `ml/data/rooms/` (identity = path relative to that folder; a top-level subfolder = one room
  with several views). Source/permission for every room image goes in `ml/data/rooms/manifest.csv`.

## Labels: `ml/data/labels.jsonl` (one JSON object per line, append-only, written by `label/server.py`)

| field | meaning |
|---|---|
| `room_id` | room identity (path under `data/rooms/`) |
| `room_sha256` | content hash of the room image when labeled |
| `product_a_id`, `product_b_id` | shown left (A) and right (B); same category; A/B order is randomized |
| `furniture_category` | `sofa` / `coffee_table` / `tv` / `rug` |
| `preferred_product` | `product_a_id`, `product_b_id`, or `"tie"` |
| `annotator_id` | who judged |
| `uncertainty` | `"sure"` or `"unsure"` |
| `timestamp` | ISO 8601 UTC |
| `pool` | room's split pool at labeling time (audit only; build_pairs recomputes) |

Skips go to `ml/data/skips.jsonl` (same fields minus preference) so the annotator isn't shown the pair again.

## Splits
`splits.py` assigns whole identities (rooms and products, separately) to train/validation/test
BEFORE examples are built. Near-duplicates (cosine > 0.97) and views in one room subfolder share a
pool. Product assignment is stratified by category, with at least 2 products per pool when a category
has 6 or more. Assignments persist in `ml/data/split_manifest.json` and never move once made. The
labeling tool only shows room + products from the same pool, so in practice no labels are lost;
`build_pairs.py` still drops (and counts) any row whose room or either product crosses pools.

## Training files: `ml/data/{train,validation,test}.pt` (written by `build_pairs.py`)
- `room`, `a`, `b`: float tensors [N,D] (normalized embeddings)
- `preference`: float [N], 1 if A preferred, 0 if B
- `room_ids`, `a_ids`, `b_ids`, `categories`: lists of str (audit, room-clustered bootstrap)
- `model_id`, `embedding_dim`

Repeated judgments of the same (room, unordered pair) are majority-voted into one example; exact
splits are dropped. Ties go to `ml/data/ties.jsonl` and are excluded from the binary model.

## Evaluation rules
Validation picks the checkpoint. Evaluate once on test (`evaluate.py`): it reports pair count,
learned accuracy, cosine-baseline accuracy, a room-clustered bootstrap 95% CI for the difference, and
annotator disagreement. "Better than baseline" is only stated when the CI excludes zero. No training
data is bundled. Synthetic tensors exist only in `tests/` as code smoke tests.
