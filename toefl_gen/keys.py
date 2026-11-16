"""Penyeimbang kunci jawaban: sebaran huruf per kelompok soal dan batas kunci sama berturut-turut."""

from .models import LETTERS


class KeyBalanceError(Exception):
    pass


def split_quota(sizes, rng):
    """Kuota tiap huruf untuk setiap kelompok. Huruf yang mendapat lebih di satu kelompok
    mendapat kurang di kelompok berikutnya, jadi total per section tetap seimbang."""
    letters = list(LETTERS)
    rng.shuffle(letters)
    quotas = {}
    for group, n in sizes.items():
        base, extra = divmod(n, 4)
        quotas[group] = {L: base + (i < extra) for i, L in enumerate(letters)}
        letters = letters[extra:] + letters[:extra]
    return quotas


def assign(groups, feasible, quotas, max_run, rng, budget=200_000):
    """Pilih kunci untuk tiap posisi. `groups[i]` adalah kelompok soal ke-i dan
    `feasible[i]` huruf yang bisa dipakai soal itu."""
    remaining = {g: dict(q) for g, q in quotas.items()}
    keys = []
    nodes = [budget]

    def choices(i):
        last = keys[-1] if keys else None
        run = 0
        for k in reversed(keys):
            if k != last:
                break
            run += 1
        options = [L for L in feasible[i] if remaining[groups[i]][L] > 0 and not (L == last and run >= max_run)]
        rng.shuffle(options)
        return options

    def solve(i):
        if i == len(groups):
            return True
        nodes[0] -= 1
        if nodes[0] < 0:
            return False
        for L in choices(i):
            keys.append(L)
            remaining[groups[i]][L] -= 1
            if solve(i + 1):
                return True
            keys.pop()
            remaining[groups[i]][L] += 1
        return False

    if not solve(0):
        raise KeyBalanceError("Kunci jawaban tidak bisa diseimbangkan untuk susunan ini; coba seed lain.")
    return keys
