"""evaluate.py code path on a SYNTHETIC test file. Numbers here are not model quality."""
import json

import torch

import evaluate
from ranker import CompatibilityRanker


def test_evaluate_writes_report_and_withholds_claim_without_evidence(tmp_path):
    gen = torch.Generator().manual_seed(0)
    n, dim = 40, 8
    data = {"room": torch.randn(n, dim, generator=gen), "a": torch.randn(n, dim, generator=gen),
            "b": torch.randn(n, dim, generator=gen), "preference": (torch.rand(n, generator=gen) < 0.5).float(),
            "room_ids": [f"r{i % 5}" for i in range(n)], "model_id": "fake/model"}
    torch.save(data, tmp_path / "test.pt")
    torch.save({"state_dict": CompatibilityRanker(dim, 4).state_dict(), "embedding_dim": dim, "hidden_dim": 4,
                "model_id": "fake/model"}, tmp_path / "ranker.pt")
    report_path = tmp_path / "eval_report.json"
    code = evaluate.main(["--test", str(tmp_path / "test.pt"), "--checkpoint", str(tmp_path / "ranker.pt"),
                          "--report", str(report_path), "--bootstrap", "500"])
    assert code == 0
    report = json.loads(report_path.read_text())
    assert report["pairs"] == n and report["bootstrap"]["unit"] == "room"
    lo, hi = report["difference_ci95"]
    assert lo <= report["difference"] <= hi
    assert ("better than" in report["verdict"]) == (lo > 0)
    assert (tmp_path / "test_evaluations.jsonl").exists()


def test_verdict_requires_ci_to_exclude_zero():
    assert "better" in evaluate.verdict(0.01, 0.2)
    assert "no significant" in evaluate.verdict(-0.01, 0.2)
    assert "WORSE" in evaluate.verdict(-0.2, -0.01)
