import math
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
LEVELS = ["Mudah", "Sedang", "Sulit"]

# Jumlah soal per section pada TOEFL ITP.
SECTION_TOTALS = {"listening": 50, "structure": 40, "reading": 50}


def load_blueprint(path=None):
    path = Path(path) if path else ROOT / "config" / "blueprint.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def level_counts(n, mix):
    """Bagi n soal ke tiap level dengan metode sisa terbesar."""
    raw = {lvl: n * mix[lvl] for lvl in LEVELS}
    counts = {lvl: int(raw[lvl]) for lvl in LEVELS}
    rest = n - sum(counts.values())
    order = sorted(LEVELS, key=lambda lvl: (-(raw[lvl] - counts[lvl]), LEVELS.index(lvl)))
    for lvl in order[:rest]:
        counts[lvl] += 1
    return counts


def key_bounds(n, rules):
    """Batas bawah dan atas jumlah satu huruf kunci untuk n soal."""
    return math.ceil(n * rules["min_share"]), math.floor(n * rules["max_share"])


def validate(bp):
    """Kembalikan daftar kesalahan blueprint; kosong berarti valid."""
    errors = []
    if abs(sum(bp["level_mix"].values()) - 1) > 1e-9:
        errors.append("level_mix tidak berjumlah 1")
    if sorted(bp["level_mix"]) != sorted(LEVELS):
        errors.append(f"level_mix harus berisi {LEVELS}")
    for name, total in SECTION_TOTALS.items():
        section = bp["sections"][name]
        expected_first = 1
        count = 0
        for part_name, part in section["parts"].items():
            if part["first"] != expected_first:
                errors.append(f"{name}.{part_name} mulai di {part['first']}, seharusnya {expected_first}")
            per_group = part.get("per_group", 1)
            if part["items"] % per_group:
                errors.append(f"{name}.{part_name}: {part['items']} soal tidak habis dibagi {per_group}")
            expected_first += part["items"]
            count += part["items"]
        if count != total:
            errors.append(f"{name} berisi {count} soal, seharusnya {total}")
    lo, hi = key_bounds(40, bp["key_rules"])
    if lo * 4 > 40 or hi * 4 < 40:
        errors.append("key_rules tidak bisa dipenuhi untuk 40 soal")
    return errors
