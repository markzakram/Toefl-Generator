"""Section Reading: rencana per paket, pembuatan teks lewat Claude, validasi, dan konversi ke Item."""

import json
import random
import re

import yaml

from .blueprint import ROOT, level_counts
from .common import (GenerationError, cached_generate, evidence_found, format_pembahasan, length_problems, norm,
                     option_problems, place_key, reason_clauses, used_topics)
from .keys import KeyBalanceError, assign, split_quota
from .models import LETTERS, Item

TYPES_PATH = ROOT / "data" / "reading" / "question_types.yaml"
TOPICS_PATH = ROOT / "data" / "reading" / "topics.yaml"
REFERENCE_PATH = ROOT / "data" / "reference" / "reading_3892.json"
PARAGRAPHS = (3, 5)
LAST_TYPES = ("organization", "tone")
QUOTED = re.compile(r"[\"“”]([^\"“”]+)[\"“”]")


class ReadingError(GenerationError):
    pass


def load_types(path=TYPES_PATH):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["types"]


def load_topics(path=TOPICS_PATH):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["fields"]


# ---------- Rencana ----------

def plan_reading(bp, seed, paket, blocked=frozenset(), types=None, topics=None):
    """Rencana tiap paket: daftar teks berisi bidang, topik, dan slot soal (tipe, level, kunci)."""
    types = types or load_types()
    topics = topics or load_topics()
    spec = bp["sections"]["reading"]
    total = spec["parts"]["reading"]["items"]
    n_pass = spec["passages"]
    if sum(t["per_paket"] for t in types) != total:
        raise ReadingError(f"Jumlah per_paket di question_types.yaml harus {total}.")
    rng = random.Random(f"{seed}:reading:plan")

    # Susunan tipe soal per teks, sama untuk semua paket.
    passages = [[] for _ in range(n_pass)]
    order = list(range(n_pass))
    rng.shuffle(order)
    tokens = [t["id"] for t in types for _ in range(t["per_paket"])]
    for i, tid in enumerate(tokens):
        passages[order[i % n_pass]].append(tid)
    for slots in passages:
        middle = [t for t in slots if t != "main_idea" and t not in LAST_TYPES]
        rng.shuffle(middle)
        slots[:] = [t for t in slots if t == "main_idea"] + middle + [t for t in slots if t in LAST_TYPES]

    # Level dibagi menurut tingkat kesulitan tipe soal.
    hardness = {t["id"]: t["hardness"] for t in types}
    positions = [(p, s) for p in range(n_pass) for s in range(len(passages[p]))]
    ranked = sorted(positions, key=lambda ps: hardness[passages[ps[0]][ps[1]]] + rng.random() * 0.6, reverse=True)
    counts = level_counts(total, bp["level_mix"])
    levels = {}
    for i, ps in enumerate(ranked):
        levels[ps] = "Sulit" if i < counts["Sulit"] else "Mudah" if i >= total - counts["Mudah"] else "Sedang"

    # Bidang sama untuk semua paket; topik berbeda per paket dan belum pernah dipakai.
    fields = rng.sample(sorted(topics), n_pass)
    taken = used_topics(blocked, "READ:")
    chosen = {}
    for p, field in enumerate(fields):
        free = [t for t in topics[field] if t["id"] not in taken]
        if len(free) < paket:
            raise ReadingError(f"Topik bidang '{field}' tinggal {len(free)}, butuh {paket}. Tambah topik di topics.yaml.")
        chosen[p] = rng.sample(free, paket)

    plan = []
    for k in range(paket):
        quotas = split_quota({"reading": total}, rng)
        try:
            keys = assign(["reading"] * total, [list(LETTERS)] * total, quotas, bp["key_rules"]["max_run"], rng)
        except KeyBalanceError as e:
            raise ReadingError(str(e)) from e
        it = iter(keys)
        plan.append([
            {
                "index": p + 1,
                "field": fields[p],
                "topic": chosen[p][k],
                "slots": [{"slot": s + 1, "type": t, "level": levels[(p, s)], "key": next(it)}
                          for s, t in enumerate(passages[p])],
            }
            for p in range(n_pass)
        ])
    return plan


