"""Code smoke tests. The toy data here is SYNTHETIC and says nothing about model quality."""
import torch

from ranker import CompatibilityRanker
from train import train


def test_forward_shapes():
    model = CompatibilityRanker(embedding_dim=16, hidden_dim=8)
    out = model(torch.randn(5, 16), torch.randn(5, 16))
    assert out.shape == (5,)
    assert torch.isfinite(out).all()


def test_forward_is_scale_invariant():
    model = CompatibilityRanker(embedding_dim=16, hidden_dim=8).eval()
    room, product = torch.randn(3, 16), torch.randn(3, 16)
    assert torch.allclose(model(room, product), model(room * 4, product * 0.5), atol=1e-5)


def _synthetic_separable(n, dim, seed):
    """SYNTHETIC toy set: the preferred product is a noisy copy of the room vector."""
    gen = torch.Generator().manual_seed(seed)
    room = torch.randn(n, dim, generator=gen)
    near = room + 0.3 * torch.randn(n, dim, generator=gen)
    far = torch.randn(n, dim, generator=gen)
    swap = torch.rand(n, generator=gen) < 0.5
    a = torch.where(swap[:, None], far, near)
    b = torch.where(swap[:, None], near, far)
    return {"room": room, "a": a, "b": b, "preference": (~swap).float()}


def test_pairwise_loss_decreases_on_synthetic_toy_set():
    data_train = _synthetic_separable(256, 16, seed=0)
    data_val = _synthetic_separable(64, 16, seed=1)
    _, best, history = train(data_train, data_val, epochs=15, hidden_dim=16, log=lambda _: None)
    losses = [h["train"]["loss"] for h in history]
    assert losses[-1] < losses[0] * 0.7, losses
    assert best["validation"]["pairwise_accuracy"] > 0.8
