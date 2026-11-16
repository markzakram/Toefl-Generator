import re
from collections import Counter

import openpyxl

from toefl_gen.blueprint import key_bounds, load_blueprint
from toefl_gen.exporter import META_HEADERS, write_section_workbook
from toefl_gen.listening import (copy_problems, generate_listening, load_types, plan_listening, validate_a)
from toefl_gen.qc import ERROR, WARN, check_batch
from toefl_gen.tts import render_items

BP = load_blueprint()
SPEC = BP["sections"]["listening"]
A_LINE = re.compile(r"^(\d+)\. tipe=(\w+), level=\w+, pembicara pertama=(MAN|WOMAN), pembicara kedua=(MAN|WOMAN), situasi=(.+)$", re.M)
G_LINE = re.compile(r"^(\d+)\. tipe=(\w+), level=\w+$", re.M)
LINE_B = "I think we should finish the outline tonight so that we can practice the whole talk tomorrow"


def opts(n):
    return {L: f"Choice {L} number {n} statement" for L in "ABCD"}


EXPLANATION = ("Pembicara kedua menyampaikan secara tidak langsung bahwa dirinya masih sibuk, sehingga ajakan "
               "pembicara pertama tidak bisa dipenuhi pada malam ini.")


def reasons():
    return {
        "A": "Salah karena pembicara kedua tidak membahas hal ini sama sekali dalam jawabannya.",
        "B": "-",
        "C": "karena hal ini tidak disebut, sebab percakapan hanya menyangkut tugas yang belum selesai",
        "D": "pernyataan ini bertentangan dengan ucapan pembicara yang masih memiliki tugas",
    }


def fake_response(prompt, tag=""):
    if "Part A" in prompt:
        items = []
        for n, t, first, second, setting in A_LINE.findall(prompt):
            items.append({
                "slot": int(n), "type": t, "first_speaker": first,
                "first_line": f"Are you coming to the {setting} with us later?",
                "second_line": f"Well, I still have a paper due tomorrow morning {tag}.",
                "question": f"What does the {second.lower()} mean?",
                "options": opts(n), "key": "B", "penjelasan": EXPLANATION, "alasan_salah": reasons(),
            })
        return {"items": items}
    part = re.search(r"Listening Part ([BC])", prompt).group(1)
    if part == "B":
        lines = [{"speaker": "MAN" if i % 2 == 0 else "WOMAN", "text": f"{LINE_B} {i}."} for i in range(10)]
    else:
        lines = [{"speaker": "PROFESSOR", "text": " ".join([LINE_B] * 3) + f" {i}."} for i in range(5)]
    questions = [{
        "slot": int(n), "type": t, "question": f"What is true about point {n}?", "options": opts(n), "key": "B",
        "evidence": "finish the outline tonight", "penjelasan": EXPLANATION, "alasan_salah": reasons(),
    } for n, t in G_LINE.findall(prompt)]
    return {"lines": lines, "questions": questions}


class FakeClient:
    def __init__(self):
        self.calls = 0

    def generate_json(self, system, prompt, schema):
        self.calls += 1
        return fake_response(prompt, tag=str(self.calls))


class FakeEngine:
    name = "fake"
    bytes_per_second = 1000

    async def render(self, script, roles):
        return b"x" * 1000 * len(script)


def make_batch(tmp_path, seed=1, paket=2):
    plan = plan_listening(BP, seed, paket)
    fake = FakeClient()
    batch = generate_listening(plan, BP, tmp_path / "cache", lambda: fake, log=lambda *_: None)
    return plan, batch, fake


def test_plan_is_parallel_and_balanced():
    plan = plan_listening(BP, 3, 5)
    shape = lambda e: ([(s["type"], s["level"]) for s in e["A"]],
                       [[(s["type"], s["level"]) for s in g["slots"]] for part in "BC" for g in e[part]])
    assert all(shape(e) == shape(plan[0]) for e in plan)
    topics = [g["topic"]["id"] for e in plan for part in "BC" for g in e[part]]
    assert len(topics) == len(set(topics))
    lo, hi = key_bounds(50, BP["key_rules"])
    for e in plan:
        keys = [s["key"] for s in e["A"]] + [s["key"] for part in "BC" for g in e[part] for s in g["slots"]]
        assert len(keys) == 50 and all(lo <= n <= hi for n in Counter(keys).values())
        assert Counter(s["type"] for s in e["A"]) == {t["id"]: t["per_paket"] for t in load_types()["part_a"]}
        assert [s["slot"] for s in e["A"]] == list(range(1, 31))
        assert [s["slot"] for g in e["C"] for s in g["slots"]] == list(range(39, 51))


