"""Satu file HTML mandiri untuk satu paket: mode Tim Input, Peserta, dan Peninjau.

Soal, audio, Word, dan Excel ditanam di dalam file, jadi bisa dibuka tanpa internet. File ini memuat kunci
jawaban, sehingga hanya untuk tim, bukan untuk peserta sungguhan.
"""

import base64
import json
from pathlib import Path

from .branding import embed_assets
from .families import load_library
from .listening import load_types as load_listening_types
from .packaging import GUIDE
from .reading import load_types as load_reading_types
from .simulate import AWAM_BASELINE

TEMPLATE_PATH = Path(__file__).with_name("review_template.html")
SECTIONS = {
    "listening": {"label": "Listening Comprehension", "minutes": 35, "items": 50},
    "structure": {"label": "Structure and Written Expression", "minutes": 25, "items": 40},
    "reading": {"label": "Reading Comprehension", "minutes": 55, "items": 50},
}
PART_LABELS = {"A": "Part A", "B": "Part B", "C": "Part C", "structure": "Structure",
               "written_expression": "Written Expression", "reading": ""}


def type_names():
    """Nama tipe soal per (section atau part Listening, id), karena id seperti `inference` dipakai beberapa section."""
    names = {("reading", t["id"]): t["name"] for t in load_reading_types()}
    names.update({("structure", fam.id): fam.topic for fam in load_library().values()})
    listening = load_listening_types()
    for part, key in (("A", "part_a"), ("B", "part_b"), ("C", "part_c")):
        names.update({(part, t["id"]): t["name"] for t in listening[key]})
    return names


def type_label(names, section, part, family_id):
    scope = part if section == "listening" else section
    return names.get((scope, family_id), family_id)


def _script_json(value):
    # "</" dipecah supaya isi JSON tidak bisa menutup tag <script>.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _embed(path, files):
    """Tanam satu file dokumen kalau ada. Kembalikan datanya untuk tombol unduh."""
    if not path.exists():
        return None
    data = path.read_bytes()
    files[path.name] = base64.b64encode(data).decode("ascii")
    return {"name": path.name, "size": len(data)}


def collect(batch_dir, paket):
    """Kembalikan (data soal, audio base64 per nama file, dokumen base64 per nama file, nama audio yang hilang)."""
    batch_dir = Path(batch_dir)
    archive = json.loads((batch_dir / "batch.json").read_text(encoding="utf-8"))
    info = archive["info"]
    names = type_names()
    paket_dir = batch_dir / f"P{paket}"
    audio_dir = paket_dir / "audio"

    items, passages, sections, audio, missing, docs, files = [], {}, [], {}, [], [], {}
    for section, spec in SECTIONS.items():
        batch = archive["sections"].get(section)
        if not batch:
            continue
        if not 1 <= paket <= len(batch):
            raise ValueError(f"Paket {paket} tidak ada di batch ini (tersedia 1-{len(batch)}).")
        rows = batch[paket - 1]
        # Waktu mengikuti jumlah soal, supaya set latihan yang lebih panjang tetap sebanding dengan tes asli.
        minutes = max(1, round(spec["minutes"] * len(rows) / spec["items"]))
        sections.append({"id": section, "label": spec["label"], "minutes": minutes, "count": len(rows)})
        docs.append({"label": spec["label"], "word": _embed(paket_dir / f"P{paket}_{section}_siadu.docx", files),
                     "excel": _embed(paket_dir / f"P{paket}_{section}.xlsx", files)})
        for it in rows:
            meta = it["meta"]
            row = {
                "id": f"{section}-{it['number']}", "section": section, "part": it["part"],
                "partLabel": PART_LABELS.get(it["part"], ""), "no": it["number"], "level": it["level"],
                "type": type_label(names, section, it["part"], it["family_id"]), "topic": it["topic"], "options": it["options"],
                "key": it["key"], "pembahasan": it["pembahasan"], "sim": meta.get("sim"), "flags": meta.get("flags", []),
                "stem": it["stem"],
            }
            if section == "reading":
                head, question = it["stem"].rsplit("\n\n", 1)
                title_line, _, body = head.partition("\n\n")
                pid = str(meta["passage"])
                passages[pid] = {"heading": title_line, "body": body, "words": meta["words"], "topic": it["topic"]}
                row.update(stem=question, passage=pid)
            if section == "listening":
                row.update(transcript=meta["transcript"], question=meta["question"], group=meta.get("group"),
                           audio=meta["audio_file"], audioSeconds=meta.get("audio_seconds"),
                           audioFull=len(meta["audio_script"]) > 1)
                path = audio_dir / meta["audio_file"]
                if path.exists():
                    audio[meta["audio_file"]] = base64.b64encode(path.read_bytes()).decode("ascii")
                else:
                    missing.append(meta["audio_file"])
            items.append(row)

    data = {
        "batch": info["batch"], "paket": paket, "seed": info["seed"], "versiPustaka": info.get("versi_pustaka", ""),
        "model": info.get("model", ""), "dibuat": info.get("dibuat", ""), "sections": sections,
        "passages": passages, "items": items, "baseline": AWAM_BASELINE, "docs": docs,
        "title": info.get("label") or f"Tryout TOEFL ITP · Paket {paket}",
        "heading": info.get("label") or f"Paket {paket}",
        "guide": GUIDE.format(paket=paket).replace("\n", "\r\n"),
        "audioBytes": sum(len(b) * 3 // 4 for b in audio.values()),
    }
    return data, audio, files, missing


def build_review_html(batch_dir, paket=1, out=None):
    """Tulis file HTML. Kembalikan (path file, ukuran MB, nama file audio yang hilang)."""
    batch_dir = Path(batch_dir)
    data, audio, files, missing = collect(batch_dir, paket)
    html = (embed_assets(TEMPLATE_PATH.read_text(encoding="utf-8"))
            .replace("__TITLE__", data["heading"] if data["heading"] != f"Paket {paket}" else f"Tryout TOEFL Paket {paket}")
            .replace("__DATA__", _script_json(data))
            .replace("__AUDIO__", _script_json(audio))
            .replace("__FILES__", _script_json(files)))
    path = Path(out) if out else batch_dir / f"QC_P{paket}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path, path.stat().st_size / 1_000_000, missing