# ---------- Prompt ----------

def build_system(types, reference):
    type_lines = "\n".join(
        f"- {t['id']} ({t['name']}): {t['rules']} Contoh bentuk pertanyaan: {' | '.join(t['stems'])}" for t in types
    )
    example = "\n\n".join(f"{q['question']}\nKunci: {q['key']}" for q in reference["questions"])
    return f"""Kamu penulis soal TOEFL ITP untuk TOEFL Academy (Indonesia). Tugasmu menulis satu teks Reading akademik orisinal beserta soal-soalnya, persis sesuai rencana yang diberikan.

ATURAN TEKS
- Bahasa Inggris Amerika, gaya buku teks perguruan tinggi pengantar, netral dan informatif.
- Orisinal. Jangan menyalin atau memparafrasekan dekat teks dari buku persiapan TOEFL, ETS, atau sumber lain.
- Fakta harus umum dan mapan. Hindari angka, tanggal, atau nama yang tidak pasti; lebih baik dijelaskan secara umum.
- Hindari topik sensitif (politik praktis, agama, kekerasan, isu SARA).

ATURAN SOAL
- Setiap soal punya empat opsi (A-D) dan tepat satu jawaban benar menurut teks.
- Opsi sejajar bentuk, panjang, dan tingkat kerinciannya. Dalam satu teks, opsi benar boleh menjadi yang terpanjang paling banyak 3 dari 10 soal; sering-seringlah membuat opsi benar lebih pendek daripada pengecoh. Opsi benar tidak memakai pola "X or Y".
- Peserta yang hanya melihat opsi, tanpa membaca teks, tidak boleh bisa menebak jawabannya. Semua opsi harus sama masuk akalnya bagi orang yang belum membaca teks.
- Kata mutlak (only, every, always, never) dan kata pelunak (may, probably, often) harus muncul merata di opsi benar dan pengecoh. Opsi benar tidak boleh selalu yang paling umum atau paling netral.
- Pengecoh harus jelas salah menurut teks, tetapi tetap masuk akal bagi pembaca yang kurang teliti.
- Antarsoal dalam satu teks: opsi benar tidak boleh menjadi satu-satunya yang saling menguatkan. Istilah dan gagasan yang berulang di opsi benar juga harus muncul di pengecoh soal lain, dan pengecoh dari beberapa soal harus bisa membentuk gambaran yang sama masuk akalnya. Orang yang hanya melihat semua opsi satu teks sekaligus tidak boleh bisa menebak isi teks dari kata yang hanya berulang di opsi benar.
- Untuk main idea, pengecoh sama luas dan sama bentuknya dengan opsi benar. Jangan hanya opsi benar yang berupa daftar tiga hal ("X, Y, and Z"), dan jangan selalu memakai pola itu.
- Tulis soal sesuai urutan slot. Selain main idea (pertama) dan organization/tone (terakhir), usahakan urutan soal mengikuti letak jawabannya di teks.
- evidence: satu kutipan PERSIS dari teks (boleh potongan kalimat) yang membuktikan jawaban. Untuk NOT/EXCEPT, kutip bagian yang menyebut opsi-opsi lainnya; boleh beberapa potongan dipisah " ... ".
- penjelasan (bahasa Indonesia): 2-4 kalimat mengalir, tanpa label dan tanpa titik dua. Jelaskan mengapa opsi benar paling sesuai dengan menafsirkan maksud teks memakai kata-katamu sendiri, bukan mengulang kalimat teks. Jangan membuka dengan "Soal ini" atau menyebut tipe soal; kalimat tentang konsep dan kutipan bukti ditambahkan sistem. Jangan menyebut huruf opsi (A-D) di penjelasan maupun alasan, karena urutan opsi akan diubah; sebut isinya.
- alasan_salah (bahasa Indonesia): untuk setiap opsi yang salah, satu atau dua klausa alasan, minimal 10 kata, TANPA awalan "keliru karena", dimulai huruf kecil. Jelaskan letak kelirunya dan apa yang sebenarnya dinyatakan teks, misalnya terlalu sempit karena hanya membahas satu paragraf, kebalikan dari pernyataan teks, atau memakai kata yang sama dengan makna berbeda. Jangan berhenti pada "tidak disebut di teks"; tambahkan apa yang sebenarnya dibahas teks tentang hal itu. Untuk huruf kunci, isi "-".

TIPE SOAL
{type_lines}

CONTOH GAYA (dari tryout lama TOEFL Academy; tiru gayanya, jangan topik atau kalimatnya)
{reference['passage']}

{example}"""


