"""Ekspor ke Excel format impor SiAdu, plus ringkasan dan arsip batch."""

import json
from collections import Counter
from dataclasses import asdict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

from .models import LETTERS

SIADU_HEADERS = [
    "no", "level", "soal", "opsi_a", "opsi_b", "opsi_c", "opsi_d", "opsi_e", "jawaban_benar",
    "skor_a", "skor_b", "skor_c", "skor_d", "skor_e", "skor_f", "pembahasan", "answer_type",
    "table_header_0", "table_header_1", "answer_options", "is_strict_mode",
]
META_HEADERS = ["no", "part", "famili", "topik", "frame", "fingerprint", "level", "kunci", "status", "batch", "seed",
                "file_audio", "sim_0", "sim_50", "sim_80", "catatan_qc"]


def status(it):
    return "Perlu dicek" if it.meta.get("flags") else "Draf"


def _sim(it, persona):
    answer = it.meta.get("sim", {}).get(persona)
    return answer["answer"] if answer else ""


def _style(ws, widths):
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for col, width in widths.items():
        ws.column_dimensions[col].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")


def siadu_row(it):
    # Tipe option_new: satu huruf kunci. Kolom skor hanya untuk TKP (tipe option), jadi dibiarkan kosong.
    values = {
        "no": it.number, "level": it.level, "soal": it.stem, "jawaban_benar": it.key,
        "pembahasan": it.pembahasan, "answer_type": "option_new",
        **{f"opsi_{L.lower()}": option for L, option in zip(LETTERS, it.options)},
    }
    return [values.get(header) for header in SIADU_HEADERS]


def write_section_workbook(path, items, batch_id, seed):
    wb = Workbook()
    ws = wb.active
    ws.title = "SOAL"
    ws.append(SIADU_HEADERS)
    for it in items:
        ws.append(siadu_row(it))
    _style(ws, {"C": 70, "D": 22, "E": 22, "F": 22, "G": 22, "P": 80})

    meta = wb.create_sheet("META")
    meta.append(META_HEADERS)
    for it in items:
        meta.append([it.number, it.part, it.family_id, it.topic, it.frame_id, it.fingerprint, it.level, it.key, status(it),
                     batch_id, seed, it.meta.get("audio_file", ""), _sim(it, "awam"), _sim(it, "menengah"),
                     _sim(it, "mahir"), "\n".join(it.meta.get("flags", []))])
    _style(meta, {"B": 20, "D": 24, "E": 16, "F": 50, "P": 70})
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def write_summary(path, info, sections, issues):
    wb = Workbook()
    ws = wb.active
    ws.title = "Batch"
    for k, v in info.items():
        ws.append([k, str(v)])
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 60

    stats = wb.create_sheet("Paket")
    stats.append(["section", "paket", "kunci A", "kunci B", "kunci C", "kunci D", "Mudah", "Sedang", "Sulit", "topik terbanyak"])
    for section, batch in sections.items():
        for p, items in enumerate(batch, start=1):
            keys = Counter(it.key for it in items)
            levels = Counter(it.level for it in items)
            topic, n = Counter(it.topic for it in items).most_common(1)[0]
            stats.append([section, p, *(keys[L] for L in LETTERS), levels["Mudah"], levels["Sedang"], levels["Sulit"],
                          f"{topic} ({n})"])

    soal = wb.create_sheet("Soal")
    soal.append(["section", "paket", "no", "part", "famili/tipe", "frame/topik", "level", "kunci", "soal", "status"])
    for section, batch in sections.items():
        for p, items in enumerate(batch, start=1):
            for it in items:
                question = it.stem.split("\n\n")[-1] if section == "reading" else it.meta.get("question", it.stem)
                soal.append([section, p, it.number, it.part, it.family_id, it.frame_id, it.level, it.key, question,
                             status(it)])
    _style(soal, {"D": 20, "F": 22, "I": 80})

    flagged = [(section, p, it) for section, batch in sections.items()
               for p, items in enumerate(batch, start=1) for it in items if it.meta.get("flags")]
    if any(it.meta.get("sim") for batch in sections.values() for items in batch for it in items):
        sim = wb.create_sheet("Simulasi")
        sim.append(["section", "paket", "no", "kunci", "jawaban 0%", "jawaban 50%", "jawaban 80%", "catatan"])
        for section, p, it in flagged:
            sim.append([section, p, it.number, it.key, _sim(it, "awam"), _sim(it, "menengah"), _sim(it, "mahir"),
                        "\n".join(it.meta["flags"])])
        _style(sim, {"H": 100})

    qc = wb.create_sheet("QC")
    qc.append(["level", "pesan"])
    for level, msg in issues or [("OK", "Tidak ada temuan")]:
        qc.append([level, msg])
    qc.column_dimensions["B"].width = 100
    wb.save(path)


def write_archive(path, info, sections):
    data = {"info": info, "sections": {name: [[asdict(it) for it in items] for items in batch]
                                       for name, batch in sections.items()}}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
