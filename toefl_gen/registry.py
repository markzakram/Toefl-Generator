"""Registri pemakaian: fingerprint soal yang sudah dipakai di batch sebelumnya."""

import json

from .blueprint import ROOT

REGISTRY_PATH = ROOT / "data" / "registry.json"


def load_registry(path=REGISTRY_PATH):
    if not path.exists():
        return {"batches": {}}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def blocked_fingerprints(registry, except_batch=None):
    """Fingerprint dari semua batch lain. Batch yang sama dikecualikan agar seed bisa diulang."""
    return frozenset(
        fp
        for batch_id, batch in registry["batches"].items()
        if batch_id != except_batch
        for fp in batch["fingerprints"]
    )


def register_batch(registry, batch_id, meta, items):
    registry["batches"][batch_id] = {**meta, "fingerprints": sorted({it.fingerprint for it in items})}


def save_registry(registry, path=REGISTRY_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=1)
