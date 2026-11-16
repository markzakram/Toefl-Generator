import re
from collections import Counter

import pytest

from toefl_gen.blueprint import key_bounds, load_blueprint
from toefl_gen.qc import ERROR, check_batch
from toefl_gen.reading import ReadingError, generate_reading, plan_reading, validate_passage

BP = load_blueprint()
SPEC = BP["sections"]["reading"]
SLOT = re.compile(r"^(\d+)\. tipe=(\w+), level=(\w+)$", re.M)

PARAGRAPH = ("Researchers describe a remarkable process in which small changes build over many years, and it "
             "shapes the wider environment in ways that scientists continue to measure carefully. ")


def fake_data(prompt, words_per_paragraph=75):
    slots = SLOT.findall(prompt)
    base = PARAGRAPH.split()
    paragraphs = []
    for i in range(4):
        words = (base * 6)[:words_per_paragraph]
        paragraphs.append(f"Part{i + 1} " + " ".join(words[1:]))
    questions = []
    for n, t, _level in slots:
        question = {
            "vocabulary": 'The word "remarkable" in paragraph 2 is closest in meaning to',
            "reference": 'The word "it" in paragraph 3 refers to',
            "negative_detail": "All of the following are mentioned EXCEPT",
        }.get(t, f"According to the passage, what is true about point {n}?")
        questions.append({
            "slot": int(n),
            "type": t,
            "question": question,
            "options": {L: f"option {L} for slot {n}" for L in "ABCD"},
            "key": "A",
            "evidence": "small changes build over many years",
            "penjelasan": ("Teks menyatakan bahwa perubahan kecil terjadi selama bertahun-tahun, dan perubahan itu "
                           "pada akhirnya membentuk lingkungan yang lebih luas sebagaimana diukur para ilmuwan."),
            "alasan_salah": {
                "A": "-",
                "B": "Salah karena hal ini tidak pernah dibahas di dalam teks, yang hanya berfokus pada perubahan kecil.",
                "C": "karena pernyataan ini bertentangan dengan penjelasan teks tentang proses yang berlangsung lama",
                "D": "opsi ini terlalu luas dibandingkan dengan pokok yang sebenarnya dibahas teks",
            },
        })
    return {"title": "A Test Passage", "paragraphs": paragraphs, "questions": questions}


class FakeClient:
    def __init__(self, bad_first=False):
        self.calls = 0
        self.bad_first = bad_first

    def generate_json(self, system, prompt, schema):
        self.calls += 1
        if self.bad_first and self.calls == 1:
            return fake_data(prompt, words_per_paragraph=40)
        return fake_data(prompt)


def test_plan_is_parallel_and_balanced():
    plan = plan_reading(BP, 1, 5)
    assert len(plan) == 5 and all(len(p) == SPEC["passages"] for p in plan)
    shapes = [[(ps["field"], [(s["type"], s["level"]) for s in ps["slots"]]) for ps in p] for p in plan]
    assert all(s == shapes[0] for s in shapes)
    topics = [ps["topic"]["id"] for p in plan for ps in p]
    assert len(topics) == len(set(topics))
    lo, hi = key_bounds(50, BP["key_rules"])
    for p in plan:
        slots = [s for ps in p for s in ps["slots"]]
        assert len(slots) == 50
        assert all(lo <= n <= hi for n in Counter(s["key"] for s in slots).values())
        assert Counter(s["level"] for s in slots) == {"Mudah": 15, "Sedang": 25, "Sulit": 10}
        assert sum(s["type"] == "tone" for s in slots) <= SPEC["max_tone_items"]
        assert all(ps["slots"][0]["type"] == "main_idea" for ps in p)


def test_generate_with_fake_client_passes_qc(tmp_path):
    plan = plan_reading(BP, 3, 2)
    fake = FakeClient()
    batch = generate_reading(plan, BP, tmp_path, lambda: fake, log=lambda *_: None)
    assert fake.calls == 10
    assert [m for lvl, m in check_batch({"reading": batch}, BP) if lvl == ERROR] == []
    for items, passages in zip(batch, plan):
        targets = [s["key"] for ps in passages for s in ps["slots"]]
        assert [it.key for it in items] == targets
        for it in items:
            correct = it.options["ABCD".index(it.key)]
            assert correct.startswith("option A")
            assert it.pembahasan.startswith(f"Jawaban: {it.key}\n")
            assert "keliru karena salah" not in it.pembahasan and "keliru karena karena" not in it.pembahasan
            assert 'bagian teks "small changes build over many years".' in it.pembahasan
            assert it.stem.startswith(f"PASSAGE {it.meta['passage']}: A Test Passage")


def test_cache_is_reused(tmp_path):
    plan = plan_reading(BP, 4, 1)
    generate_reading(plan, BP, tmp_path, lambda: FakeClient(), log=lambda *_: None)

    def no_client():
        raise AssertionError("klien tidak boleh dipanggil bila cache lengkap")

    batch = generate_reading(plan, BP, tmp_path, no_client, log=lambda *_: None)
    assert len(batch[0]) == 50


def test_retry_with_feedback(tmp_path):
    plan = plan_reading(BP, 5, 1)
    plan[0] = plan[0][:1]
    fake = FakeClient(bad_first=True)
    generate_reading(plan, BP, tmp_path, lambda: fake, log=lambda *_: None)
    assert fake.calls == 2


def test_gives_up_after_max_attempts(tmp_path):
    plan = plan_reading(BP, 6, 1)
    plan[0] = plan[0][:1]

    class AlwaysBad(FakeClient):
        def generate_json(self, system, prompt, schema):
            return fake_data(prompt, words_per_paragraph=30)

    with pytest.raises(ReadingError):
        generate_reading(plan, BP, tmp_path, lambda: AlwaysBad(), log=lambda *_: None)


def test_validation_catches_problems():
    passage = plan_reading(BP, 7, 1)[0][0]
    prompt = "\n".join(f"{s['slot']}. tipe={s['type']}, level={s['level']}" for s in passage["slots"])
    good = fake_data(prompt)
    assert validate_passage(good, passage, SPEC) == []

    bad = fake_data(prompt)
    bad["questions"][1]["evidence"] = "a sentence that is not in the passage"
    assert any("evidence" in p for p in validate_passage(bad, passage, SPEC))

    bad = fake_data(prompt)
    for q in bad["questions"]:
        if q["type"] == "vocabulary":
            q["question"] = 'The word "photosynthesis" in paragraph 2 is closest in meaning to'
    if any(s["type"] == "vocabulary" for s in passage["slots"]):
        assert any("tidak ada di paragraf" in p for p in validate_passage(bad, passage, SPEC))

    bad = fake_data(prompt, words_per_paragraph=120)
    assert any("kata" in p for p in validate_passage(bad, passage, SPEC))


def test_blocked_topics_are_not_reused():
    first = plan_reading(BP, 8, 5)
    used = frozenset(f"READ:{ps['topic']['id']}#1" for p in first for ps in p)
    second = plan_reading(BP, 9, 2, blocked=used)
    again = {ps["topic"]["id"] for p in second for ps in p}
    assert not again & {fp[5:-2] for fp in used}
