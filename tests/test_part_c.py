import json
import re
import zipfile
from collections import Counter

import pytest
from docx import Document

from tests.test_listening import EXPLANATION, FakeEngine, opts, reasons
from toefl_gen.blueprint import key_bounds, load_blueprint
from toefl_gen.cli import _avoided_part_c, main
from toefl_gen.listening import ListeningError, generate_part_c_set, load_topics, plan_listening, plan_part_c_set
from toefl_gen.qc import ERROR, check_part_c_set
from toefl_gen.review_html import collect
from toefl_gen.tts import render_items

BP = load_blueprint()
LINE = "Today we will look at how this process began and why it still matters to people who study the field today"


class FakeClient:
    usage = {"calls": 0}

    def __init__(self):
        self.calls = 0

    def cost_usd(self):
        return 0

    def generate_json(self, system, prompt, schema):
        self.calls += 1
        lines = [{"speaker": "PROFESSOR", "text": " ".join([LINE] * 2) + f" {i}."} for i in range(5)]
        questions = [{
            "slot": int(n), "type": t, "question": f"What is true about point {n}?", "options": opts(n), "key": "B",
            "evidence": "how this process began", "penjelasan": EXPLANATION, "alasan_salah": reasons(),
        } for n, t in re.findall(r"^(\d+)\. tipe=(\w+), level=\w+$", prompt, re.M)]
        return {"lines": lines, "questions": questions}


def test_rencana_120_soal_seimbang_dan_bernomor_dari_1():
    groups = plan_part_c_set(BP, 1, 30)
    slots = [s for g in groups for s in g["slots"]]
    assert len(groups) == 30 and [s["slot"] for s in slots] == list(range(1, 121))
    assert all(len(g["slots"]) == 4 for g in groups)
    assert len({g["topic"]["id"] for g in groups}) == 30
    assert Counter(s["level"] for s in slots) == {"Mudah": 36, "Sedang": 60, "Sulit": 24}
    lo, hi = key_bounds(120, BP["key_rules"])
    assert all(lo <= n <= hi for n in Counter(s["key"] for s in slots).values())
    assert [s["type"] for s in groups[0]["slots"]] == ["main_topic", "detail", "detail", "inference"]


def test_rencana_sama_untuk_seed_yang_sama():
    ids = lambda seed: [g["topic"]["id"] for g in plan_part_c_set(BP, seed, 5)]
    assert ids(7) == ids(7) and ids(7) != ids(8)


def test_topik_yang_sudah_terpakai_dihindari():
    first = plan_part_c_set(BP, 1, 30)
    used = frozenset(f"LISC:{g['topic']['id']}#1" for g in first)
    again = plan_part_c_set(BP, 2, 10, blocked=used)
    assert not {g["topic"]["id"] for g in again} & {g["topic"]["id"] for g in first}


def test_topik_yang_kurang_ditolak_dengan_jelas():
    too_many = len(load_topics()["part_c"]) + 1
    with pytest.raises(ListeningError, match="Topik Part C tinggal"):
        plan_part_c_set(BP, 1, too_many)


def test_hindari_mengambil_topik_part_c_dari_batch_lain():
    avoided = _avoided_part_c("2028:3", BP, frozenset())
    expected = {g["topic"]["id"] for e in plan_listening(BP, 2028, 3) for g in e["C"]}
    assert len(expected) == 9
    assert avoided == {f"LISC:{t}#1" for t in expected}
    assert not {g["topic"]["id"] for g in plan_part_c_set(BP, 2029, 30, blocked=avoided)} & expected


@pytest.fixture
def made(tmp_path):
    groups = plan_part_c_set(BP, 3, 3)
    fake = FakeClient()
    items = generate_part_c_set(groups, BP, tmp_path / "cache", lambda: fake, log=lambda *_: None)
    return groups, items, fake, tmp_path


def test_generate_menghasilkan_soal_part_c_yang_lolos_qc(made):
    groups, items, fake, tmp_path = made
    assert fake.calls == 3
    render_items(items, tmp_path / "audio", FakeEngine(), log=lambda *_: None)
    assert [m for lvl, m in check_part_c_set(items, BP) if lvl == ERROR] == []
    assert [it.number for it in items] == list(range(1, 13))
    assert all(it.part == "C" and it.meta["audio_file"].startswith("P1_L_C_") for it in items)
    assert items[0].meta["audio_script"][0][1].startswith("Questions 1 through 4.")
    assert items[4].meta["audio_script"][0][1].startswith("Questions 5 through 8.")
    assert len(items[1].meta["audio_script"]) == 1
    assert [it.meta["group"] for it in items[:5]] == [1, 1, 1, 1, 2]


def test_qc_menolak_topik_yang_sudah_dipakai_dan_nomor_kacau(made):
    _, items, _, tmp_path = made
    render_items(items, tmp_path / "audio", FakeEngine(), log=lambda *_: None)
    blocked = {f"LISC:{items[0].frame_id}#1"}
    assert any("sudah pernah dipakai" in m for lvl, m in check_part_c_set(items, BP, blocked) if lvl == ERROR)
    items[0].number = 99
    assert any("tidak berurutan" in m for lvl, m in check_part_c_set(items, BP) if lvl == ERROR)


def test_cache_dipakai_ulang(made):
    groups, _, _, tmp_path = made

    def no_client():
        raise AssertionError("klien tidak boleh dipanggil bila cache lengkap")

    assert len(generate_part_c_set(groups, BP, tmp_path / "cache", no_client, log=lambda *_: None)) == 12


def test_perintah_cli_menyusun_paket_lengkap(tmp_path, monkeypatch):
    monkeypatch.setattr("toefl_gen.cli.ClaudeClient", lambda *a: FakeClient())
    monkeypatch.setattr("toefl_gen.cli.EdgeTTS", FakeEngine)
    out = tmp_path / "hasil"
    assert main(["part-c", "--seed", "5", "--soal", "16", "--no-register", "--out", str(out)]) == 0
    batch = out / "part-c-5"
    assert (batch / "P1" / "P1_listening_siadu.docx").exists() and (batch / "P1" / "P1_listening.xlsx").exists()
    with zipfile.ZipFile(batch / "P1_paket_input.zip") as archive:
        assert sum(n.endswith(".mp3") for n in archive.namelist()) == 16
    archive = json.loads((batch / "batch.json").read_text(encoding="utf-8"))
    assert archive["info"]["batch"] == "part-c-5" and len(archive["sections"]["listening"][0]) == 16
    data, audio, files, missing = collect(batch, 1)
    assert missing == [] and len(audio) == 16 and "P1_listening_siadu.docx" in files
    assert [s["id"] for s in data["sections"]] == ["listening"]
    assert data["sections"][0]["minutes"] == 11
    assert data["title"] == data["heading"] == "Latihan Part C, 16 soal"
    word = (batch / "P1" / "P1_listening_siadu.docx")
    assert Document(word).paragraphs[0].text.startswith("TOEFL ITP - Latihan Part C, 16 soal")


def test_perintah_cli_menolak_jumlah_bukan_kelipatan_empat(tmp_path):
    with pytest.raises(SystemExit, match="kelipatan 4"):
        main(["part-c", "--seed", "5", "--soal", "10", "--out", str(tmp_path)])


def test_perintah_cli_cache_only_tidak_memanggil_api(tmp_path):
    with pytest.raises(SystemExit, match="--cache-only"):
        main(["part-c", "--seed", "5", "--soal", "4", "--cache-only", "--no-register", "--out", str(tmp_path)])
