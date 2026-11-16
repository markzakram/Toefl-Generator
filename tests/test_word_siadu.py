import re

from docx import Document

from toefl_gen.cli import main
from toefl_gen.common import format_pembahasan
from toefl_gen.models import LETTERS, Item
from toefl_gen.word_siadu import write_section_word


def _item(section, part, number, stem, key="B", family="detail", **meta):
    reasons = {L: f"alasan {L}" for L in LETTERS if L != key}
    transcript = ["MAN: Hi.", "NARRATOR: What?"] if section == "listening" else ()
    return Item(section=section, part=part, family_id=family, topic="t", level="Sedang", stem=stem,
                options=["satu", "dua", "tiga", "empat"], key=key,
                pembahasan=format_pembahasan(key, "Soal ini membahas X.", reasons, "Cari Y.", transcript=transcript),
                frame_id="f", fingerprint=f"{section}{number}", number=number, meta=meta)


def _paragraphs(path):
    return [p.text for p in Document(path).paragraphs]


def _chunks(lines):
    """Pembagian blok yang sama dengan pembaca Word di SiAdu Auto Input."""
    starts = [i for i, line in enumerate(lines) if re.fullmatch(r"SOAL\s+\d+", line, re.I)]
    return [lines[s:e] for s, e in zip(starts, starts[1:] + [len(lines)])]


def _parts(chunk):
    level = next(i for i, line in enumerate(chunk) if re.match(r"Tingkat\s+Kesulitan\s*:", line, re.I))
    answer = next(i for i, line in enumerate(chunk) if re.match(r"Jawaban\s*:\s*[A-F]\b", line, re.I))
    return chunk[1:level + 1], chunk[level + 1:answer], chunk[answer:]


def test_susunan_soal_mengikuti_format_siadu(tmp_path):
    path = tmp_path / "s.docx"
    items = [_item("structure", "structure", 1, "The cat ___ here.", family="SVA"),
             _item("structure", "written_expression", 16, "The cats(A) runs(B) fast(C) today(D).", key="B", family="SVA")]
    write_section_word(path, items, "structure", 1, 2027)
    chunks = _chunks(_paragraphs(path))
    assert [c[0] for c in chunks] == ["Soal 1", "Soal 16"]
    metadata, content, explanation = _parts(chunks[0])
    assert metadata == ["Category: TOEFL ITP", "Lesson: Structure and Written Expression",
                        "Chapter: Structure - subject-verb agreement", "Bentuk Soal: Option New", "Tingkat Kesulitan: Sedang"]
    assert content == ["The cat ___ here.", "A. satu", "B. dua", "C. tiga", "D. empat"]
    assert explanation == ["Jawaban: B", "Pembahasan:", "", "Soal ini membahas X.", "",
                           "* Opsi A keliru karena alasan A.", "* Opsi C keliru karena alasan C.",
                           "* Opsi D keliru karena alasan D.", "", "Cara cepat:", "Cari Y."]


def test_nama_file_audio_hanya_ada_di_metadata(tmp_path):
    path = tmp_path / "l.docx"
    item = _item("listening", "A", 1, "Listen to the audio carefully.", family="idiom", audio_file="P1_L_A_001.mp3")
    write_section_word(path, [item], "listening", 1, 2027)
    lines = _paragraphs(path)
    metadata, content, explanation = _parts(_chunks(lines)[0])
    assert "File audio: P1_L_A_001.mp3" in metadata
    assert "Chapter: Part A - Idiom" in metadata
    assert not any("mp3" in line for line in content + explanation)
    assert content[0] == "Listen to the audio carefully."
    assert explanation[:6] == ["Jawaban: B", "Pembahasan:", "", "Transkrip Audio:", "MAN: Hi.", "NARRATOR: What?"]
    assert any("folder audio" in line for line in lines[:lines.index("Soal 1")])


def test_section_tanpa_audio_tidak_memuat_petunjuk_audio(tmp_path):
    path = tmp_path / "s.docx"
    write_section_word(path, [_item("structure", "structure", 1, "The cat ___ here.", family="SVA")], "structure", 1, 1)
    assert not any("audio" in line.lower() for line in _paragraphs(path))


def test_teks_reading_menjadi_paragraf_sebelum_opsi(tmp_path):
    path = tmp_path / "r.docx"
    stem = "PASSAGE 1: Judul\n\nParagraf satu.\n\nParagraf dua.\n\nWhat is the main idea?"
    write_section_word(path, [_item("reading", "reading", 1, stem, family="main_idea")], "reading", 1, 1)
    metadata, content, _ = _parts(_chunks(_paragraphs(path))[0])
    assert "Chapter: Main idea" in metadata
    assert content[:4] == ["PASSAGE 1: Judul", "Paragraf satu.", "Paragraf dua.", "What is the main idea?"]
    assert content[4] == "A. satu"


def test_soal_dan_jawaban_tebal_lewat_style(tmp_path):
    path = tmp_path / "s.docx"
    write_section_word(path, [_item("structure", "structure", 1, "The cat ___ here.", family="SVA")], "structure", 1, 1)
    paragraphs = {p.text: p for p in Document(path).paragraphs}
    assert paragraphs["Soal 1"].style.name == "SiaduQuestion" and paragraphs["Soal 1"].style.font.bold
    assert paragraphs["Jawaban: B"].style.name == "SiaduAnswer"
    assert paragraphs["Cara cepat:"].runs[0].bold
    # Pembaca Word menganggap setiap penanda bold sebagai tebal, jadi teks biasa tidak boleh membawanya.
    assert paragraphs["Cari Y."].runs[0].bold is None


def test_perintah_generate_membuat_word_per_paket(tmp_path):
    args = ["generate", "--seed", "1", "--paket", "1", "--sections", "structure", "--no-register", "--out", str(tmp_path)]
    assert main(args) == 0
    path = tmp_path / "seed-1" / "P1" / "P1_structure_siadu.docx"
    chunks = _chunks(_paragraphs(path))
    assert len(chunks) == 40
    assert all(_parts(c)[1][-4][:3] == "A. " and _parts(c)[1][-1][:3] == "D. " for c in chunks)
