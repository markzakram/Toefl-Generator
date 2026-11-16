"""Pembaca file .env sederhana, tanpa dependensi tambahan."""

import os

from .blueprint import ROOT

ENV_PATH = ROOT / ".env"


def load_env(path=ENV_PATH):
    """Isi os.environ dari file .env. Variabel yang sudah ada di environment tidak ditimpa,
    dan nilai kosong dilewati. Kembalikan nama variabel yang dimuat (bukan nilainya)."""
    if not path.exists():
        return []
    loaded = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if value and name not in os.environ:
            os.environ[name] = value
            loaded.append(name)
    return loaded
