"""QC otomatis berbasis aturan untuk satu paket dan satu batch."""

import re
from collections import Counter

from .blueprint import LEVELS, key_bounds, level_counts
from .models import LETTERS

ERROR, WARN = "ERROR", "WARN"


def max_run(keys):
    best = run = 0
    prev = None
    for k in keys:
        run = run + 1 if k == prev else 1
        prev = k
        best = max(best, run)
    return best


def check_item(it):
    issues = []
    where = f"no {it.number}"
    if it.key not in LETTERS:
        issues.append((ERROR, f"{where}: kunci '{it.key}' tidak valid"))
    if len(it.options) != 4 or len({o.strip().lower() for o in it.options}) != 4:
        issues.append((ERROR, f"{where}: opsi tidak berjumlah 4 atau tidak unik"))
    if not it.pembahasan.startswith(f"Jawaban: {it.key}\nPembahasan:\n\n"):
        issues.append((ERROR, f"{where}: pembahasan tidak menyebut kunci {it.key}"))
    missing = [L for L in LETTERS if L != it.key and f"\n* Opsi {L} keliru karena " not in it.pembahasan]
    if missing:
        issues.append((ERROR, f"{where}: pembahasan belum menjelaskan opsi {', '.join(missing)}"))
    if not re.search(r"\n\nCara cepat:\n\S", it.pembahasan):
        issues.append((ERROR, f"{where}: pembahasan belum memuat Cara cepat"))
    if re.search(r"^(Tipe soal|Rumus|Bukti):", it.pembahasan, re.M):
        issues.append((ERROR, f"{where}: pembahasan masih memakai label lama"))
    if it.part == "structure" and it.stem.count("___") != 1:
        issues.append((ERROR, f"{where}: soal Structure harus punya tepat satu rumpang"))
    if it.part == "written_expression" and re.findall(r"\(([A-D])\)", it.stem) != list(LETTERS):
        issues.append((ERROR, f"{where}: penanda (A)-(D) Written Expression tidak lengkap"))
    return issues


def check_structure_paket(items, bp):
    issues = []
    parts = bp["sections"]["structure"]["parts"]
    if [it.number for it in items] != list(range(1, len(items) + 1)):
        issues.append((ERROR, "nomor soal tidak berurutan"))
    for fmt, spec in parts.items():
        sub = [it for it in items if it.part == fmt]
        if len(sub) != spec["items"]:
            issues.append((ERROR, f"{fmt}: {len(sub)} soal, seharusnya {spec['items']}"))
            continue
        if sub[0].number != spec["first"]:
            issues.append((ERROR, f"{fmt}: mulai di nomor {sub[0].number}, seharusnya {spec['first']}"))
        want = level_counts(spec["items"], bp["level_mix"])
        got = Counter(it.level for it in sub)
        if any(got[lvl] != want[lvl] for lvl in LEVELS):
            issues.append((ERROR, f"{fmt}: level {dict(got)}, seharusnya {want}"))

    issues += _key_checks(items, bp)

    for topic, n in Counter(it.topic for it in items).items():
        if n > bp["max_per_topic"]:
            issues.append((ERROR, f"topik '{topic}' muncul {n} kali (batas {bp['max_per_topic']})"))
    for frame, n in Counter(it.frame_id for it in items).items():
        if n > 1:
            issues.append((ERROR, f"frame {frame} dipakai {n} kali dalam satu paket"))

    longest = _longest_share([it for it in items if it.part == "structure"])
    n_struct = sum(it.part == "structure" for it in items)
    if n_struct and longest / n_struct > 0.35:
        issues.append((WARN, f"opsi benar paling panjang di {longest} dari {n_struct} soal Structure"))

    for it in items:
        issues += check_item(it)
    return issues


def _key_checks(items, bp):
    issues = []
    keys = [it.key for it in items]
    lo, hi = key_bounds(len(items), bp["key_rules"])
    counts = Counter(keys)
    for L in LETTERS:
        if not lo <= counts[L] <= hi:
            issues.append((ERROR, f"kunci {L} muncul {counts[L]} kali (batas {lo}-{hi})"))
    if max_run(keys) > bp["key_rules"]["max_run"]:
        issues.append((ERROR, f"kunci sama berturut-turut {max_run(keys)} kali"))
    return issues


def _longest_share(items):
    return sum(len(it.options[LETTERS.index(it.key)]) > max(len(o) for i, o in enumerate(it.options) if LETTERS[i] != it.key)
               for it in items)


