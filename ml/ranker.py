"""Trainable compatibility scorer. Requires externally computed, normalized embeddings."""
import torch
from torch import nn

class CompatibilityRanker(nn.Module):
    def __init__(self, embedding_dim=768, hidden_dim=128):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(embedding_dim * 4, hidden_dim), nn.ReLU(), nn.Dropout(.1), nn.Linear(hidden_dim,1))
    def forward(self, room, product):
        room = nn.functional.normalize(room, dim=-1)
        product = nn.functional.normalize(product, dim=-1)
        features = torch.cat([room,product,torch.abs(room-product),room*product],dim=-1)
        return self.net(features).squeeze(-1)
