"""Loads room/product identities with their embeddings for labeling and pair building."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import torch

from common import ARTIFACTS_DIR, ROOMS_DIR, file_sha256, list_images


@dataclass
class RoomTable:
    ids: list[str] = field(default_factory=list)          # path relative to rooms dir (posix)
    paths: list[Path] = field(default_factory=list)
    shas: list[str] = field(default_factory=list)
    embeddings: torch.Tensor | None = None                # [N,D] or None if any room is unembedded
    by_sha: dict[str, torch.Tensor] = field(default_factory=dict)
    model_id: str | None = None


def load_rooms(rooms_dir: Path = ROOMS_DIR, artifacts_dir: Path = ARTIFACTS_DIR, model_id: str | None = None,
               embed_missing: bool = True) -> RoomTable:
    from embed import load_room_embeddings, main as embed_main
    paths = list_images(rooms_dir)
    table = RoomTable(ids=[p.relative_to(rooms_dir).as_posix() for p in paths], paths=paths,
                      shas=[file_sha256(p) for p in paths])
    data = load_room_embeddings(artifacts_dir) or {}
    if model_id and data.get("model_id") not in (None, model_id):
        data = {}
    missing = [s for s in table.shas if s not in data.get("items", {})]
    if missing and embed_missing:
        print(f"Embedding {len(missing)} room image(s) not yet in room_embeddings.pt ...")
        args = ["--artifacts", str(artifacts_dir)] + (["--model", model_id] if model_id else []) + ["images", str(rooms_dir)]
        if embed_main(args) == 0:
            data = load_room_embeddings(artifacts_dir) or {}
    table.by_sha = dict(data.get("items", {}))
    table.model_id = data.get("model_id")
    if paths and all(s in table.by_sha for s in table.shas):
        table.embeddings = torch.stack([table.by_sha[s] for s in table.shas]).float()
    return table
