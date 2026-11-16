"""Fungsi bersama antarsection, terutama yang dibuat lewat Claude (Reading dan Listening)."""

import hashlib
import json
import re

from .models import LETTERS


MIN_EXPLANATION_WORDS = 20
MIN_REASON_WORDS = 8
COLON = re.compile(r":(\s|$)")
# Penyebutan huruf opsi di teks buatan Claude, misalnya "Opsi A dan C" atau "B adalah jawaban".
LETTER_REF = re.compile(r"\b(?:[Oo]psi|[Oo]ption|[Pp]ilihan|[Jj]awaban|[Kk]unci|[Hh]uruf|[Jj]udul) "
                        r"[A-D](?:(?:, dan |, | dan | atau )[A-D]\b)*\b|\b[A-D](?= adalah jawaban)")


class GenerationError(Exception):
    pass


def cache_only():
    """Pengganti `get_client` untuk menyusun ulang batch dari cache tanpa memanggil API."""
    raise GenerationError("Ada bagian yang belum ada di cache dan butuh Claude API. Jalankan tanpa --cache-only.")


def cached_generate(path, system, prompt, schema, validate, get_client, log, label, max_attempts=3,
                    error=GenerationError, effort=None):
    """Ambil hasil dari cache bila prompt-nya sama; kalau tidak, minta Claude membuat dan
    validasi hasilnya. Hasil yang gagal validasi diminta ditulis ulang dengan umpan balik.
    Dengan `cache_only`, isi cache dipakai walau prompt sudah berubah."""
    digest = hashlib.sha256((system + prompt).encode("utf-8")).hexdigest()[:16]
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("prompt_hash") == digest or get_client is cache_only:
            return cached["data"]
    feedback = ""
    problems = []
    for attempt in range(1, max_attempts + 1):
        log(f"  {label}: membuat (percobaan {attempt})")
        extra = {"effort": effort} if effort else {}
        data = get_client().generate_json(system, prompt + feedback, schema, **extra)
        problems = validate(data)
        if not problems:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"prompt_hash": digest, "data": data}, ensure_ascii=False, indent=1),
                            encoding="utf-8")
            return data
        log(f"    perlu diperbaiki: {'; '.join(problems)}")
        feedback = ("\n\nHasil sebelumnya belum memenuhi aturan. Tulis ulang seluruhnya, dan perbaiki:\n- "
                    + "\n- ".join(problems))
    raise error(f"{label} gagal setelah {max_attempts} percobaan: {'; '.join(problems)}")


def norm(text):
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().lower()


def words(text):
    return re.findall(r"[a-z']+", norm(text))


def place_key(q, target):
    """Pindahkan opsi benar ke huruf target; opsi lain tetap berurutan. Alasan ikut berpindah, dan huruf
    opsi yang disebut di penjelasan atau alasan disesuaikan. Kembalikan (opsi, alasan, penjelasan)."""
    correct = q["options"][q["key"]]
    others = [(L, q["options"][L]) for L in LETTERS if L != q["key"]]
    k = LETTERS.index(target)
    ordered = others[:k] + [(q["key"], correct)] + others[k:]
    moved = {old: LETTERS[i] for i, (old, _) in enumerate(ordered)}

    def relabel(text):
        return LETTER_REF.sub(lambda m: re.sub(r"\b[A-D]\b", lambda ref: moved[ref.group()], m.group()), text)

    options = [text for _, text in ordered]
    reasons = {LETTERS[i]: relabel(q["alasan_salah"][old]) for i, (old, _) in enumerate(ordered) if old != q["key"]}
    return options, reasons, relabel(q["penjelasan"])


def reason_clause(text):
    """Rapikan alasan model menjadi klausa yang bisa disambung setelah 'keliru karena'."""
    text = re.sub(r"^(opsi [A-D]\s*)?((salah|keliru)\s*)?(karena\s*)?", "", text.strip(), flags=re.I).rstrip(". ")
    return text[:1].lower() + text[1:] if text else text


def reason_clauses(reasons):
    return {L: reason_clause(text) for L, text in reasons.items()}


def format_pembahasan(key, explanation, reasons, cara_cepat, transcript=()):
    """Susun pembahasan sesuai format tim akademik (docs/standar-toefl-itp.md bagian 6).
    `reasons` berisi klausa alasan untuk setiap huruf selain kunci."""
    lines = [f"Jawaban: {key}", "Pembahasan:", ""]
    if transcript:
        lines += ["Transkrip Audio:", *transcript, ""]
    lines += [explanation.strip(), ""]
    lines += [f"* Opsi {L} keliru karena {reasons[L].rstrip('. ')}." for L in LETTERS if L != key]
    lines += ["", "Cara cepat:", cara_cepat.strip()]
    return "\n".join(lines)


def option_problems(q):
    """Masalah umum pada empat opsi, penjelasan, dan alasan salahnya."""
    problems = []
    texts = [q["options"][L].strip() for L in LETTERS]
    if not all(texts) or len({t.lower() for t in texts}) != 4:
        problems.append("opsi kosong atau tidak unik")
    if any(not q["alasan_salah"][L].strip() or q["alasan_salah"][L].strip() == "-" for L in LETTERS if L != q["key"]):
        problems.append("alasan untuk opsi salah belum lengkap")
    elif any(len(reason_clause(q["alasan_salah"][L]).split()) < MIN_REASON_WORDS for L in LETTERS if L != q["key"]):
        problems.append(f"alasan opsi salah terlalu singkat (minimal {MIN_REASON_WORDS} kata); jelaskan letak kelirunya")
    if len(q["penjelasan"].split()) < MIN_EXPLANATION_WORDS:
        problems.append(f"penjelasan terlalu singkat (minimal {MIN_EXPLANATION_WORDS} kata)")
    if COLON.search(q["penjelasan"]):
        problems.append("penjelasan memakai titik dua; tulis sebagai kalimat mengalir")
    if any(LETTER_REF.search(text) for text in [q["penjelasan"], *q["alasan_salah"].values()]):
        problems.append("penjelasan atau alasan menyebut huruf opsi; sebut isinya, karena urutan opsi akan diubah")
    return problems


def key_is_longest(q):
    others = [len(q["options"][L].strip()) for L in LETTERS if L != q["key"]]
    return len(q["options"][q["key"]].strip()) > max(others)


def length_problems(questions):
    """Peserta bisa menebak kunci kalau opsi benar terlalu sering paling panjang. Kalau acak, sekitar 25%."""
    limit = max(2, round(len(questions) * 0.4))
    n = sum(key_is_longest(q) for q in questions)
    if n <= limit:
        return []
    return [f"opsi benar paling panjang di {n} dari {len(questions)} soal (batas {limit}); "
            "samakan panjang opsi dengan memperpanjang pengecoh atau mempersingkat opsi benar"]


def evidence_found(evidence, full_text):
    parts = [p.strip(" .") for p in re.split(r"\.\.\.|…", evidence) if p.strip(" .")]
    return bool(parts) and all(norm(p) in norm(full_text) for p in parts)


def used_topics(blocked, prefix):
    return {fp.split("#")[0][len(prefix):] for fp in blocked if fp.startswith(prefix)}
