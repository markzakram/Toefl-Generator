import base64
import json
import re

import pytest

from toefl_gen.cli import main
from toefl_gen.review_html import build_review_html, collect

AUDIO_BYTES = b"\xff\xfb\x90\x00fake-mp3"
WORD_BYTES = b"PK\x03\x04fake-docx"


def _item(section, part, number, stem, **meta):
    return {
        "section": section, "part": part, "family_id": "x", "topic": "Topik", "level": "Sedang", "stem": stem,
        "options": ["satu", "dua", "tiga", "empat"], "key": "B", "pembahasan": "Karena dua.", "frame_id": "",
        "fingerprint": f"F{section}{number}", "number": number, "meta": meta,
    }


def _listening(number, audio_file):
    script = [["MAN", "Hello."], ["NARRATOR", "What?"]] if number == 1 else [["NARRATOR", "What?"]]
    return _item("listening", "A", number, "Listen to the audio carefully.", transcript="M: Hello.", question="What?",
                 audio_file=audio_file, audio_path="C:/rahasia/audio.mp3", group=None, audio_script=script, audio_seconds=10.0)


def _reading(number, question):
    stem = f"PASSAGE 1: Judul Teks\n\nParagraf satu.\n\nParagraf dua.\n\n{question}"
    return _item("reading", "reading", number, stem, passage=1, words=250, field="Sains", title="Judul Teks")


@pytest.fixture
def batch_dir(tmp_path):
    audio = tmp_path / "P1" / "audio"
    audio.mkdir(parents=True)
    (audio / "L001.mp3").write_bytes(AUDIO_BYTES)
    (tmp_path / "P1" / "P1_listening_siadu.docx").write_bytes(WORD_BYTES)
    (tmp_path / "P1" / "P1_listening.xlsx").write_bytes(b"excel")
    archive = {
        "info": {"batch": "seed-7", "seed": 7, "paket": 1, "versi_pustaka": "abc", "model": "m", "dibuat": "2026-11-04"},
        "sections": {
            "reading": [[_reading(1, "What is the main idea?"), _reading(2, "The word </script> means?")]],
            "structure": [[_item("structure", "structure", 1, "The cat ___ here.")]],
            "listening": [[_listening(1, "L001.mp3"), _listening(2, "L002.mp3")]],
        },
    }
    (tmp_path / "batch.json").write_text(json.dumps(archive), encoding="utf-8")
    return tmp_path


def _embedded(html, element_id):
    match = re.search(rf'<script id="{element_id}" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(match.group(1))


def test_section_mengikuti_urutan_tes(batch_dir):
    data, _, _, _ = collect(batch_dir, 1)
    assert [s["id"] for s in data["sections"]] == ["listening", "structure", "reading"]
    assert [s["count"] for s in data["sections"]] == [2, 1, 2]
    assert set(data["baseline"]) == {"listening", "structure", "reading"}


def test_nama_tipe_soal_mengikuti_sectionnya(tmp_path):
    reading = _reading(1, "It can be inferred that?")
    reading["family_id"] = "inference"
    part_c = _listening(1, "L001.mp3")
    part_c.update(part="C", family_id="inference")
    archive = {"info": {"batch": "seed-7", "seed": 7}, "sections": {"reading": [[reading]], "listening": [[part_c]]}}
    (tmp_path / "batch.json").write_text(json.dumps(archive), encoding="utf-8")
    data, _, _, _ = collect(tmp_path, 1)
    types = {it["section"]: it["type"] for it in data["items"]}
    assert types == {"reading": "Inference", "listening": "Inferensi/tujuan pembicara"}


def test_teks_reading_dipisah_dari_pertanyaan(batch_dir):
    data, _, _, _ = collect(batch_dir, 1)
    assert data["passages"]["1"]["heading"] == "PASSAGE 1: Judul Teks"
    assert data["passages"]["1"]["body"] == "Paragraf satu.\n\nParagraf dua."
    first = next(it for it in data["items"] if it["id"] == "reading-1")
    assert first["stem"] == "What is the main idea?"
    assert first["passage"] == "1"


def test_audio_yang_hilang_dilaporkan(batch_dir):
    data, audio, _, missing = collect(batch_dir, 1)
    assert missing == ["L002.mp3"]
    assert base64.b64decode(audio["L001.mp3"]) == AUDIO_BYTES
    assert data["audioBytes"] == len(AUDIO_BYTES)


def test_word_dan_excel_ikut_tertanam(batch_dir):
    data, _, files, _ = collect(batch_dir, 1)
    assert [d["label"] for d in data["docs"]] == ["Listening Comprehension", "Structure and Written Expression", "Reading Comprehension"]
    listening = data["docs"][0]
    assert listening["word"] == {"name": "P1_listening_siadu.docx", "size": len(WORD_BYTES)}
    assert base64.b64decode(files["P1_listening_siadu.docx"]) == WORD_BYTES
    assert data["docs"][1]["word"] is None and data["docs"][1]["excel"] is None
    assert "CARA_INPUT" not in data["guide"] and "File audio" in data["guide"]


def test_audio_menandai_isi_lengkap_atau_pertanyaan_saja(batch_dir):
    data, _, _, _ = collect(batch_dir, 1)
    rows = {it["no"]: it for it in data["items"] if it["section"] == "listening"}
    assert rows[1]["audioFull"] is True and rows[1]["audioSeconds"] == 10.0
    assert rows[2]["audioFull"] is False


def test_path_lokal_tidak_ikut_tertanam(batch_dir):
    path, _, _ = build_review_html(batch_dir)
    assert "rahasia" not in path.read_text(encoding="utf-8")


def test_placeholder_terganti_dan_json_terbaca(batch_dir):
    path, size_mb, _ = build_review_html(batch_dir)
    html = path.read_text(encoding="utf-8")
    assert path == batch_dir / "QC_P1.html"
    assert size_mb > 0
    for placeholder in ("__TITLE__", "__DATA__", "__AUDIO__", "__FILES__"):
        assert placeholder not in html
    assert "<title>Tryout TOEFL Paket 1</title>" in html
    assert _embedded(html, "qc-data")["batch"] == "seed-7"
    assert base64.b64decode(_embedded(html, "qc-audio")["L001.mp3"]) == AUDIO_BYTES
    assert base64.b64decode(_embedded(html, "qc-files")["P1_listening_siadu.docx"]) == WORD_BYTES


def test_isi_soal_tidak_bisa_menutup_tag_script(batch_dir):
    html = build_review_html(batch_dir)[0].read_text(encoding="utf-8")
    assert html.count("</script>") == 4  # qc-data, qc-audio, qc-files, kode halaman
    data = _embedded(html, "qc-data")
    assert next(it for it in data["items"] if it["id"] == "reading-2")["stem"] == "The word </script> means?"


def test_paket_di_luar_batas_ditolak(batch_dir):
    with pytest.raises(ValueError, match="Paket 2"):
        collect(batch_dir, 2)


def test_perintah_cli(batch_dir, tmp_path, capsys):
    out = tmp_path / "hasil" / "qc.html"
    assert main(["review-html", "--batch", str(batch_dir), "--out", str(out)]) == 0
    assert out.exists()
    printed = capsys.readouterr().out
    assert "File QC:" in printed
    assert "L002.mp3" in printed


def test_perintah_cli_batch_tidak_ada(tmp_path):
    with pytest.raises(SystemExit, match="Gagal membuat file QC"):
        main(["review-html", "--batch", str(tmp_path / "tidak-ada")])
