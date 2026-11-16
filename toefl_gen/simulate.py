"""Simulasi peserta tanpa kunci.

Tiga persona Claude menjawab setiap soal tanpa melihat kunci, pembahasan, level, atau tipe soal:
- awam (0%): hanya melihat opsi, tanpa pertanyaan, teks, atau transkrip. Claude tidak bisa benar-benar
  melupakan bahasa Inggris, jadi yang diuji adalah apakah bentuk opsi saja sudah membocorkan kunci.
  Tebakan acak sekitar 25%.
- menengah (50%): melihat soal lengkap. Kalau ia salah pada soal Mudah, levelnya mungkin terlalu rendah.
- mahir (80%): melihat soal lengkap. Kalau jawabannya beda dari kunci, soalnya mungkin ambigu atau kuncinya salah.
"""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from .common import cached_generate
from .models import LETTERS

PERSONAS = {
    "awam": ("Kamu peserta TOEFL dengan kemampuan bahasa Inggris hampir nol. Kamu tidak memahami tata bahasa, "
             "isi teks, maupun percakapan. Pilih jawaban HANYA dari petunjuk permukaan: panjang opsi, kata yang "
             "sama dengan pertanyaan, opsi yang paling spesifik atau paling berbeda dari yang lain. Jangan memakai "
             "pengetahuan bahasa Inggris atau pengetahuan umum. Kalau tidak ada petunjuk, tebak dan beri keyakinan rendah."),
    "menengah": ("Kamu peserta TOEFL dengan kemampuan sekitar 50%: tahu tata bahasa dasar dan kosakata umum, tetapi "
                 "sering kesulitan dengan struktur yang rumit, idiom, dan kesimpulan tersirat. Jawab seperti peserta "
                 "di tingkat ini, termasuk kesalahan yang wajar. Jangan berpura-pura lebih pintar."),
    "mahir": ("Kamu peserta TOEFL dengan kemampuan sekitar 80%: menguasai tata bahasa, kosakata akademik, dan "
              "strategi membaca serta menyimak. Jawab dengan teliti."),
}
SYSTEM = ("Kamu sedang mengerjakan soal latihan TOEFL ITP sebagai peserta. Untuk setiap soal, pilih satu jawaban "
          "(A-D), beri tingkat keyakinan (rendah, sedang, tinggi), dan satu kalimat alasan dalam bahasa Indonesia.")
CHUNK = 10
# Skor persona hanya-opsi pada tryout 3892 (November 2026), sebagai pembanding. Angkanya tinggi karena Claude
# tetap memahami bahasa Inggris dan isi opsi, jadi yang dinilai adalah selisihnya, bukan jaraknya dari 25%.
AWAM_BASELINE = {"listening": 0.68, "structure": 0.40, "reading": 0.84}
AWAM_MARGIN = 0.10


def _options(it):
    return "\n".join(f"{L}. {o}" for L, o in zip(LETTERS, it.options))


def _question(it):
    if it.section == "reading":
        return it.stem.rsplit("\n\n", 1)[-1]
    if it.section == "listening":
        return it.meta["question"]
    return it.stem


