"""Section Listening: rencana per paket, naskah lewat Claude, validasi, dan konversi ke Item.

Part A berisi percakapan pendek (satu soal per percakapan). Part B dan C berisi
percakapan panjang dan kuliah, masing-masing dengan empat soal.
"""

import hashlib
import json
import random
import re
from concurrent.futures import ThreadPoolExecutor

import yaml

from .blueprint import ROOT, level_counts
from .common import (GenerationError, cached_generate, evidence_found, format_pembahasan, length_problems,
                     option_problems, place_key, reason_clauses, used_topics, words)
from .keys import KeyBalanceError, assign, split_quota
from .models import LETTERS, Item

TYPES_PATH = ROOT / "data" / "listening" / "question_types.yaml"
TOPICS_PATH = ROOT / "data" / "listening" / "topics.yaml"
REFERENCE_PATH = ROOT / "data" / "reference" / "listening_3892.json"
PARTS = ("A", "B", "C")
VOICE_ROLES = {"MAN": ["male1", "male2"], "WOMAN": ["female1", "female2"]}
STEM = "Listen to the audio carefully."
CHUNK_A = 10
MAX_LINE_WORDS = 30
GROUP_TYPES = ["main_topic", "detail", "inference"]
LINES = {"B": (8, 16), "C": (3, 10)}
SPEAKERS = {"B": ["MAN", "WOMAN"], "C": ["PROFESSOR"]}
OR_PATTERN = re.compile(r"\b\w+ or \w+\b", re.I)
# Tipe yang bertumpu pada ungkapan baku; ungkapannya tidak boleh berulang dalam satu batch.
PHRASE_TYPES = ("idiom", "negative", "condition", "agreement")
NAMES = {
    "MAN": ["Daniel", "Marcus", "Ethan", "Carlos", "Ben", "Omar", "Ryan", "Tom"],
    "WOMAN": ["Hannah", "Priya", "Grace", "Elena", "Nina", "Maya", "Rachel", "Sara"],
}
OPENINGS = [
    "langsung ke topik dengan sebuah pertanyaan kepada mahasiswa",
    "mengaitkan dengan materi pertemuan sebelumnya",
    "memulai dengan contoh atau cerita singkat dari kehidupan sehari-hari",
]


class ListeningError(GenerationError):
    pass


def load_types(path=TYPES_PATH):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_topics(path=TOPICS_PATH):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def other(speaker):
    return "WOMAN" if speaker == "MAN" else "MAN"


# ---------- Rencana ----------

def _levels(hardness, counts, rng):
    ranked = sorted(range(len(hardness)), key=lambda i: hardness[i] + rng.random() * 0.6, reverse=True)
    levels = [None] * len(hardness)
    for r, i in enumerate(ranked):
        levels[i] = "Sulit" if r < counts["Sulit"] else "Mudah" if r >= len(hardness) - counts["Mudah"] else "Sedang"
    return levels