def test_generate_with_fake_client_passes_qc(tmp_path):
    plan, batch, fake = make_batch(tmp_path)
    assert fake.calls == 2 * (3 + 2 + 3)
    issues = check_batch({"listening": batch}, BP)
    assert [m for lvl, m in issues if lvl == ERROR] == []
    assert any("audio belum dibuat" in m for lvl, m in issues if lvl == WARN)
    for items, entry in zip(batch, plan):
        assert [it.number for it in items] == list(range(1, 51))
        targets = [s["key"] for s in entry["A"]] + [s["key"] for part in "BC" for g in entry[part] for s in g["slots"]]
        assert [it.key for it in items] == targets
        assert all(it.options["ABCD".index(it.key)].startswith("Choice B") for it in items)
        assert all(it.pembahasan.startswith(f"Jawaban: {it.key}\nPembahasan:\n\nTranskrip Audio:\n") for it in items)
        assert all("NARRATOR: " in it.pembahasan and "\n\nCara cepat:\n" in it.pembahasan for it in items)
        assert 'ucapan "finish the outline tonight".' in items[31].pembahasan
        a = items[0]
        assert len(a.meta["audio_script"]) == 3 and a.meta["audio_script"][-1][0] == "NARRATOR"
        b_first, b_second = items[30], items[31]
        assert b_first.meta["audio_script"][0][1].startswith("Questions 31 through 34")
        assert len(b_first.meta["audio_script"]) == 12 and len(b_second.meta["audio_script"]) == 1
        c_first = items[38]
        assert re.match(r"Questions 39 through 42\. Listen to part of a lecture in an? [\w ]+ class\.", c_first.meta["audio_script"][0][1])


def test_audio_mode_every_repeats_conversation(tmp_path):
    bp = load_blueprint()
    bp["sections"]["listening"]["audio_mode"] = "every"
    plan = plan_listening(bp, 2, 1)
    batch = generate_listening(plan, bp, tmp_path, lambda: FakeClient(), log=lambda *_: None)
    assert all(len(it.meta["audio_script"]) == 12 for it in batch[0] if it.part == "B")


def test_copied_option_is_rejected():
    plan = plan_listening(BP, 4, 1)
    chunk = plan[0]["A"][:10]
    prompt = "Part A\n" + "\n".join(
        f"{s['slot']}. tipe={s['type']}, level={s['level']}, pembicara pertama={s['first']}, "
        f"pembicara kedua={'WOMAN' if s['first'] == 'MAN' else 'MAN'}, situasi={s['setting']}" for s in chunk)
    data = fake_response(prompt)
    meta = {t["id"]: t for t in load_types()["part_a"]}
    assert validate_a(data, chunk, meta) == []
    data["items"][0]["options"]["C"] = "I still have a paper due tomorrow morning."
    assert any("menyalin" in p for p in validate_a(data, chunk, meta))
    q = {"options": {"A": "It is red or blue.", "B": "x y z", "C": "a b c", "D": "d e f"}, "key": "A"}
    assert any("X or Y" in p for p in copy_problems(q, ["nothing"], 3))


def test_first_speakers_are_balanced():
    for e in plan_listening(BP, 5, 3):
        assert Counter(s["first"] for s in e["A"]) == {"MAN": 15, "WOMAN": 15}


def test_part_b_uses_different_names_and_part_c_different_openings():
    e = plan_listening(BP, 5, 1)[0]
    names = [g["names"]["WOMAN"] for g in e["B"]]
    assert len(set(names)) == len(names)
    openings = [g["opening"] for g in e["C"]]
    assert len(set(openings)) == len(openings)


def test_used_phrases_are_sent_to_later_chunks(tmp_path):
    plan = plan_listening(BP, 6, 1)
    prompts = []

    class Recording(FakeClient):
        def generate_json(self, system, prompt, schema):
            prompts.append(prompt)
            return super().generate_json(system, prompt, schema)

    fake = Recording()
    generate_listening(plan, BP, tmp_path, lambda: fake, log=lambda *_: None)
    assert "sudah dipakai" not in prompts[0]
    assert "sudah dipakai" in prompts[1]
    assert "paper due tomorrow morning 1" in prompts[1]


def test_key_longest_too_often_is_rejected():
    plan = plan_listening(BP, 4, 1)
    chunk = plan[0]["A"][:10]
    prompt = "Part A\n" + "\n".join(
        f"{s['slot']}. tipe={s['type']}, level={s['level']}, pembicara pertama={s['first']}, "
        f"pembicara kedua={'WOMAN' if s['first'] == 'MAN' else 'MAN'}, situasi={s['setting']}" for s in chunk)
    data = fake_response(prompt)
    meta = {t["id"]: t for t in load_types()["part_a"]}
    for q in data["items"][:4]:
        q["options"]["B"] += " with many extra words"
    assert validate_a(data, chunk, meta) == []
    data["items"][4]["options"]["B"] += " with many extra words"
    assert any("paling panjang" in p for p in validate_a(data, chunk, meta))


def test_render_audio_and_reuse(tmp_path):
    _, batch, _ = make_batch(tmp_path, paket=1)
    items = batch[0]
    assert render_items(items, tmp_path / "audio", FakeEngine(), log=lambda *_: None) == 50
    assert render_items(items, tmp_path / "audio", FakeEngine(), log=lambda *_: None) == 0
    issues = check_batch({"listening": batch}, BP)
    assert [m for lvl, m in issues if lvl in (ERROR, WARN)] == []
    assert items[0].meta["audio_seconds"] == 3.0


def test_excel_has_audio_column(tmp_path):
    _, batch, _ = make_batch(tmp_path, paket=1)
    path = tmp_path / "P1_listening.xlsx"
    write_section_workbook(path, batch[0], "seed-1", 1)
    meta = list(openpyxl.load_workbook(path)["META"].iter_rows(values_only=True))
    assert list(meta[0]) == META_HEADERS
    assert meta[1][META_HEADERS.index("file_audio")] == "P1_L_A_001.mp3"