def chunks(section, items):
    """Kelompokkan soal yang berbagi konteks (teks, percakapan) agar konteks hanya dikirim sekali."""
    if section == "reading":
        key = lambda it: it.meta["passage"]
    elif section == "listening":
        key = lambda it: (it.part, it.meta.get("group") or (it.number - 1) // CHUNK)
    else:
        key = lambda it: (it.number - 1) // CHUNK
    groups = {}
    for it in items:
        groups.setdefault(key(it), []).append(it)
    return list(groups.values())


def blind_prompt(section, group, persona):
    """Prompt tanpa kunci, pembahasan, level, atau tipe soal."""
    lines = [f"Peranmu: {PERSONAS[persona]}", ""]
    if section == "reading" and persona != "awam":
        lines += ["Teks bacaan:", group[0].stem.rsplit("\n\n", 1)[0], ""]
    for it in group:
        if persona == "awam":
            lines.append(f"Soal {it.number} (kamu tidak melihat pertanyaan, teks, atau audionya; hanya melihat opsi):")
        elif section == "listening":
            lines.append(f"Soal {it.number}. Yang kamu dengar:\n{it.meta['transcript']}\nNARRATOR: {it.meta['question']}")
        else:
            lines.append(f"Soal {it.number}. {_question(it)}")
        lines += [_options(it), ""]
    lines.append(f"Jawab {len(group)} soal di atas.")
    return "\n".join(lines)


def answer_schema():
    answer = {
        "type": "object",
        "properties": {
            "no": {"type": "integer"},
            "answer": {"type": "string", "enum": list(LETTERS)},
            "confidence": {"type": "string", "enum": ["rendah", "sedang", "tinggi"]},
            "reason": {"type": "string"},
        },
        "required": ["no", "answer", "confidence", "reason"],
        "additionalProperties": False,
    }
    return {"type": "object", "properties": {"answers": {"type": "array", "items": answer}},
            "required": ["answers"], "additionalProperties": False}


def _validate(data, group):
    got = [a["no"] for a in data.get("answers") or []]
    want = [it.number for it in group]
    return [] if sorted(got) == sorted(want) else [f"jawaban untuk soal {want}, diterima {got}"]


def simulate_section(section, batch, cache_dir, get_client, log=print, effort="medium", workers=6):
    """Isi `item.meta['sim']` dengan jawaban ketiga persona untuk setiap soal."""
    schema = answer_schema()
    jobs = [(k, c, group, persona)
            for k, items in enumerate(batch, start=1)
            for c, group in enumerate(chunks(section, items), start=1)
            for persona in PERSONAS]

    def run(job):
        k, c, group, persona = job
        data = cached_generate(
            cache_dir / f"{section}_P{k}_{c:02d}_{persona}.json", SYSTEM,
            blind_prompt(section, group, persona), schema, lambda d: _validate(d, group),
            get_client, log, f"Simulasi {section} paket {k} kelompok {c} ({persona})", effort=effort,
        )
        return group, persona, {a["no"]: a for a in data["answers"]}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for group, persona, by_no in pool.map(run, jobs):
            for it in group:
                it.meta.setdefault("sim", {})[persona] = by_no[it.number]


def flags_for(it):
    sim = it.meta.get("sim")
    if not sim:
        return []
    flags = []
    mahir, menengah, awam = sim["mahir"], sim["menengah"], sim["awam"]
    if mahir["answer"] != it.key:
        flags.append(f"peserta 80% memilih {mahir['answer']} (kunci {it.key}): periksa kunci atau ambiguitas. "
                     f"Alasannya: {mahir['reason']}")
    if awam["answer"] == it.key and awam["confidence"] == "tinggi":
        flags.append(f"peserta 0% menebak kunci dengan yakin: kunci mungkin terlihat dari opsi. Alasannya: {awam['reason']}")
    if it.level == "Mudah" and menengah["answer"] != it.key:
        flags.append("peserta 50% salah pada soal Mudah: level mungkin terlalu rendah")
    if it.level == "Sulit" and all(sim[p]["answer"] == it.key for p in PERSONAS):
        flags.append("semua persona benar pada soal Sulit: pengecoh mungkin terlalu lemah")
    return flags


def summarize(section, batch):
    """Tandai soal dan kembalikan daftar (level, pesan) untuk laporan QC."""
    issues = []
    for k, items in enumerate(batch, start=1):
        simulated = [it for it in items if it.meta.get("sim")]
        if not simulated:
            continue
        correct = Counter()
        for it in simulated:
            it.meta["flags"] = flags_for(it)
            for persona in PERSONAS:
                correct[persona] += it.meta["sim"][persona]["answer"] == it.key
            for flag in it.meta["flags"]:
                issues.append(("WARN", f"Paket {k} {section} no {it.number}: {flag}"))
        n = len(simulated)
        share = {p: correct[p] / n for p in PERSONAS}
        baseline = AWAM_BASELINE[section]
        issues.append(("INFO", f"Paket {k} {section}: skor simulasi 0% {share['awam']:.0%} (tryout 3892: {baseline:.0%}), "
                               f"50% {share['menengah']:.0%}, 80% {share['mahir']:.0%}"))
        if share["awam"] > baseline + AWAM_MARGIN:
            issues.append(("WARN", f"Paket {k} {section}: persona yang hanya melihat opsi benar {share['awam']:.0%}, "
                                   f"lebih tinggi dari tryout 3892 ({baseline:.0%}); pola kunci mungkin bisa ditebak"))
    return issues
