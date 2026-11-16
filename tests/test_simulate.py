import re

import openpyxl

from tests.test_listening import FakeClient as ListeningFake
from tests.test_reading import FakeClient as ReadingFake
from toefl_gen.blueprint import load_blueprint
from toefl_gen.exporter import META_HEADERS, write_section_workbook, write_summary
from toefl_gen.families import load_library
from toefl_gen.listening import generate_listening, plan_listening
from toefl_gen.models import Item
from toefl_gen.planner import plan_structure_section
from toefl_gen.reading import generate_reading, plan_reading
from toefl_gen.simulate import PERSONAS, blind_prompt, chunks, flags_for, simulate_section, summarize

BP = load_blueprint()


def all_sections(tmp_path):
    return {
        "structure": plan_structure_section(load_library(), BP, 1, 1),
        "reading": generate_reading(plan_reading(BP, 1, 1), BP, tmp_path / "r", lambda: ReadingFake(), log=lambda *_: None),
        "listening": generate_listening(plan_listening(BP, 1, 1), BP, tmp_path / "l", lambda: ListeningFake(), log=lambda *_: None),
    }


def test_prompts_are_blind(tmp_path):
    for section, batch in all_sections(tmp_path).items():
        for group in chunks(section, batch[0]):
            for persona in PERSONAS:
                prompt = blind_prompt(section, group, persona)
                assert "Jawaban" not in prompt and "Pembahasan" not in prompt
                assert not re.search(r"\b(Mudah|Sedang|Sulit)\b", prompt)
                for it in group:
                    assert it.pembahasan not in prompt
                    for option in it.options:
                        assert option in prompt
                    if persona == "awam" and section == "listening":
                        assert all(line not in prompt for line in it.meta["transcript_lines"])
                    if persona == "awam" and section == "reading":
                        assert it.meta["title"] not in prompt
                    if persona == "awam" and section == "structure":
                        assert it.stem not in prompt


def item(level, key="B"):
    return Item(section="structure", part="structure", family_id="X", topic="t", level=level, stem="s ___",
                options=["a", "b", "c", "d"], key=key, pembahasan=f"Jawaban: {key}\n", frame_id="f", fingerprint="fp", number=1)


def answers(awam, menengah, mahir, awam_conf="rendah"):
    return {"awam": {"answer": awam, "confidence": awam_conf, "reason": "opsi paling panjang"},
            "menengah": {"answer": menengah, "confidence": "sedang", "reason": "-"},
            "mahir": {"answer": mahir, "confidence": "tinggi", "reason": "konteks"}}


def test_flags():
    it = item("Sedang")
    it.meta["sim"] = answers("A", "B", "B")
    assert flags_for(it) == []
    it.meta["sim"] = answers("A", "B", "C")
    assert any("80%" in f for f in flags_for(it))
    it.meta["sim"] = answers("B", "B", "B", awam_conf="tinggi")
    assert any("0%" in f for f in flags_for(it))
    it = item("Mudah")
    it.meta["sim"] = answers("A", "C", "B")
    assert any("50%" in f for f in flags_for(it))
    it = item("Sulit")
    it.meta["sim"] = answers("B", "B", "B")
    assert any("Sulit" in f for f in flags_for(it))


def test_guessing_warning_is_relative_to_baseline():
    items = [item("Sedang") for _ in range(10)]
    for it in items:
        it.meta["sim"] = answers("A", "B", "B")
    for it in items[:5]:
        it.meta["sim"] = answers("B", "B", "B")
    assert not any("hanya melihat opsi" in m for _, m in summarize("reading", [items]))
    assert not any("hanya melihat opsi" in m for _, m in summarize("structure", [items]))
    for it in items[:6]:
        it.meta["sim"] = answers("B", "B", "B")
    assert any("hanya melihat opsi" in m for _, m in summarize("structure", [items]))


class SimFake:
    """Persona mahir menjawab sesuai kunci kecuali soal no 3; persona lain selalu menjawab A."""

    def __init__(self, keys):
        self.keys = keys
        self.calls = 0

    def generate_json(self, system, prompt, schema, **kwargs):
        self.calls += 1
        persona = next(p for p, text in PERSONAS.items() if text in prompt)
        numbers = [int(n) for n in re.findall(r"^Soal (\d+)", prompt, re.M)]
        out = []
        for n in numbers:
            answer = self.keys[n] if persona == "mahir" and n != 3 else ("D" if self.keys[n] != "D" else "C") if persona == "mahir" else "A"
            out.append({"no": n, "answer": answer, "confidence": "sedang", "reason": "uji"})
        return {"answers": out}


def test_simulation_flow_and_export(tmp_path):
    batch = plan_structure_section(load_library(), BP, 2, 1)
    fake = SimFake({it.number: it.key for it in batch[0]})
    simulate_section("structure", batch, tmp_path / "sim", lambda: fake, log=lambda *_: None)
    assert fake.calls == 4 * 3
    issues = summarize("structure", batch)
    assert any("no 3: peserta 80% memilih" in m for lvl, m in issues if lvl == "WARN")
    assert any("skor simulasi" in m for lvl, m in issues if lvl == "INFO")

    path = tmp_path / "P1.xlsx"
    write_section_workbook(path, batch[0], "seed-2", 2)
    meta = list(openpyxl.load_workbook(path)["META"].iter_rows(values_only=True))
    row3 = next(r for r in meta[1:] if r[0] == 3)
    assert row3[META_HEADERS.index("status")] == "Perlu dicek"
    assert "80%" in row3[META_HEADERS.index("catatan_qc")]

    write_summary(tmp_path / "ringkasan.xlsx", {"batch": "seed-2"}, {"structure": batch}, issues)
    sim_rows = list(openpyxl.load_workbook(tmp_path / "ringkasan.xlsx")["Simulasi"].iter_rows(values_only=True))
    assert any(r[2] == 3 for r in sim_rows[1:])

    def no_client():
        raise AssertionError("cache simulasi harus dipakai ulang")

    simulate_section("structure", batch, tmp_path / "sim", no_client, log=lambda *_: None)