def check_reading_paket(items, bp):
    spec = bp["sections"]["reading"]
    total = spec["parts"]["reading"]["items"]
    issues = []
    if len(items) != total:
        issues.append((ERROR, f"{len(items)} soal, seharusnya {total}"))
    if [it.number for it in items] != list(range(1, len(items) + 1)):
        issues.append((ERROR, "nomor soal tidak berurutan"))

    per_passage = Counter(it.meta["passage"] for it in items)
    if len(per_passage) != spec["passages"]:
        issues.append((ERROR, f"{len(per_passage)} teks, seharusnya {spec['passages']}"))
    lo, hi = spec["items_per_passage"]
    for p, n in sorted(per_passage.items()):
        if not lo <= n <= hi:
            issues.append((ERROR, f"teks {p} berisi {n} soal (batas {lo}-{hi})"))
    words_lo, words_hi = spec["passage_words"]
    for p in sorted(per_passage):
        words = next(it.meta["words"] for it in items if it.meta["passage"] == p)
        if not words_lo <= words <= words_hi:
            issues.append((ERROR, f"teks {p} berisi {words} kata (batas {words_lo}-{words_hi})"))
    topics = {it.meta["passage"]: it.frame_id for it in items}
    if len(set(topics.values())) != len(topics):
        issues.append((ERROR, "ada topik yang dipakai dua kali dalam satu paket"))

    want = level_counts(total, bp["level_mix"])
    got = Counter(it.level for it in items)
    if any(got[lvl] != want[lvl] for lvl in LEVELS):
        issues.append((ERROR, f"level {dict(got)}, seharusnya {want}"))
    issues += _key_checks(items, bp)
    tone = sum(it.family_id == "tone" for it in items)
    if tone > spec["max_tone_items"]:
        issues.append((ERROR, f"soal tone {tone}, batas {spec['max_tone_items']}"))

    longest = _longest_share(items)
    if items and longest / len(items) > 0.35:
        issues.append((WARN, f"opsi benar paling panjang di {longest} dari {len(items)} soal"))
    for it in items:
        issues += check_item(it)
    return issues


def check_listening_paket(items, bp):
    parts = bp["sections"]["listening"]["parts"]
    issues = []
    if [it.number for it in items] != list(range(1, len(items) + 1)):
        issues.append((ERROR, "nomor soal tidak berurutan"))
    for part, spec in parts.items():
        sub = [it for it in items if it.part == part]
        if len(sub) != spec["items"]:
            issues.append((ERROR, f"Part {part}: {len(sub)} soal, seharusnya {spec['items']}"))
            continue
        if sub[0].number != spec["first"]:
            issues.append((ERROR, f"Part {part}: mulai di nomor {sub[0].number}, seharusnya {spec['first']}"))
        want = level_counts(spec["items"], bp["level_mix"])
        got = Counter(it.level for it in sub)
        if any(got[lvl] != want[lvl] for lvl in LEVELS):
            issues.append((ERROR, f"Part {part}: level {dict(got)}, seharusnya {want}"))
        per_group = spec.get("per_group", 1)
        if per_group > 1:
            groups = Counter(it.meta["group"] for it in sub)
            if len(groups) != spec["items"] // per_group or any(n != per_group for n in groups.values()):
                issues.append((ERROR, f"Part {part}: setiap percakapan/kuliah harus berisi {per_group} soal"))
    issues += _key_checks(items, bp)
    return issues + _listening_item_checks(items)


def check_part_c_set(items, bp, blocked=frozenset()):
    """QC set latihan Part C saja, yang tidak mengikuti susunan 50 soal di blueprint."""
    per_group = bp["sections"]["listening"]["parts"]["C"]["per_group"]
    issues = []
    if [it.number for it in items] != list(range(1, len(items) + 1)):
        issues.append((ERROR, "nomor soal tidak berurutan"))
    if any(it.part != "C" for it in items):
        issues.append((ERROR, "ada soal di luar Part C"))
    groups = Counter(it.meta["group"] for it in items)
    if any(n != per_group for n in groups.values()):
        issues.append((ERROR, f"setiap kuliah harus berisi {per_group} soal"))
    topics = {it.meta["group"]: it.frame_id for it in items}
    if len(set(topics.values())) != len(topics):
        issues.append((ERROR, "ada topik kuliah yang dipakai dua kali"))
    want = level_counts(len(items), bp["level_mix"])
    got = Counter(it.level for it in items)
    if any(got[lvl] != want[lvl] for lvl in LEVELS):
        issues.append((ERROR, f"level {dict(got)}, seharusnya {want}"))
    for fp, n in Counter(it.fingerprint for it in items).items():
        if n > 1:
            issues.append((ERROR, f"soal kembar: {fp}"))
    used = {fp.split("#")[0] for fp in blocked}
    reused = {it.fingerprint.split("#")[0] for it in items} & used
    if reused:
        issues.append((ERROR, f"{len(reused)} topik sudah pernah dipakai di batch sebelumnya"))
    return issues + _key_checks(items, bp) + _listening_item_checks(items)


