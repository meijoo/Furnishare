"""One-shot held-out test evaluation of the learned ranker vs. the cosine baseline.

    ml/.venv/bin/python ml/evaluate.py [--test data/test.pt] [--checkpoint artifacts/ranker.pt]

Prints pair count, learned pairwise accuracy, cosine baseline accuracy, and a bootstrap 95% CI
for (learned - cosine). The bootstrap resamples ROOMS (clusters) when room ids are available,
since pairs sharing a room are not independent. Writes artifacts/eval_report.json and appends to
test_evaluations.jsonl next to the report; warns if the test set was already used for another checkpoint.
The learned model is called better only if the CI excludes zero.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import torch
from torch import nn

from common import ARTIFACTS_DIR, DATA_DIR, SPLIT_MANIFEST_PATH, atomic_write_json, read_jsonl, utc_now
from ranker import CompatibilityRanker
from train import load, pair_logits


def bootstrap_diff(learned_correct: torch.Tensor, cosine_correct: torch.Tensor, clusters: list | None,
                   n_boot: int = 5000, seed: int = 0) -> tuple[float, float]:
    gen = torch.Generator().manual_seed(seed)
    diff = (learned_correct.float() - cosine_correct.float())
    if clusters:
        ids = sorted(set(clusters))
        index = {c: i for i, c in enumerate(ids)}
        cid = torch.tensor([index[c] for c in clusters])
        sums = torch.zeros(len(ids)).index_add_(0, cid, diff)
        counts = torch.zeros(len(ids)).index_add_(0, cid, torch.ones_like(diff))
        draws = torch.randint(len(ids), (n_boot, len(ids)), generator=gen)
        stats = sums[draws].sum(1) / counts[draws].sum(1)
    else:
        draws = torch.randint(len(diff), (n_boot, len(diff)), generator=gen)
        stats = diff[draws].mean(1)
    lo, hi = torch.quantile(stats, torch.tensor([0.025, 0.975])).tolist()
    return lo, hi


def verdict(lo: float, hi: float) -> str:
    if lo > 0:
        return "learned ranker better than cosine baseline (95% CI excludes zero)"
    if hi < 0:
        return "learned ranker WORSE than cosine baseline (95% CI excludes zero)"
    return "no significant difference from cosine baseline (95% CI includes zero)"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--test", default=str(DATA_DIR / "test.pt"))
    parser.add_argument("--checkpoint", default=str(ARTIFACTS_DIR / "ranker.pt"))
    parser.add_argument("--report", default=str(ARTIFACTS_DIR / "eval_report.json"))
    parser.add_argument("--bootstrap", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    test_path, ckpt_path = Path(args.test), Path(args.checkpoint)
    try:
        data = load(test_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Cannot evaluate: {exc}", file=sys.stderr)
        return 1
    if not ckpt_path.exists():
        print(f"No checkpoint at {ckpt_path}; run train.py first.", file=sys.stderr)
        return 1
    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=True)
    if ckpt.get("model_id") != data.get("model_id"):
        print(f"model_id mismatch: checkpoint {ckpt.get('model_id')} vs test {data.get('model_id')}", file=sys.stderr)
        return 1
    if int(ckpt["embedding_dim"]) != data["room"].shape[1]:
        print("embedding_dim mismatch between checkpoint and test data", file=sys.stderr)
        return 1

    ckpt_sha, test_sha = sha256_file(ckpt_path), sha256_file(test_path)
    log_path = Path(args.report).parent / "test_evaluations.jsonl"
    prior = [r for r in read_jsonl(log_path) if r.get("test_sha256") == test_sha and r.get("checkpoint_sha256") != ckpt_sha]
    if prior:
        print(f"WARNING: this test set was already evaluated for {len(prior)} other checkpoint(s). Choosing among "
              "checkpoints by test accuracy makes the test estimate optimistic.", file=sys.stderr)

    model = CompatibilityRanker(int(ckpt["embedding_dim"]), int(ckpt.get("hidden_dim", 128)))
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    with torch.no_grad():
        learned = pair_logits(model, data)
    cosine = nn.functional.cosine_similarity(data["room"], data["a"]) - nn.functional.cosine_similarity(data["room"], data["b"])
    target = data["preference"].bool()
    learned_correct, cosine_correct = (learned > 0) == target, (cosine > 0) == target
    clusters = data.get("room_ids") or None
    lo, hi = bootstrap_diff(learned_correct, cosine_correct, clusters, args.bootstrap, args.seed)
    learned_acc, cosine_acc = learned_correct.float().mean().item(), cosine_correct.float().mean().item()

    disagreement = None
    if SPLIT_MANIFEST_PATH.exists():
        disagreement = json.loads(SPLIT_MANIFEST_PATH.read_text()).get("build_stats", {}).get("annotator_disagreement")

    report = {"evaluated_at": utc_now(), "test_path": str(test_path), "test_sha256": test_sha,
              "checkpoint": str(ckpt_path), "checkpoint_sha256": ckpt_sha, "model_id": ckpt["model_id"],
              "pairs": len(target), "rooms": len(set(clusters)) if clusters else None,
              "learned_accuracy": learned_acc, "cosine_baseline_accuracy": cosine_acc,
              "difference": learned_acc - cosine_acc, "difference_ci95": [lo, hi],
              "bootstrap": {"resamples": args.bootstrap, "unit": "room" if clusters else "pair"},
              "verdict": verdict(lo, hi), "annotator_disagreement": disagreement,
              "validation_at_checkpoint": ckpt.get("validation")}
    atomic_write_json(Path(args.report), report)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as handle:
        handle.write(json.dumps({k: report[k] for k in ("evaluated_at", "test_sha256", "checkpoint_sha256",
                                                         "learned_accuracy", "cosine_baseline_accuracy")}) + "\n")

    print(f"Test pairs:                {report['pairs']}" + (f" across {report['rooms']} rooms" if clusters else ""))
    print(f"Learned pairwise accuracy: {learned_acc:.3f}")
    print(f"Cosine baseline accuracy:  {cosine_acc:.3f}")
    print(f"Difference (learned-cos):  {learned_acc - cosine_acc:+.3f}  95% CI [{lo:+.3f}, {hi:+.3f}] "
          f"({report['bootstrap']['unit']}-level bootstrap)")
    print(f"Verdict: {report['verdict']}")
    if report["pairs"] < 100:
        print("Note: fewer than 100 test pairs; the CI is wide and the comparison is weak evidence either way.")
    print(f"Wrote {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
