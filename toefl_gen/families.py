"""Pustaka famili soal Structure & Written Expression berbasis template.

Setiap famili berisi beberapa frame. Frame Structure punya satu rumpang `___`,
satu jawaban benar, dan minimal tiga pengecoh beserta alasannya. Frame Written
Expression ditulis dengan penanda: `[teks](m)` untuk bagian yang boleh ditandai
dan benar, `[teks](e:bentuk benar)` untuk satu bagian yang salah. `{nama}` diisi
dari daftar `vars` milik frame. Bila satu sisi kekurangan bagian bertanda untuk
posisi kunci yang diminta, kata isi lain di sisi itu ikut ditandai.
"""

import hashlib
import itertools
import re
from dataclasses import dataclass, field

import yaml

from .blueprint import LEVELS, ROOT
from .common import format_pembahasan
from .models import LETTERS, Item

LIBRARY_PATH = ROOT / "data" / "families" / "structure_we.yaml"
FORMATS = ("structure", "written_expression")

CHUNK = re.compile(r"\[([^\]]+)\]\((m|e:[^)]*)\)")
VAR = re.compile(r"\{(\w+)\}")
WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")

# Kata fungsi yang tidak ditandai otomatis di soal Written Expression.
STOPWORDS = {
    "the", "and", "but", "for", "nor", "yet", "from", "with", "into", "onto", "upon", "over", "than",
    "that", "this", "these", "those", "they", "them", "their", "its", "his", "her", "our", "your",
    "who", "whom", "whose", "which", "what", "when", "where", "while", "about", "after", "before",
    "during", "through", "between", "among", "off", "out", "not",
}


def substitute(text, values):
    return VAR.sub(lambda m: values[m.group(1)], text)


@dataclass
class Frame:
    family: "Family"
    id: str
    format: str
    level: str
    text: str
    why: str
    correct: str = ""
    distractors: list = field(default_factory=list)
    vars: dict = field(default_factory=dict)

    @property
    def key(self):
        return f"{self.family.id}:{self.id}"

    def _texts(self):
        texts = [self.text, self.why, self.correct]
        for text, reason in self.distractors:
            texts += [text, reason]
        return texts

    def variants(self):
        """Semua kombinasi isi `vars` yang dipakai frame, dalam urutan tetap."""
        names = sorted({name for t in self._texts() for name in VAR.findall(t)})
        pools = [self.vars[name] for name in names]
        return [dict(zip(names, combo)) for combo in itertools.product(*pools)]

    def fingerprint(self, values):
        return self.key + "|" + "|".join(values[k] for k in sorted(values))

    def feasible_keys(self, values):
        """Huruf kunci yang bisa dicapai frame ini dengan isi `values`."""
        if self.format == "structure":
            return list(LETTERS)
        units = markable_units(substitute(self.text, values))
        err = next(i for i, u in enumerate(units) if u["error"])
        before, after = err, len(units) - err - 1
        return [L for k, L in enumerate(LETTERS) if k <= before and 3 - k <= after]

    def build(self, values, key, rng):
        if self.format == "structure":
            return self._build_structure(values, key, rng)
        return self._build_we(values, key, rng)

    def _build_structure(self, values, key, rng):
        fam = self.family
        sub = lambda s: substitute(s, values)
        wrong = rng.sample([(sub(t), sub(r)) for t, r in self.distractors], 3)
        k = LETTERS.index(key)
        options = [t for t, _ in wrong]
        options.insert(k, sub(self.correct))
        reasons = {LETTERS[i]: r for i, (_, r) in zip([i for i in range(4) if i != k], wrong)}
        explanation = f"Soal ini membahas {fam.konsep}. {sub(self.why)}"
        pembahasan = format_pembahasan(key, explanation, reasons, fam.cara_cepat)
        return self._item(sub(self.text), options, key, pembahasan, values)

    def _build_we(self, values, key, rng):
        fam = self.family
        sub = lambda s: substitute(s, values)
        text = sub(self.text)
        chunks = markable_units(text)
        err = next(i for i, c in enumerate(chunks) if c["error"])
        k = LETTERS.index(key)
        before = _take(chunks, range(err), k, rng, text)
        after = _take(chunks, range(err + 1, len(chunks)), 3 - k, rng, text)
        picked = sorted(before + [err] + after)
        labels = {idx: LETTERS[n] for n, idx in enumerate(picked)}

        out, pos = [], 0
        for idx, c in enumerate(chunks):
            if c["auto"] and idx not in labels:
                continue
            out.append(text[pos:c["start"]])
            out.append(c["text"] + (f"({labels[idx]})" if idx in labels else ""))
            pos = c["end"]
        out.append(text[pos:])
        stem = "".join(out)
        options = [chunks[idx]["text"] for idx in picked]

        wrong, right = chunks[err]["text"], chunks[err]["right"]
        explanation = (f'Soal ini membahas {fam.konsep}. Bagian yang keliru adalah "{wrong}" (opsi {key}), '
                       f'dan bentuk yang benar adalah "{right}". {sub(self.why)}')
        reasons = {labels[idx]: f'bagian "{chunks[idx]["text"]}" sudah benar di dalam kalimat ini, jadi tidak perlu diperbaiki'
                   for idx in picked if idx != err}
        item = self._item(stem, options, key, format_pembahasan(key, explanation, reasons, fam.cara_cepat), values)
        item.meta["marked"] = picked
        return item

    def _item(self, stem, options, key, pembahasan, values):
        return Item(
            section="structure",
            part=self.format,
            family_id=self.family.id,
            topic=self.family.topic,
            level=self.level,
            stem=stem,
            options=options,
            key=key,
            pembahasan=pembahasan,
            frame_id=self.key,
            fingerprint=self.fingerprint(values),
        )


