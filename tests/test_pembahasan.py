import json
import random

import pytest

from toefl_gen.cli import main
from toefl_gen.common import (GenerationError, cache_only, cached_generate, format_pembahasan, option_problems,
                              place_key, reason_clause)
from toefl_gen.families import load_library
from toefl_gen.listening import load_types as load_listening_types
from toefl_gen.models import LETTERS, Item
from toefl_gen.qc import ERROR, check_item
from toefl_gen.reading import load_types as load_reading_types

REASONS = {"A": "alasan a", "C": "alasan c.", "D": "alasan d"}
LONG_REASON = "opsi ini memakai kata yang sama dengan teks tetapi maknanya berbeda"
LONG_EXPLANATION = " ".join(["kata"] * 20)


def explanation_of(pembahasan):
    return pembahasan.split("Pembahasan:\n\n", 1)[1].split("\n\n", 1)[0]


def test_format_sesuai_permintaan_tim_akademik():
    assert format_pembahasan("B", "Soal ini membahas X.", REASONS, "Cari Y.") == (
        "Jawaban: B\n"
        "Pembahasan:\n"
        "\n"
        "Soal ini membahas X.\n"
        "\n"
        "* Opsi A keliru karena alasan a.\n"
        "* Opsi C keliru karena alasan c.\n"
        "* Opsi D keliru karena alasan d.\n"
        "\n"
        "Cara cepat:\n"
        "Cari Y."
    )


def test_transkrip_berada_sebelum_penjelasan():
    text = format_pembahasan("B", "Penjelasan.", REASONS, "Cari Y.", transcript=["MAN: Hi.", "NARRATOR: What?"])
    assert text.startswith("Jawaban: B\nPembahasan:\n\nTranskrip Audio:\nMAN: Hi.\nNARRATOR: What?\n\nPenjelasan.\n\n* Opsi A")


def test_semua_frame_mengikuti_format():
    for fam in load_library().values():
        for fr in fam.frames:
            values = fr.variants()[0]
            it = fr.build(values, fr.feasible_keys(values)[0], random.Random(1))
            assert [m for lvl, m in check_item(it) if lvl == ERROR] == [], fr.key
            explanation = explanation_of(it.pembahasan)
            assert explanation.startswith(f"Soal ini membahas {fam.konsep}.")
            assert ": " not in explanation, fr.key
            assert it.pembahasan.endswith(fam.cara_cepat)


def test_written_expression_menyebut_bagian_keliru_dan_bentuk_benar():
    fam = load_library()["SVA"]
    fr = next(f for f in fam.frames if f.id == "w3")
    values = fr.variants()[0]
    it = fr.build(values, fr.feasible_keys(values)[0], random.Random(1))
    assert 'Bagian yang keliru adalah "are"' in it.pembahasan
    assert 'bentuk yang benar adalah "is"' in it.pembahasan
    assert sum(line.startswith("* Opsi ") for line in it.pembahasan.splitlines()) == 3


def _described_types():
    listening = load_listening_types()
    yield from load_reading_types()
    yield from listening["part_a"]
    yield from ({"id": k, **v} for k, v in listening["group_types"].items())


def test_setiap_tipe_soal_punya_konsep_dan_cara_cepat():
    for t in _described_types():
        assert t["konsep"].strip(), t["id"]
        assert t["cara_cepat"].strip(), t["id"]


def test_cara_cepat_tanpa_titik_dua():
    texts = [t["cara_cepat"] for t in _described_types()] + [f.cara_cepat for f in load_library().values()]
    assert [t for t in texts if ":" in t] == []


def test_semua_tipe_part_b_c_punya_penjelasan():
    types = load_listening_types()
    used = {t["id"] for key in ("part_b", "part_c") for t in types[key]}
    assert used == set(types["group_types"])


def _question(**changes):
    q = {"options": {L: f"option {L}" for L in LETTERS}, "key": "A", "penjelasan": LONG_EXPLANATION,
         "alasan_salah": {"A": "-", "B": LONG_REASON, "C": LONG_REASON, "D": LONG_REASON}}
    q.update(changes)
    return q


def test_penjelasan_dan_alasan_yang_dangkal_ditolak():
    assert option_problems(_question()) == []
    short = _question(alasan_salah={"A": "-", "B": "biaya pengiriman tidak pernah disebut", "C": LONG_REASON, "D": LONG_REASON})
    assert any("terlalu singkat" in p for p in option_problems(short))
    assert any("penjelasan terlalu singkat" in p for p in option_problems(_question(penjelasan="Terlalu pendek.")))
    assert any("titik dua" in p for p in option_problems(_question(penjelasan=LONG_EXPLANATION + ": lanjutan")))
    assert option_problems(_question(penjelasan=LONG_EXPLANATION + " pukul 10:30")) == []


@pytest.mark.parametrize("text", ["Opsi B menyatakan hal itu dengan kata lain.", "Jadi jawaban C paling tepat.",
                                  "Hal ini membuat A adalah jawaban terbaik."])