def build_prompt(passage, spec, main_idea_stems=()):
    lo, hi = spec["passage_words"]
    slots = "\n".join(f"{s['slot']}. tipe={s['type']}, level={s['level']}" for s in passage["slots"])
    # Bentuk pertanyaan main idea digilir per teks supaya tidak seragam dalam satu paket.
    stem = f'\nBentuk pertanyaan main idea untuk teks ini: "{main_idea_stems[(passage["index"] - 1) % len(main_idea_stems)]}"' if main_idea_stems else ""
    return f"""Tulis TEKS {passage['index']} untuk satu paket TOEFL ITP.

Bidang: {passage['field']}
Topik: {passage['topic']['title']}
Panjang: {lo}-{hi} kata, {PARAGRAPHS[0]}-{PARAGRAPHS[1]} paragraf.
Judul: singkat, dalam bahasa Inggris.

Rencana soal ({len(passage['slots'])} soal, ikuti urutan dan tipenya persis):
{slots}

Level: Mudah = jawaban langsung ditemukan; Sedang = perlu memahami parafrase; Sulit = perlu menyimpulkan atau membandingkan beberapa bagian, dengan pengecoh yang lebih dekat.
Untuk vocabulary dan reference, sebut nomor paragrafnya dan apit kata yang ditanyakan dengan tanda kutip ganda.{stem}"""


def response_schema(type_ids):
    letters = {L: {"type": "string"} for L in LETTERS}
    letter_obj = {"type": "object", "properties": letters, "required": list(LETTERS), "additionalProperties": False}
    question = {
        "type": "object",
        "properties": {
            "slot": {"type": "integer"},
            "type": {"type": "string", "enum": list(type_ids)},
            "question": {"type": "string"},
            "options": letter_obj,
            "key": {"type": "string", "enum": list(LETTERS)},
            "evidence": {"type": "string"},
            "penjelasan": {"type": "string"},
            "alasan_salah": letter_obj,
        },
        "required": ["slot", "type", "question", "options", "key", "evidence", "penjelasan", "alasan_salah"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "paragraphs": {"type": "array", "items": {"type": "string"}},
            "questions": {"type": "array", "items": question},
        },
        "required": ["title", "paragraphs", "questions"],
        "additionalProperties": False,
    }


# ---------- Validasi ----------

def word_count(paragraphs):
    return sum(len(p.split()) for p in paragraphs)