@dataclass
class Family:
    id: str
    topic: str
    konsep: str
    cara_cepat: str
    frames: list = field(default_factory=list)

    def frames_for(self, fmt, level):
        return [f for f in self.frames if f.format == fmt and f.level == level]


def parse_chunks(text):
    chunks = []
    for m in CHUNK.finditer(text):
        tag = m.group(2)
        chunks.append({
            "start": m.start(),
            "end": m.end(),
            "text": m.group(1),
            "error": tag.startswith("e:"),
            "right": tag[2:] if tag.startswith("e:") else None,
        })
    return chunks


def markable_units(text):
    """Bagian bertanda dari penulis, ditambah kata isi di luar penanda sebagai cadangan (`auto`)."""
    chunks = [dict(c, auto=False) for c in parse_chunks(text)]
    taken = {c["text"].lower() for c in chunks}
    units = list(chunks)
    gaps = zip([0] + [c["end"] for c in chunks], [c["start"] for c in chunks] + [len(text)])
    for start, end in gaps:
        for m in WORD.finditer(text, start, end):
            word = m.group()
            if len(word) < 3 or word.lower() in STOPWORDS or word.lower() in taken:
                continue
            taken.add(word.lower())
            units.append({"start": m.start(), "end": m.end(), "text": word, "error": False, "right": None, "auto": True})
    return sorted(units, key=lambda u: u["start"])


def _take(units, positions, n, rng, text=None):
    """Ambil n posisi; bagian dari penulis didahulukan, kata otomatis hanya pengisi kekurangan.
    Kata otomatis yang bersebelahan dengan bagian terpilih dihindari agar satu frasa tidak terbelah."""
    positions = list(positions)
    authored = [i for i in positions if not units[i]["auto"]]
    auto = [i for i in positions if units[i]["auto"]]
    chosen = rng.sample(authored, min(n, len(authored)))
    rng.shuffle(auto)

    def adjacent(i, j):
        a, b = sorted((units[i], units[j]), key=lambda u: u["start"])
        return text is not None and not text[a["end"]:b["start"]].strip()

    for strict in (True, False):
        for i in auto:
            if len(chosen) == n:
                break
            if i not in chosen and not (strict and any(adjacent(i, j) for j in chosen)):
                chosen.append(i)
    return chosen


def load_library(path=LIBRARY_PATH):
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    library = {}
    for fam_raw in raw["families"]:
        fam = Family(fam_raw["id"], fam_raw["topic"], fam_raw["konsep"], fam_raw["cara_cepat"])
        for fr in fam_raw["frames"]:
            fam.frames.append(Frame(
                family=fam,
                id=fr["id"],
                format=fr["format"],
                level=fr["level"],
                text=fr["text"],
                why=fr["why"],
                correct=fr.get("correct", ""),
                distractors=[tuple(d) for d in fr.get("distractors", [])],
                vars=fr.get("vars", {}),
            ))
        library[fam.id] = fam
    return library


def library_version(path=LIBRARY_PATH):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def validate_library(library):
    """Cek struktur setiap frame untuk semua kombinasi vars. Kembalikan daftar kesalahan."""
    errors = []
    seen = set()
    for fam in library.values():
        if not fam.cara_cepat.strip():
            errors.append(f"{fam.id}: cara_cepat kosong")
        for fr in fam.frames:
            where = fr.key
            if where in seen:
                errors.append(f"{where}: id frame ganda")
            seen.add(where)
            if fr.format not in FORMATS:
                errors.append(f"{where}: format tidak dikenal '{fr.format}'")
                continue
            if fr.level not in LEVELS:
                errors.append(f"{where}: level tidak dikenal '{fr.level}'")
            missing = {n for t in fr._texts() for n in VAR.findall(t)} - set(fr.vars)
            if missing:
                errors.append(f"{where}: vars tidak didefinisikan {sorted(missing)}")
                continue
            for values in fr.variants():
                errors += [f"{where} {values}: {e}" for e in _check_variant(fr, values)]
    return errors


def _check_variant(fr, values):
    errors = []
    if fr.format == "structure":
        stem = substitute(fr.text, values)
        if stem.count("___") != 1:
            errors.append("stem harus punya tepat satu '___'")
        if len(fr.distractors) < 3:
            errors.append("pengecoh kurang dari 3")
        texts = [substitute(fr.correct, values).lower()] + [substitute(t, values).lower() for t, _ in fr.distractors]
        if len(set(texts)) != len(texts):
            errors.append("opsi tidak unik")
    else:
        chunks = parse_chunks(substitute(fr.text, values))
        if sum(c["error"] for c in chunks) != 1:
            errors.append("harus ada tepat satu bagian salah")
        elif len(chunks) < 4:
            errors.append("bagian yang bisa ditandai kurang dari 4")
        elif not fr.feasible_keys(values):
            errors.append("tidak ada posisi kunci yang bisa dicapai")
        texts = [c["text"].lower() for c in chunks]
        if len(set(texts)) != len(texts):
            errors.append("teks bagian bertanda tidak unik")
    return errors
