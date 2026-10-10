# ml/: visual compatibility ranker

Ranks furniture products by visual compatibility with a room or inspiration image. A frozen SigLIP2
encoder (`google/siglip2-base-patch16-224`, 768-d) embeds images. A small MLP over
`[room, product, |room-product|, room*product]` is trained with a pairwise logistic loss on human
preferences, then compared on identity-disjoint held-out data against plain cosine similarity.
Until a trained model beats cosine on the test set, the service ranks by cosine.

## Setup (separate venv; do not touch the root .venv)

```bash
cd ml
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest          # 25 tests, about 3 s, no model download
```

The first embedding run downloads SigLIP2 (about 375 MB) to `~/.cache/huggingface`. It uses MPS when
available and falls back to CPU. Throughput is about 15 img/s on Apple Silicon (MPS and CPU are similar).

## Workflow

All commands run from `ml/` with `.venv/bin/python`.

1. **Add room photos** to `data/rooms/` and record source/license in `data/rooms/manifest.csv`
   (see `data/rooms/README.md` for Unsplash/Pexels/Commons).
2. **Embed** (incremental; re-run whenever the catalog or rooms change):
   ```bash
   .venv/bin/python embed.py catalog          # -> artifacts/catalog_embeddings.pt
   .venv/bin/python embed.py images data/rooms  # -> artifacts/room_embeddings.pt (keyed by sha256)
   ```
3. **Label**:
   ```bash
   .venv/bin/python label/server.py           # http://127.0.0.1:8200
   ```
   Enter an annotator id, then use `A`/`←` for left, `B`/`→` for right, `T`/`↓` for tie,
   `S`/space to skip, and `U` to mark the judgment "unsure". Pairs are always same-category and
   same-pool, favor close cosine scores (hard pairs, 20% uniform exploration), and never repeat for one
   annotator. About 30% of the time another annotator's pair is re-shown so disagreement can be measured.
   Restart the server (or `POST /api/reload`) after adding rooms or re-embedding.
4. **Build pairs**: `.venv/bin/python build_pairs.py` writes `data/{train,validation,test}.pt`,
   `data/ties.jsonl`, and `data/split_manifest.json`. It reports dropped cross-pool rows and annotator
   disagreement.
5. **Train**: `.venv/bin/python train.py --train data/train.pt --validation data/validation.pt`
   writes `artifacts/ranker.pt`, selected on validation accuracy.
6. **Evaluate once**: `.venv/bin/python evaluate.py` writes `artifacts/eval_report.json`.
7. **Serve**: `.venv/bin/python serve.py` starts the server at `http://127.0.0.1:8100`. Run
   `curl -X POST :8100/reload` after re-embedding or retraining. Only keep `ranker.pt` in
   `artifacts/` if the evaluation verdict says it beats cosine; otherwise delete it and the service
   stays in cosine mode.

## How many labels and rooms?

The test set size is limited by **identities, not labeling effort**. Pairs need a room and two products
from the same pool. With the current catalog (30 products: 12 sofas, 7 coffee tables, 6 rugs, 5 TVs),
each validation or test pool holds 2 products per category, and TVs have only 1. So **each test room
yields at most 3 unique test pairs**, while each train room yields about 35.

| rooms total | test rooms (~15%) | max test pairs | labels to cover it (1 annotator) |
|---|---|---|---|
| 40 | 6 | ~18 | ~1,100 |
| 100 | 15 | ~45 | ~2,800 |
| 300 | 45 | ~135 | ~8,000 |

The labels column assumes every train pair gets labeled. You can stop well short of that on the train
side, since the tool round-robins rooms. Roughly 150+ test pairs are needed to resolve a ~10-point
accuracy gap. Practical plan:
- Collect 100–300 room photos; they are cheap to get from Unsplash/Pexels.
- Grow the catalog: about 15–20 products per category roughly triples test pairs per room.
- Collect at least 1,500–3,000 labels. At ~3 s per judgment, that is 1–3 annotator-hours.
- Have a second annotator label for ~20 minutes so disagreement is measurable.

With fewer test pairs, `evaluate.py` still runs, but its CI will be wide and the verdict will
almost certainly be "no significant difference". That is the honest outcome, and the service should
stay on cosine.

## Backend integration

`infer.py` implements the `RankerService` contract from `docs/API.md` and imports with the stdlib
only. In the backend (root `.venv`, no torch):

```python
import sys; sys.path.insert(0, "<repo>")      # or run from the repo root
from pathlib import Path
from ml.infer import RankerService

ranker = RankerService.load(Path("ml/artifacts"))   # never raises
ranker.mode                                         # "learned" | "cosine" | "neutral"
scores = ranker.score(Path("backend/static/uploads/inspo.jpg"), ["ikea-...", "ikea-..."])
```

Without torch, `RankerService` automatically proxies to the sidecar (`ml/serve.py`). Set
`RAG_RANKER_URL` to override `http://127.0.0.1:8100`. If the sidecar is down, the mode is `neutral`
(all 0.0), and it is re-probed every 10 s, so starting the sidecar later upgrades the mode with no
backend restart. **The backend should call the sidecar this way; start it alongside uvicorn.**

Sidecar HTTP API:
- `GET /health` returns `{mode, reason, model_id, embedding_dim, catalog_size, device}`.
- `POST /score` takes `{"room_image_path": "/abs/path.jpg" | null, "product_ids": [...]}` and returns
  `{mode, scores}`. The path must be readable by the sidecar.
- `POST /reload` re-reads `artifacts/`.

Score semantics:
- Compare scores only within one category for one room image.
- `learned` returns MLP logits, `cosine` returns cosine similarity, and `neutral` returns 0.0.
- Unknown product ids (not in `catalog_embeddings.pt`) are omitted in learned/cosine mode, so use
  `scores.get(pid, default)`.
- A missing or `None` room image returns 0.0 for every requested id.
- Room embeddings are cached by file sha256.

## Files

| file | role |
|---|---|
| `common.py` | paths and helpers (stdlib only) |
| `embed.py` | SigLIP2 embeddings, `embed_image(path)` cache, `catalog` / `images` CLI |
| `infer.py` | `RankerService` (local or sidecar proxy) |
| `serve.py` | HTTP sidecar on :8100 |
| `splits.py` | near-duplicate grouping and persistent identity pools |
| `dataset.py` | room inventory and embeddings |
| `label/` | labeling server and page (:8200) |
| `build_pairs.py` | labels to identity-disjoint `.pt` splits |
| `ranker.py`, `train.py` | MLP and trainer |
| `evaluate.py` | one-shot test evaluation with bootstrap CI |
| `tests/` | smoke tests (synthetic fixtures only; not model quality) |