def validate_passage(data, passage, spec):
    """Kembalikan daftar masalah; kosong berarti teks dan soal memenuhi aturan."""
    problems = []
    paragraphs = data.get("paragraphs") or []
    if not data.get("title", "").strip():
        problems.append("judul kosong")
    if not PARAGRAPHS[0] <= len(paragraphs) <= PARAGRAPHS[1]:
        problems.append(f"teks berisi {len(paragraphs)} paragraf, seharusnya {PARAGRAPHS[0]}-{PARAGRAPHS[1]}")
    lo, hi = spec["passage_words"]
    words = word_count(paragraphs)
    if not lo <= words <= hi:
        problems.append(f"teks berisi {words} kata, seharusnya {lo}-{hi}")
    full = " ".join(paragraphs)

    questions = data.get("questions") or []
    if len(questions) != len(passage["slots"]):
        problems.append(f"jumlah soal {len(questions)}, seharusnya {len(passage['slots'])}")
        return problems
    for q, slot in zip(questions, passage["slots"]):
        tag = f"soal slot {slot['slot']}"
        if q["type"] != slot["type"]:
            problems.append(f"{tag}: tipe {q['type']}, seharusnya {slot['type']}")
        problems += [f"{tag}: {p}" for p in option_problems(q)]
        if not evidence_found(q["evidence"], full):
            problems.append(f"{tag}: evidence tidak ditemukan persis di teks")
        if slot["type"] in ("vocabulary", "reference"):
            m = re.search(r"paragraph (\d+)", q["question"], re.I)
            word = QUOTED.search(q["question"])
            if not m or not word:
                problems.append(f"{tag}: harus menyebut nomor paragraf dan kata dalam tanda kutip ganda")
            elif not 1 <= int(m.group(1)) <= len(paragraphs):
                problems.append(f"{tag}: paragraf {m.group(1)} tidak ada")
            elif not re.search(rf"\b{re.escape(norm(word.group(1)))}\b", norm(paragraphs[int(m.group(1)) - 1])):
                problems.append(f"{tag}: kata \"{word.group(1)}\" tidak ada di paragraf {m.group(1)}")
        if slot["type"] == "negative_detail" and not re.search(r"\b(NOT|EXCEPT)\b", q["question"]):
            problems.append(f"{tag}: soal NOT/EXCEPT harus memuat kata NOT atau EXCEPT kapital")
    return problems + length_problems(questions)


# ---------- Konversi ke Item ----------

def build_items(data, passage, type_meta, start):
    header = f"PASSAGE {passage['index']}: {data['title'].strip()}"
    body = "\n\n".join(p.strip() for p in data["paragraphs"])
    words = word_count(data["paragraphs"])
    items = []
    for n, (q, slot) in enumerate(zip(data["questions"], passage["slots"]), start=start):
        options, reasons, penjelasan = place_key(q, slot["key"])
        meta = type_meta[slot["type"]]
        explanation = (f"Soal ini membahas {meta['konsep']}. {penjelasan.strip()} "
                       f"Hal ini terlihat dari bagian teks \"{q['evidence'].strip().rstrip('.')}\".")
        items.append(Item(
            section="reading",
            part="reading",
            family_id=slot["type"],
            topic=passage["topic"]["title"],
            level=slot["level"],
            stem=f"{header}\n\n{body}\n\n{q['question'].strip()}",
            options=options,
            key=slot["key"],
            pembahasan=format_pembahasan(slot["key"], explanation, reason_clauses(reasons), meta["cara_cepat"]),
            frame_id=passage["topic"]["id"],
            fingerprint=f"READ:{passage['topic']['id']}#{slot['slot']}",
            number=n,
            meta={"passage": passage["index"], "words": words, "field": passage["field"], "title": data["title"].strip()},
        ))
    return items


# ---------- Pembuatan ----------

def generate_reading(plan, bp, cache_dir, get_client, log=print, max_attempts=3):
    """Buat semua teks dalam rencana. Teks yang sudah ada di cache tidak dibuat ulang.
    `get_client` dipanggil hanya bila ada teks yang perlu dibuat."""
    spec = bp["sections"]["reading"]
    types = load_types()
    type_meta = {t["id"]: t for t in types}
    with open(REFERENCE_PATH, encoding="utf-8") as f:
        reference = json.load(f)
    system = build_system(types, reference)
    schema = response_schema([t["id"] for t in types])
    main_idea_stems = next(t["stems"] for t in types if t["id"] == "main_idea")

    batch = []
    for k, passages in enumerate(plan, start=1):
        items = []
        for passage in passages:
            data = cached_generate(
                cache_dir / f"P{k}_teks{passage['index']}_{passage['topic']['id']}.json",
                system, build_prompt(passage, spec, main_idea_stems), schema,
                lambda d, passage=passage: validate_passage(d, passage, spec),
                get_client, log, f"Paket {k} teks {passage['index']} ({passage['topic']['title']})",
                max_attempts, error=ReadingError,
            )
            items += build_items(data, passage, type_meta, start=len(items) + 1)
        batch.append(items)
    return batch