def _listening_item_checks(items):
    from pathlib import Path

    from .listening import copy_problems

    issues = []
    longest = _longest_share(items)
    if items and longest / len(items) > 0.35:
        issues.append((WARN, f"opsi benar paling panjang di {longest} dari {len(items)} soal"))

    missing_audio = 0
    for it in items:
        issues += check_item(it)
        q = {"options": dict(zip(LETTERS, it.options)), "key": it.key}
        min_words = 3 if it.part == "A" else 5
        issues += [(ERROR, f"no {it.number}: {p}") for p in copy_problems(q, it.meta["transcript_lines"], min_words)]
        path = it.meta.get("audio_path")
        if not path:
            missing_audio += 1
        elif not Path(path).exists() or not Path(path).stat().st_size:
            issues.append((ERROR, f"no {it.number}: file audio {it.meta['audio_file']} tidak ada atau kosong"))
    if missing_audio:
        issues.append((WARN, f"audio belum dibuat untuk {missing_audio} soal"))
    return issues


CHECKERS = {"structure": check_structure_paket, "reading": check_reading_paket, "listening": check_listening_paket}


def _shape(section, items):
    if section == "reading":
        return [(it.meta["passage"], it.family_id, it.level) for it in items]
    if section == "listening":
        return [(it.part, it.family_id, it.level) for it in items]
    return sorted((it.part, it.family_id, it.level) for it in items)


# Kata umum di judul topik yang tidak menandakan kemiripan isi.
GENERIC_WORDS = {
    "history", "origins", "origin", "invention", "development", "beginnings", "early", "first", "their", "about",
    "people", "science", "making", "formation", "effect", "effects", "causes", "ancient", "medieval", "public",
    "changes", "already", "built", "reveal", "using", "global", "modern", "survive", "through", "between",
    "against", "become", "became", "works", "system", "things", "method", "small", "young", "rise", "growth",
}


def _content_words(title):
    return {w for w in re.findall(r"[a-z]+", title.lower()) if len(w) >= 5 and w not in GENERIC_WORDS}


def _topic_overlap(sections):
    """Topik Reading dan kuliah Listening (Part C) dalam paket yang sama tidak boleh mirip."""
    if "reading" not in sections or "listening" not in sections:
        return []
    issues = []
    for p, (reading, listening) in enumerate(zip(sections["reading"], sections["listening"]), start=1):
        r_topics = {it.topic for it in reading}
        l_topics = {it.topic for it in listening if it.part == "C"}
        for r in sorted(r_topics):
            for lt in sorted(l_topics):
                shared = _content_words(r) & _content_words(lt)
                if shared:
                    issues.append((WARN, f"Paket {p}: topik Reading '{r}' mirip dengan Listening '{lt}' "
                                         f"({', '.join(sorted(shared))})"))
    return issues


def check_batch(sections, bp, blocked=frozenset()):
    """`sections` = {nama section: [daftar Item per paket]}. Kembalikan daftar (level, pesan)."""
    issues = []
    for section, batch in sections.items():
        for p, items in enumerate(batch, start=1):
            issues += [(lvl, f"Paket {p} {section}: {msg}") for lvl, msg in CHECKERS[section](items, bp)]
        shapes = [_shape(section, items) for items in batch]
        if any(shape != shapes[0] for shape in shapes):
            issues.append((ERROR, f"{section}: susunan soal dan level tidak sama antarpaket"))

    issues += _topic_overlap(sections)

    all_items = [it for batch in sections.values() for items in batch for it in items]
    fps = Counter(it.fingerprint for it in all_items)
    for fp, n in fps.items():
        if n > 1:
            issues.append((ERROR, f"soal kembar antarpaket: {fp}"))
    # Fingerprint Reading "READ:topik#slot": topik yang sama dianggap sudah dipakai.
    used = {fp.split("#")[0] for fp in blocked}
    reused = {fp.split("#")[0] for fp in fps if fp.split("#")[0] in used}
    if reused:
        issues.append((ERROR, f"{len(reused)} soal/topik sudah pernah dipakai di batch sebelumnya"))
    return issues
