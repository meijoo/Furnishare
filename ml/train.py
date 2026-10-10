"""Train from human-labeled embedding pairs. No synthetic quality claims.
Input .pt files (from build_pairs.py): room, a, b float tensors [N,D]; preference [N] in {0,1};
1 means A preferred. Optional metadata (room_ids, a_ids, b_ids, categories, model_id) is carried along.
Construct identity-disjoint train/validation/test sets first. Validation selects the checkpoint;
the test set is only touched by evaluate.py.
"""
import argparse
import json
from pathlib import Path

import torch
from torch import nn

from ranker import CompatibilityRanker

TENSOR_KEYS = ('room', 'a', 'b', 'preference')
DEFAULT_OUTPUT = Path(__file__).resolve().parent / 'artifacts' / 'ranker.pt'


def load(path):
    data = torch.load(path, map_location='cpu', weights_only=True)
    for key in TENSOR_KEYS:
        if key not in data: raise ValueError(f'Missing {key}')
    if data['room'].ndim != 2 or len(data['room']) == 0: raise ValueError(f'{path}: expected nonempty [N,D] embeddings')
    if not (data['room'].shape == data['a'].shape == data['b'].shape): raise ValueError('Embedding shapes must match')
    if data['preference'].shape != (len(data['room']),): raise ValueError('One label required per pair')
    if not all(torch.isfinite(data[k]).all() for k in TENSOR_KEYS): raise ValueError('Nonfinite data')
    if not ((data['preference'] == 0) | (data['preference'] == 1)).all(): raise ValueError('Labels must be 0 or 1')
    out = dict(data)
    out.update({k: data[k].float() for k in TENSOR_KEYS})
    return out


def pair_logits(model, data):
    return model(data['room'], data['a']) - model(data['room'], data['b'])


def evaluate(model, data):
    model.eval()
    with torch.no_grad():
        score = pair_logits(model, data)
        baseline = nn.functional.cosine_similarity(data['room'], data['a']) - nn.functional.cosine_similarity(data['room'], data['b'])
        loss = nn.functional.binary_cross_entropy_with_logits(score, data['preference']).item()
        accuracy = lambda s: ((s > 0) == data['preference'].bool()).float().mean().item()
        return {'pairwise_accuracy': accuracy(score), 'cosine_baseline_accuracy': accuracy(baseline),
                'loss': loss, 'pairs': len(score)}


def train(train_data, val_data, epochs=30, hidden_dim=128, lr=1e-3, weight_decay=1e-2, batch_size=32, seed=42, log=print):
    torch.manual_seed(seed)
    model = CompatibilityRanker(train_data['room'].shape[1], hidden_dim)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    best, best_state, history = None, None, []
    for epoch in range(epochs):
        model.train()
        for indices in torch.randperm(len(train_data['room'])).split(batch_size):
            batch = {k: train_data[k][indices] for k in TENSOR_KEYS}
            loss = nn.functional.binary_cross_entropy_with_logits(pair_logits(model, batch), batch['preference'])
            optimizer.zero_grad(); loss.backward(); optimizer.step()
        metrics = {'epoch': epoch + 1, 'train': evaluate(model, train_data), 'validation': evaluate(model, val_data)}
        history.append(metrics)
        log(json.dumps(metrics))
        key = (metrics['validation']['pairwise_accuracy'], -metrics['validation']['loss'])
        if best is None or key > best[0]:
            best = (key, metrics)
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    return model, best[1], history


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--train', required=True); parser.add_argument('--validation', required=True)
    parser.add_argument('--output', default=str(DEFAULT_OUTPUT)); parser.add_argument('--epochs', type=int, default=30)
    parser.add_argument('--hidden-dim', type=int, default=128); parser.add_argument('--lr', type=float, default=1e-3)
    parser.add_argument('--weight-decay', type=float, default=1e-2); parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    train_data, val_data = load(args.train), load(args.validation)
    model_id = train_data.get('model_id')
    if model_id is None: raise ValueError('train data lacks model_id; rebuild with build_pairs.py')
    if val_data.get('model_id') != model_id: raise ValueError('train/validation embedding model_id mismatch')
    model, best, _ = train(train_data, val_data, args.epochs, args.hidden_dim, args.lr, args.weight_decay, seed=args.seed)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    torch.save({'state_dict': model.state_dict(), 'embedding_dim': int(train_data['room'].shape[1]),
                'hidden_dim': args.hidden_dim, 'model_id': model_id, 'validation': best['validation'],
                'epoch': best['epoch'], 'train_pairs': len(train_data['room'])}, args.output)
    print(f"Saved {args.output} (epoch {best['epoch']}, validation {json.dumps(best['validation'])})")
    print('Validation numbers chose this checkpoint and are optimistic; use evaluate.py on test for the real estimate.')


if __name__ == '__main__': main()