def test_penyebutan_huruf_opsi_ditolak(text):
    assert any("huruf opsi" in p for p in option_problems(_question(penjelasan=f"{LONG_EXPLANATION} {text}")))
    reasons = {"A": "-", "B": f"{LONG_REASON}, berbeda dengan {text}", "C": LONG_REASON, "D": LONG_REASON}
    assert any("huruf opsi" in p for p in option_problems(_question(alasan_salah=reasons)))


def _moved_question(explanation, reason_b=LONG_REASON):
    return {"options": {L: f"isi {L}" for L in LETTERS}, "key": "B", "penjelasan": explanation,
            "alasan_salah": {"A": LONG_REASON, "B": "-", "C": reason_b, "D": LONG_REASON}}


def test_huruf_di_penjelasan_mengikuti_posisi_akhir_opsi():
    # Kunci B pindah ke D, sehingga A tetap A, C menjadi B, dan D menjadi C.
    options, reasons, explanation = place_key(_moved_question("Opsi B benar, sedangkan opsi C dan D keliru."), "D")
    assert options == ["isi A", "isi C", "isi D", "isi B"]
    assert explanation == "Opsi D benar, sedangkan opsi B dan C keliru."
    assert sorted(reasons) == ["A", "B", "C"]


def test_huruf_di_alasan_ikut_disesuaikan():
    _, reasons, _ = place_key(_moved_question("Isi penjelasan.", "berbeda dengan opsi B yang benar"), "D")
    assert reasons["B"] == "berbeda dengan opsi D yang benar"


@pytest.mark.parametrize("text", ["Ungkapan 'A piece of cake' berarti mudah.", "Teks menyebut vitamin C dan Part B.",
                                  "Disebut A adalah sebuah contoh."])
def test_huruf_bukan_rujukan_opsi_tidak_berubah(text):
    assert place_key(_moved_question(text), "D")[2] == text


@pytest.mark.parametrize("text, expected", [("Judul B merangkum isi teks.", "Judul D merangkum isi teks."),
                                            ("Jadi B adalah jawaban paling tepat.", "Jadi D adalah jawaban paling tepat.")])
def test_bentuk_rujukan_lain_ikut_disesuaikan(text, expected):
    assert place_key(_moved_question(text), "D")[2] == expected


@pytest.mark.parametrize("raw, clause", [
    ("Opsi B keliru karena terlalu luas.", "terlalu luas"),
    ("Salah karena Teks menyebut hal lain.", "teks menyebut hal lain"),
    ("karena tidak disebut", "tidak disebut"),
    ("terlalu sempit", "terlalu sempit"),
])
def test_awalan_alasan_dibersihkan(raw, clause):
    assert reason_clause(raw) == clause


def _item(pembahasan, key="B"):
    return Item(section="reading", part="reading", family_id="detail", topic="t", level="Sedang", stem="Soal?",
                options=["a", "b", "c", "d"], key=key, pembahasan=pembahasan, frame_id="f", fingerprint="fp", number=1)


def test_qc_menolak_format_lama():
    good = format_pembahasan("B", "Penjelasan.", REASONS, "Cari Y.")
    assert check_item(_item(good)) == []
    errors = [m for _, m in check_item(_item('Jawaban: B\nPembahasan:\nTipe soal: Detail. Isi.\nBukti: "x"'))]
    assert any("kunci" in m for m in errors)
    assert any("belum menjelaskan opsi A, C, D" in m for m in errors)
    assert any("Cara cepat" in m for m in errors)
    assert any("label lama" in m for m in errors)


def _write_cache(path, data):
    path.write_text(json.dumps({"prompt_hash": "hash-lama", "data": data}), encoding="utf-8")


def test_cache_only_memakai_cache_walau_prompt_berubah(tmp_path):
    path = tmp_path / "c.json"
    _write_cache(path, {"isi": 1})
    assert cached_generate(path, "sistem", "prompt baru", {}, lambda d: [], cache_only, print, "x") == {"isi": 1}


def test_tanpa_cache_only_prompt_baru_memanggil_klien(tmp_path):
    path = tmp_path / "c.json"
    _write_cache(path, {"isi": 1})

    class Client:
        def generate_json(self, system, prompt, schema):
            return {"isi": 2}

    assert cached_generate(path, "sistem", "prompt baru", {}, lambda d: [], Client, lambda *_: None, "x") == {"isi": 2}


def test_cache_only_berhenti_kalau_cache_tidak_ada(tmp_path):
    with pytest.raises(GenerationError, match="--cache-only"):
        cached_generate(tmp_path / "tidak-ada.json", "s", "p", {}, lambda d: [], cache_only, lambda *_: None, "x")


def test_perintah_cli_cache_only_tidak_memanggil_api(tmp_path):
    args = ["generate", "--seed", "1", "--paket", "1", "--sections", "reading", "--cache-only", "--no-register",
            "--out", str(tmp_path)]
    with pytest.raises(SystemExit, match="--cache-only"):
        main(args)
