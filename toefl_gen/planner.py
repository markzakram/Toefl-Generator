"""Perencana batch: dari seed menjadi beberapa paket setara.

Semua paket dalam satu batch memakai susunan famili dan level yang sama
(paket setara). Isi tiap slot diambil dari frame yang berbeda, dan tidak ada
fingerprint yang terpakai dua kali, baik di batch ini maupun di registri.
"""

import random
from collections import Counter

from .blueprint import LEVELS, level_counts
from .keys import KeyBalanceError, assign, split_quota

STRUCTURE_PARTS = ("structure", "written_expression")


class PlanError(Exception):
    pass


def plan_structure_section(library, bp, seed, paket, blocked=frozenset()):
    """Kembalikan daftar paket; tiap paket berisi 40 Item Structure & WE bernomor."""
    rng = random.Random(f"{seed}:structure:plan")
    parts = bp["sections"]["structure"]["parts"]
    topic_count = Counter()
    capacity = _capacity(library, blocked, paket)

    templates = {}
    for fmt in STRUCTURE_PARTS:
        counts = level_counts(parts[fmt]["items"], bp["level_mix"])
        templates[fmt] = _slot_template(library, fmt, counts, paket, rng, topic_count, bp["max_per_topic"], capacity)

    picks = {fmt: _allocate(library, fmt, templates[fmt], paket, rng, blocked) for fmt in STRUCTURE_PARTS}

    batch = []
    for p in range(paket):
        order = []
        for fmt in STRUCTURE_PARTS:
            slots = list(picks[fmt][p])
            # Urut dari Mudah ke Sulit, acak di dalam level yang sama.
            rng.shuffle(slots)
            slots.sort(key=lambda s: LEVELS.index(s[0].level))
            order += [(fmt, fr, values) for fr, values in slots]
        quotas = split_quota({fmt: parts[fmt]["items"] for fmt in STRUCTURE_PARTS}, rng)
        try:
            keys = assign([o[0] for o in order], [fr.feasible_keys(v) for _, fr, v in order],
                          quotas, bp["key_rules"]["max_run"], rng)
        except KeyBalanceError as e:
            raise PlanError(str(e)) from e
        items = []
        for n, ((fmt, fr, values), key) in enumerate(zip(order, keys), start=1):
            item = fr.build(values, key, random.Random(f"{seed}:{p}:{n}"))
            item.number = n
            items.append(item)
        batch.append(items)
    return batch


def _capacity(library, blocked, paket):
    """Jumlah slot-paket yang bisa diisi tiap (famili, format, level). Satu frame dipakai paling banyak
    sekali per paket, jadi sumbangannya dibatasi jumlah paket."""
    cap = Counter()
    for fam in library.values():
        for fr in fam.frames:
            free = sum(fr.fingerprint(v) not in blocked for v in fr.variants())
            cap[(fam.id, fr.format, fr.level)] += min(free, paket)
    return cap


def _slot_template(library, fmt, counts, paket, rng, topic_count, max_topic, capacity):
    """Susunan (famili, level) satu part; sama untuk semua paket."""
    slots = []
    used = Counter()
    for level in LEVELS:
        for _ in range(counts[level]):
            candidates = []
            for fam in library.values():
                n_frames = len(fam.frames_for(fmt, level))
                k = used[(fam.id, level)]
                if n_frames > k and topic_count[fam.topic] < max_topic and capacity[(fam.id, fmt, level)] >= (k + 1) * paket:
                    candidates.append(fam)
            if not candidates:
                raise PlanError(f"Tidak ada famili yang cukup untuk {fmt} level {level}. Tambah frame atau kurangi jumlah paket.")
            least = min(used[(f.id, "*")] for f in candidates)
            fam = rng.choice([f for f in candidates if used[(f.id, "*")] == least])
            used[(fam.id, level)] += 1
            used[(fam.id, "*")] += 1
            topic_count[fam.topic] += 1
            slots.append((fam.id, level))
    return slots


def _allocate(library, fmt, template, paket, rng, blocked):
    """Pilih (frame, vars) untuk setiap slot di setiap paket."""
    taken = set(blocked)
    frames_in_paket = [set() for _ in range(paket)]
    frame_use = Counter()
    result = [[] for _ in range(paket)]
    for fam_id, level in template:
        for p in range(paket):
            options = [
                (fr, values)
                for fr in library[fam_id].frames_for(fmt, level)
                if fr.key not in frames_in_paket[p]
                for values in fr.variants()
                if fr.fingerprint(values) not in taken
            ]
            if not options:
                raise PlanError(f"Frame {fam_id} {fmt} {level} habis untuk paket {p + 1}.")
            least = min(frame_use[fr.key] for fr, _ in options)
            fr, values = rng.choice([o for o in options if frame_use[o[0].key] == least])
            taken.add(fr.fingerprint(values))
            frames_in_paket[p].add(fr.key)
            frame_use[fr.key] += 1
            result[p].append((fr, values))
    return result
