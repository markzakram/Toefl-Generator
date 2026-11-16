"""Ekspor Word format input SiAdu untuk tim input, mengikuti format generator SKD.

Word hanya berisi teks. Audio Listening tetap berupa file mp3 di folder `audio`, dan setiap soal
menyebut nama file-nya di baris `File audio:`. Baris itu berada di antara `Soal N` dan
`Tingkat Kesulitan`, yaitu bagian metadata, jadi tidak ikut masuk ke teks soal.
"""

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.shared import Pt, Twips

from .models import LETTERS
from .review_html import PART_LABELS, SECTIONS, type_label, type_names

CATEGORY = "TOEFL ITP"
BLOCK_LABELS = ("Pembahasan:", "Transkrip Audio:", "Cara cepat:")
AUDIO_GUIDE = ("Audio ada di folder audio. Unggah file yang namanya tertulis di baris File audio pada setiap soal. "
               "Di Part B dan C, percakapan atau kuliah hanya ada di audio soal pertama tiap kelompok.")


def _new_document():
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)
    normal.paragraph_format.line_spacing = 1.5
    normal.paragraph_format.space_after = Pt(5)
    # Tebal lewat style, supaya pembaca Word tetap melihat "Soal N" dan "Jawaban: X" sebagai teks polos.
    for name in ("SiaduQuestion", "SiaduAnswer"):
        style = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        style.base_style = normal
        style.font.bold = True
    section = doc.sections[0]
    section.page_width, section.page_height = Twips(11906), Twips(16838)
    section.top_margin = section.bottom_margin = section.left_margin = section.right_margin = Twips(1000)
    return doc


def _add(doc, text="", bold=False, keep_next=False, style=None):
    paragraph = doc.add_paragraph(style=style)
    paragraph.paragraph_format.keep_with_next = keep_next
    if text:
        run = paragraph.add_run(text)
        if bold:
            run.bold = True
    return paragraph


def chapter(item, names):
    return " - ".join(filter(None, [PART_LABELS.get(item.part), type_label(names, item.section, item.part, item.family_id)]))


def _add_item(doc, index, item, names):
    _add(doc, f"Soal {index}", keep_next=True, style="SiaduQuestion")
    _add(doc, f"Category: {CATEGORY}", bold=True, keep_next=True)
    _add(doc, f"Lesson: {SECTIONS[item.section]['label']}", bold=True, keep_next=True)
    _add(doc, f"Chapter: {chapter(item, names)}", bold=True, keep_next=True)
    if item.meta.get("audio_file"):
        _add(doc, f"File audio: {item.meta['audio_file']}", bold=True, keep_next=True)
    _add(doc, "Bentuk Soal: Option New", keep_next=True)
    _add(doc, f"Tingkat Kesulitan: {item.level}", keep_next=True)
    for line in item.stem.splitlines():
        if line.strip():
            _add(doc, line)
    for letter, option in zip(LETTERS, item.options):
        _add(doc, f"{letter}. {option}")
    _add(doc, f"Jawaban: {item.key}", keep_next=True, style="SiaduAnswer")
    for line in item.pembahasan.split("\n")[1:]:
        _add(doc, line, bold=line in BLOCK_LABELS, keep_next=line in BLOCK_LABELS)


def write_section_word(path, items, section, paket, seed, label=None):
    doc = _new_document()
    names = type_names()
    _add(doc, f"TOEFL ITP - {label or f'Paket {paket}'} - {SECTIONS[section]['label']}", bold=True)
    _add(doc, f"Format input Word SiAdu - {len(items)} soal - seed {seed}")
    if any(it.meta.get("audio_file") for it in items):
        _add(doc, AUDIO_GUIDE)
    for it in items:
        _add_item(doc, it.number, it, names)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