def plan_listening(bp, seed, paket, blocked=frozenset(), types=None, topics=None):
    types = types or load_types()
    topics = topics or load_topics()
    parts = bp["sections"]["listening"]["parts"]
    rng = random.Random(f"{seed}:listening:plan")

    a_types = [t for t in types["part_a"] for _ in range(t["per_paket"])]
    if len(a_types) != parts["A"]["items"]:
        raise ListeningError(f"Jumlah per_paket Part A harus {parts['A']['items']}.")
    rng.shuffle(a_types)
    a_levels = _levels([t["hardness"] for t in a_types], level_counts(parts["A"]["items"], bp["level_mix"]), rng)
    if len(topics["settings"]) < parts["A"]["items"]:
        raise ListeningError("Daftar settings di topics.yaml kurang dari jumlah soal Part A.")

    groups = {}
    for part, key in (("B", "part_b"), ("C", "part_c")):
        per_group = parts[part]["per_group"]
        n_groups = parts[part]["items"] // per_group
        seq = types[key]
        if len(seq) != per_group:
            raise ListeningError(f"Urutan tipe Part {part} harus berisi {per_group} soal.")
        flat = seq * n_groups
        levels = _levels([t["hardness"] for t in flat], level_counts(parts[part]["items"], bp["level_mix"]), rng)
        taken = used_topics(blocked, f"LIS{part}:")
        free = [t for t in topics[key] if t["id"] not in taken]
        if len(free) < n_groups * paket:
            raise ListeningError(f"Topik Part {part} tinggal {len(free)}, butuh {n_groups * paket}. Tambah di topics.yaml.")
        groups[part] = (seq, levels, n_groups, per_group, rng.sample(free, n_groups * paket))

    plan = []
    for k in range(paket):
        quotas = split_quota({p: parts[p]["items"] for p in PARTS}, rng)
        order = [p for p in PARTS for _ in range(parts[p]["items"])]
        try:
            keys = iter(assign(order, [list(LETTERS)] * len(order), quotas, bp["key_rules"]["max_run"], rng))
        except KeyBalanceError as e:
            raise ListeningError(str(e)) from e
        n_a = parts["A"]["items"]
        settings = rng.sample(topics["settings"], n_a)
        # Pembicara pertama seimbang, supaya pertanyaan tidak condong ke salah satu pembicara.
        firsts = ["MAN", "WOMAN"] * (n_a // 2) + ["MAN"] * (n_a % 2)
        rng.shuffle(firsts)
        entry = {"A": []}
        for i, t in enumerate(a_types):
            entry["A"].append({
                "slot": parts["A"]["first"] + i, "type": t["id"], "level": a_levels[i], "key": next(keys),
                "first": firsts[i], "setting": settings[i],
                "voices": {"MAN": rng.choice(VOICE_ROLES["MAN"]), "WOMAN": rng.choice(VOICE_ROLES["WOMAN"])},
            })
        for part in ("B", "C"):
            seq, levels, n_groups, per_group, chosen = groups[part]
            number = parts[part]["first"]
            entry[part] = []
            men, women = rng.sample(NAMES["MAN"], n_groups), rng.sample(NAMES["WOMAN"], n_groups)
            for g in range(n_groups):
                extra = {}
                if part == "B":
                    voices = {s: rng.choice(VOICE_ROLES[s]) for s in ("MAN", "WOMAN")}
                    extra["names"] = {"MAN": men[g], "WOMAN": women[g]}
                else:
                    voices = {"PROFESSOR": rng.choice(VOICE_ROLES["MAN"] + VOICE_ROLES["WOMAN"])}
                    extra["opening"] = OPENINGS[g % len(OPENINGS)]
                slots = []
                for j, t in enumerate(seq):
                    slots.append({"slot": number, "type": t["id"], "name": t["name"],
                                  "level": levels[g * per_group + j], "key": next(keys)})
                    number += 1
                entry[part].append({"index": g + 1, "topic": chosen[k * n_groups + g], "voices": voices, "slots": slots,
                                    **extra})
        plan.append(entry)
    return plan


def plan_part_c_set(bp, seed, lectures, blocked=frozenset(), types=None, topics=None):
    """Rencana set latihan Part C saja: `lectures` kuliah, empat soal per kuliah, bernomor dari 1."""
    types = types or load_types()
    topics = topics or load_topics()
    rng = random.Random(f"{seed}:listening:part-c")
    seq = types["part_c"]
    total = lectures * len(seq)
    taken = used_topics(blocked, "LISC:")
    free = [t for t in topics["part_c"] if t["id"] not in taken]
    if len(free) < lectures:
        raise ListeningError(f"Topik Part C tinggal {len(free)}, butuh {lectures}. Tambah di topics.yaml.")
    chosen = rng.sample(free, lectures)
    levels = _levels([t["hardness"] for t in seq * lectures], level_counts(total, bp["level_mix"]), rng)
    try:
        keys = iter(assign(["C"] * total, [list(LETTERS)] * total, split_quota({"C": total}, rng),
                           bp["key_rules"]["max_run"], rng))
    except KeyBalanceError as e:
        raise ListeningError(str(e)) from e
    groups = []
    for g in range(lectures):
        slots = [{"slot": g * len(seq) + j + 1, "type": t["id"], "name": t["name"],
                  "level": levels[g * len(seq) + j], "key": next(keys)} for j, t in enumerate(seq)]
        groups.append({"index": g + 1, "topic": chosen[g], "slots": slots, "opening": OPENINGS[g % len(OPENINGS)],
                       "voices": {"PROFESSOR": rng.choice(VOICE_ROLES["MAN"] + VOICE_ROLES["WOMAN"])}})
    return groups


# ---------- Prompt ----------

def build_system(types, reference):
    a_lines = "\n".join(f"- {t['id']} ({t['name']}): {t['rules']} Bentuk pertanyaan: {t['question']}" for t in types["part_a"])
    examples = "\n\n".join(
        it["transcript"] + "\n" + "\n".join(f"{L}. {it['options'][L]}" for L in LETTERS) + f"\nKunci: {it['key']}"
        for it in reference["items"]
    )
    return f"""Kamu penulis soal Listening TOEFL ITP untuk TOEFL Academy (Indonesia). Naskahmu akan dibacakan text-to-speech, jadi tulis bahasa lisan Amerika yang natural.

ATURAN NASKAH
- Orisinal; jangan menyalin dari buku persiapan TOEFL atau ETS.
- Bahasa lisan sehari-hari: bentuk singkat (I'm, don't, it's), sesekali "Oh," "Well," atau "Hmm,". Hindari slang yang tidak umum.
- Konteks kampus atau kehidupan sehari-hari mahasiswa. Hindari topik sensitif.
- Jangan menulis keterangan panggung atau tanda kurung; semua teks akan dibacakan.

ATURAN SOAL
- Pertanyaan ditulis dalam bahasa Inggris, seperti yang dibacakan narator.
- Empat opsi (A-D), tepat satu benar. Opsi sejajar bentuk, panjang, dan tingkat kerinciannya.
- Opsi TIDAK BOLEH menyalin kalimat atau potongan kalimat dari naskah. Opsi benar memparafrasekan maksudnya.
- Opsi benar tidak memakai pola "X or Y". Opsi benar boleh menjadi yang terpanjang paling banyak 3 dari 10 soal; sering-seringlah membuatnya lebih pendek daripada pengecoh.
- Peserta yang hanya melihat opsi, tanpa mendengar naskah, tidak boleh bisa menebak jawabannya. Semua opsi harus sama masuk akalnya bagi orang yang belum mendengar naskah.
- Kata mutlak (only, every, always, never) dan kata pelunak (may, probably, often) harus muncul merata di opsi benar dan pengecoh. Opsi benar tidak boleh selalu yang paling umum atau paling netral.
- Ungkapan di aturan tipe soal hanyalah contoh. Variasikan, jangan selalu memakai contoh itu.
- Untuk Part B dan C: pengecoh harus terdengar sama benarnya menurut pengetahuan umum tentang topiknya. Pengecoh boleh berupa hal yang benar di dunia nyata tetapi tidak disebut atau tidak menjawab pertanyaan, sehingga soal tidak bisa dijawab hanya dengan pengetahuan umum.
- Antarsoal dalam satu percakapan atau kuliah Part B dan C: opsi benar tidak boleh menjadi satu-satunya yang saling menguatkan. Istilah dan gagasan yang berulang di opsi benar juga harus muncul di pengecoh soal lain, dan pengecoh dari beberapa soal harus bisa membentuk gambaran yang sama masuk akalnya. Orang yang hanya melihat semua opsi satu kelompok sekaligus tidak boleh bisa menebak isi naskah dari kata yang hanya berulang di opsi benar.
- penjelasan (bahasa Indonesia): 2-4 kalimat mengalir, tanpa label dan tanpa titik dua. Jelaskan mengapa opsi benar paling sesuai dengan menafsirkan maksud pembicara memakai kata-katamu sendiri, bukan mengulang kalimat naskah. Jangan membuka dengan "Soal ini" atau menyebut tipe soal; kalimat tentang konsep ditambahkan sistem. Jangan menyebut huruf opsi (A-D) di penjelasan maupun alasan, karena urutan opsi akan diubah; sebut isinya.
- alasan_salah (bahasa Indonesia): untuk setiap opsi salah, satu atau dua klausa alasan, minimal 10 kata, TANPA awalan "keliru karena", dimulai huruf kecil. Jelaskan letak kelirunya dan apa yang sebenarnya dimaksud pembicara, misalnya memakai kata yang terdengar mirip, mengambil makna harfiah, atau kebalikan dari ucapannya. Jangan berhenti pada "tidak disebut"; tambahkan apa yang sebenarnya dibicarakan tentang hal itu. Untuk huruf kunci, isi "-".

TIPE SOAL PART A
{a_lines}

PART B: percakapan panjang dua mahasiswa (MAN dan WOMAN). PART C: kuliah oleh PROFESSOR.
Tipe soal Part B/C: main_topic (apa yang terutama dibahas), detail (informasi yang disebut), inference (hal yang tersirat atau tujuan/rencana pembicara).

CONTOH GAYA PART A (dari tryout lama TOEFL Academy; tiru gayanya, jangan isinya)
{examples}"""


def build_prompt_a(slots, used=()):
    plan = "\n".join(
        f"{s['slot']}. tipe={s['type']}, level={s['level']}, pembicara pertama={s['first']}, "
        f"pembicara kedua={other(s['first'])}, situasi={s['setting']}" for s in slots
    )
    avoid = ""
    if used:
        avoid = ("\n\nKalimat berikut sudah dipakai di batch ini. Jangan memakai idiom atau ungkapan yang sama:\n"
                 + "\n".join(f"- {line}" for line in used))
    return f"""Tulis {len(slots)} percakapan pendek Listening Part A, satu untuk setiap baris rencana.

Setiap percakapan:
- Pembicara pertama: 1 kalimat, paling banyak 20 kata.
- Pembicara kedua: 1-2 kalimat, paling banyak 25 kata. Di sinilah kunci jawabannya.
- Pertanyaan narator, sesuai tipe. Untuk tipe yang menanyakan maksud, tanyakan tentang pembicara kedua ("the man" atau "the woman").
- Situasi mengikuti rencana. Untuk tipe setting, tempatnya jangan disebut langsung.

Level: Mudah = maksudnya cukup jelas; Sedang = perlu memahami ungkapan; Sulit = maksudnya tersirat dan pengecohnya dekat.

Rencana:
{plan}{avoid}"""


def _article(word):
    return "an" if word[:1].lower() in "aeiou" else "a"


def intro(part, group):
    first, last = group["slots"][0]["slot"], group["slots"][-1]["slot"]
    if part == "B":
        return f"Questions {first} through {last}. Listen to a conversation between two students."
    course = group["topic"]["course"]
    return f"Questions {first} through {last}. Listen to part of a lecture in {_article(course)} {course} class."


def build_prompt_group(part, group, spec):
    lo, hi = spec["part_b_words"] if part == "B" else spec["part_c_words"]
    n_lo, n_hi = LINES[part]
    slots = "\n".join(f"{s['slot']}. tipe={s['type']}, level={s['level']}" for s in group["slots"])
    if part == "B":
        names = group["names"]
        who = (f"Percakapan dua mahasiswa tentang: {group['topic']['title']}.\n"
               f"Pembicara MAN dan WOMAN bergantian, {n_lo}-{n_hi} giliran bicara.\n"
               f"Kalau nama perlu disebut, MAN bernama {names['MAN']} dan WOMAN bernama {names['WOMAN']}. "
               f"Jangan selalu membuka dengan sapaan \"Hey\" diikuti nama.")
    else:
        who = (f"Kuliah dalam mata kuliah {group['topic']['course']} tentang: {group['topic']['title']}.\n"
               f"Pembicara hanya PROFESSOR, gaya kuliah lisan yang jelas dan ramah. "
               f"Bagi menjadi {n_lo}-{n_hi} bagian (lines), masing-masing beberapa kalimat.\n"
               f"Cara membuka kuliah: {group['opening']}. Jangan membuka dengan \"Good morning\".")
    return f"""Tulis naskah Listening Part {part} untuk soal {group['slots'][0]['slot']}-{group['slots'][-1]['slot']}.

{who}
Panjang naskah: {lo}-{hi} kata.

Lalu tulis {len(group['slots'])} soal sesuai urutan berikut:
{slots}

Pertanyaan berupa kalimat tanya narator, misalnya "What are the speakers mainly discussing?" atau "According to the professor, why ...?".
evidence: satu kutipan PERSIS dari naskah yang membuktikan jawaban."""


def _letters():
    return {"type": "object", "properties": {L: {"type": "string"} for L in LETTERS},
            "required": list(LETTERS), "additionalProperties": False}


def schema_a(type_ids):
    item = {
        "type": "object",
        "properties": {
            "slot": {"type": "integer"},
            "type": {"type": "string", "enum": list(type_ids)},
            "first_speaker": {"type": "string", "enum": ["MAN", "WOMAN"]},
            "first_line": {"type": "string"},
            "second_line": {"type": "string"},
            "question": {"type": "string"},
            "options": _letters(),
            "key": {"type": "string", "enum": list(LETTERS)},
            "penjelasan": {"type": "string"},
            "alasan_salah": _letters(),
        },
        "required": ["slot", "type", "first_speaker", "first_line", "second_line", "question", "options", "key",
                     "penjelasan", "alasan_salah"],
        "additionalProperties": False,
    }
    return {"type": "object", "properties": {"items": {"type": "array", "items": item}},
            "required": ["items"], "additionalProperties": False}


def schema_group(part):
    line = {"type": "object",
            "properties": {"speaker": {"type": "string", "enum": SPEAKERS[part]}, "text": {"type": "string"}},
            "required": ["speaker", "text"], "additionalProperties": False}
    question = {
        "type": "object",
        "properties": {
            "slot": {"type": "integer"},
            "type": {"type": "string", "enum": GROUP_TYPES},
            "question": {"type": "string"},
            "options": _letters(),
            "key": {"type": "string", "enum": list(LETTERS)},
            "evidence": {"type": "string"},
            "penjelasan": {"type": "string"},
            "alasan_salah": _letters(),
        },
        "required": ["slot", "type", "question", "options", "key", "evidence", "penjelasan", "alasan_salah"],
        "additionalProperties": False,
    }
    return {"type": "object",
            "properties": {"lines": {"type": "array", "items": line}, "questions": {"type": "array", "items": question}},
            "required": ["lines", "questions"], "additionalProperties": False}


# ---------- Validasi ----------

def copy_problems(q, lines, min_words):
    """Opsi yang menyalin kalimat naskah, persis atau hampir persis."""
    problems = []
    for L in LETTERS:
        opt = words(q["options"][L])
        if len(opt) < min_words:
            continue
        for line in lines:
            ln = words(line)
            overlap = len(set(opt) & set(ln)) / len(set(opt) | set(ln)) if ln else 0
            if f" {' '.join(opt)} " in f" {' '.join(ln)} " or overlap >= 0.75:
                problems.append(f"opsi {L} menyalin kalimat dari naskah")
                break
    if OR_PATTERN.search(q["options"][q["key"]]):
        problems.append("opsi benar memakai pola 'X or Y'")
    return problems


def validate_a(data, slots, type_meta):
    problems = []
    items = data.get("items") or []
    if len(items) != len(slots):
        return [f"jumlah percakapan {len(items)}, seharusnya {len(slots)}"]
    for q, s in zip(items, slots):
        tag = f"Part A no {s['slot']}"
        if q["type"] != s["type"]:
            problems.append(f"{tag}: tipe {q['type']}, seharusnya {s['type']}")
        if q["first_speaker"] != s["first"]:
            problems.append(f"{tag}: pembicara pertama harus {s['first']}")
        for name in ("first_line", "second_line"):
            n = len(q[name].split())
            if not n or n > MAX_LINE_WORDS:
                problems.append(f"{tag}: {name} berisi {n} kata (maksimal {MAX_LINE_WORDS})")
        if not q["question"].strip().endswith("?"):
            problems.append(f"{tag}: pertanyaan harus diakhiri tanda tanya")
        second = other(s["first"]).lower()
        if type_meta[s["type"]]["about_second"] and not re.search(rf"\bthe {second}\b", q["question"].lower()):
            problems.append(f"{tag}: pertanyaan harus tentang pembicara kedua (the {second})")
        problems += [f"{tag}: {p}" for p in option_problems(q)]
        problems += [f"{tag}: {p}" for p in copy_problems(q, [q["first_line"], q["second_line"]], 3)]
    return problems + length_problems(items)


def validate_group(data, part, group, spec):
    problems = []
    lines = data.get("lines") or []
    n_lo, n_hi = LINES[part]
    if not n_lo <= len(lines) <= n_hi:
        problems.append(f"naskah berisi {len(lines)} bagian, seharusnya {n_lo}-{n_hi}")
    if part == "B" and {ln["speaker"] for ln in lines} != {"MAN", "WOMAN"}:
        problems.append("percakapan harus melibatkan MAN dan WOMAN")
    lo, hi = spec["part_b_words"] if part == "B" else spec["part_c_words"]
    total = sum(len(ln["text"].split()) for ln in lines)
    if not lo <= total <= hi:
        problems.append(f"naskah berisi {total} kata, seharusnya {lo}-{hi}")
    full = " ".join(ln["text"] for ln in lines)

    questions = data.get("questions") or []
    if len(questions) != len(group["slots"]):
        return problems + [f"jumlah soal {len(questions)}, seharusnya {len(group['slots'])}"]
    for q, s in zip(questions, group["slots"]):
        tag = f"soal {s['slot']}"
        if q["type"] != s["type"]:
            problems.append(f"{tag}: tipe {q['type']}, seharusnya {s['type']}")
        if not q["question"].strip().endswith("?"):
            problems.append(f"{tag}: pertanyaan harus diakhiri tanda tanya")
        problems += [f"{tag}: {p}" for p in option_problems(q)]
        if not evidence_found(q["evidence"], full):
            problems.append(f"{tag}: evidence tidak ditemukan persis di naskah")
        problems += [f"{tag}: {p}" for p in copy_problems(q, [ln["text"] for ln in lines], 5)]
    return problems + length_problems(questions)


# ---------- Konversi ke Item ----------

def _audio_name(k, part, number):
    return f"P{k}_L_{part}_{number:03d}.mp3"


def build_a_item(q, s, k, type_meta):
    first, second = s["first"], other(s["first"])
    script = [[first, q["first_line"].strip()], [second, q["second_line"].strip()], ["NARRATOR", q["question"].strip()]]
    options, reasons, penjelasan = place_key(q, s["key"])
    meta = type_meta[s["type"]]
    pembahasan = format_pembahasan(
        s["key"], f"Soal ini membahas {meta['konsep']}. {penjelasan.strip()}", reason_clauses(reasons),
        meta["cara_cepat"], transcript=[f"{spk}: {text}" for spk, text in script],
    )
    digest = hashlib.sha1(q["second_line"].strip().lower().encode("utf-8")).hexdigest()[:10]
    return Item(
        section="listening", part="A", family_id=s["type"], topic=s["setting"], level=s["level"], stem=STEM,
        options=options, key=s["key"], pembahasan=pembahasan, frame_id=s["setting"],
        fingerprint=f"LISA:{s['setting']}:{s['type']}:{digest}", number=s["slot"],
        meta={"audio_script": script, "voices": s["voices"], "audio_file": _audio_name(k, "A", s["slot"]),
              "transcript_lines": [q["first_line"], q["second_line"]],
              "transcript": "\n".join(f"{spk}: {text}" for spk, text in script[:2]), "question": script[2][1]},
    )


def build_group_items(data, part, group, k, audio_mode, type_meta):
    lines = [[ln["speaker"], ln["text"].strip()] for ln in data["lines"]]
    opening = intro(part, group)
    items = []
    for j, (q, s) in enumerate(zip(data["questions"], group["slots"])):
        question = q["question"].strip()
        script = ([["NARRATOR", opening]] + lines if audio_mode == "every" or j == 0 else []) + [["NARRATOR", question]]
        options, reasons, penjelasan = place_key(q, s["key"])
        meta = type_meta[s["type"]]
        explanation = (f"Soal ini membahas {meta['konsep']}. {penjelasan.strip()} "
                       f"Hal ini terdengar dari ucapan \"{q['evidence'].strip().rstrip('.')}\".")
        pembahasan = format_pembahasan(
            s["key"], explanation, reason_clauses(reasons), meta["cara_cepat"],
            transcript=[f"{spk}: {text}" for spk, text in lines] + [f"NARRATOR: {question}"],
        )
        items.append(Item(
            section="listening", part=part, family_id=s["type"], topic=group["topic"]["title"], level=s["level"],
            stem=STEM, options=options, key=s["key"], pembahasan=pembahasan, frame_id=group["topic"]["id"],
            fingerprint=f"LIS{part}:{group['topic']['id']}#{j + 1}", number=s["slot"],
            meta={"audio_script": script, "voices": group["voices"], "audio_file": _audio_name(k, part, s["slot"]),
                  "group": group["index"], "transcript_lines": [text for _, text in lines],
                  "transcript": "\n".join(f"{spk}: {text}" for spk, text in lines), "question": question},
        ))
    return items


# ---------- Pembuatan ----------

def generate_listening(plan, bp, cache_dir, get_client, log=print, max_attempts=3):
    spec = bp["sections"]["listening"]
    types = load_types()
    type_meta = {t["id"]: t for t in types["part_a"]}
    with open(REFERENCE_PATH, encoding="utf-8") as f:
        reference = json.load(f)
    system = build_system(types, reference)
    s_a = schema_a(list(type_meta))

    batch = []
    used_phrases = []
    for k, entry in enumerate(plan, start=1):
        items = []
        for c in range(0, len(entry["A"]), CHUNK_A):
            chunk = entry["A"][c:c + CHUNK_A]
            data = cached_generate(
                cache_dir / f"P{k}_A{c // CHUNK_A + 1}.json", system, build_prompt_a(chunk, used_phrases), s_a,
                lambda d, chunk=chunk: validate_a(d, chunk, type_meta), get_client, log,
                f"Paket {k} Part A no {chunk[0]['slot']}-{chunk[-1]['slot']}", max_attempts, error=ListeningError,
            )
            items += [build_a_item(q, s, k, type_meta) for q, s in zip(data["items"], chunk)]
            used_phrases += [q["second_line"].strip() for q in data["items"] if q["type"] in PHRASE_TYPES]
        for part in ("B", "C"):
            for group in entry[part]:
                data = cached_generate(
                    cache_dir / f"P{k}_{part}{group['index']}_{group['topic']['id']}.json", system,
                    build_prompt_group(part, group, spec), schema_group(part),
                    lambda d, part=part, group=group: validate_group(d, part, group, spec), get_client, log,
                    f"Paket {k} Part {part} ({group['topic']['title']})", max_attempts, error=ListeningError,
                )
                items += build_group_items(data, part, group, k, spec["audio_mode"], types["group_types"])
        batch.append(items)
    return batch


def generate_part_c_set(groups, bp, cache_dir, get_client, log=print, max_attempts=3, workers=4):
    """Buat naskah dan soal semua kuliah, beberapa sekaligus. Kuliah yang ada di cache tidak dibuat ulang."""
    spec = bp["sections"]["listening"]
    types = load_types()
    with open(REFERENCE_PATH, encoding="utf-8") as f:
        reference = json.load(f)
    system = build_system(types, reference)
    schema = schema_group("C")

    def one(group):
        data = cached_generate(
            cache_dir / f"C{group['index']:02d}_{group['topic']['id']}.json", system,
            build_prompt_group("C", group, spec), schema, lambda d: validate_group(d, "C", group, spec), get_client, log,
            f"Part C kuliah {group['index']} ({group['topic']['title']})", max_attempts, error=ListeningError,
        )
        return build_group_items(data, "C", group, 1, spec["audio_mode"], types["group_types"])

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return [it for items in pool.map(one, groups) for it in items]
