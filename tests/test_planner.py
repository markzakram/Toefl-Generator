import openpyxl
import pytest

from toefl_gen.blueprint import load_blueprint
from toefl_gen.exporter import SIADU_HEADERS, write_section_workbook
from toefl_gen.families import load_library
from toefl_gen.planner import PlanError, plan_structure_section
from toefl_gen.qc import ERROR, check_batch

BP = load_blueprint()
LIBRARY = load_library()


def snapshot(batch):
    return [[(it.stem, tuple(it.options), it.key) for it in items] for items in batch]


@pytest.mark.parametrize("seed", [1, 2, 7, 2026, 99991])
def test_batch_passes_qc(seed):
    batch = plan_structure_section(LIBRARY, BP, seed, 5)
    assert len(batch) == 5 and all(len(items) == 40 for items in batch)
    errors = [msg for level, msg in check_batch({"structure": batch}, BP) if level == ERROR]
    assert errors == []


@pytest.mark.parametrize("paket", [1, 2, 3, 4, 5])
@pytest.mark.parametrize("seed", [1, 2026, 31337])
def test_every_paket_count_plans(seed, paket):
    batch = plan_structure_section(LIBRARY, BP, seed, paket)
    assert [m for lvl, m in check_batch({"structure": batch}, BP) if lvl == ERROR] == []


def test_same_seed_same_batch():
    assert snapshot(plan_structure_section(LIBRARY, BP, 42, 5)) == snapshot(plan_structure_section(LIBRARY, BP, 42, 5))


def test_different_seed_different_batch():
    assert snapshot(plan_structure_section(LIBRARY, BP, 42, 5)) != snapshot(plan_structure_section(LIBRARY, BP, 43, 5))


def test_registry_blocks_previous_batch():
    first = plan_structure_section(LIBRARY, BP, 10, 5)
    used = frozenset(it.fingerprint for items in first for it in items)
    second = plan_structure_section(LIBRARY, BP, 11, 3, blocked=used)
    assert not used & {it.fingerprint for items in second for it in items}
    assert [m for lvl, m in check_batch({"structure": second}, BP, used) if lvl == ERROR] == []


def test_exhausted_library_raises_clear_error():
    everything = frozenset(
        fr.fingerprint(v) for fam in LIBRARY.values() for fr in fam.frames for v in fr.variants()
    )
    with pytest.raises(PlanError):
        plan_structure_section(LIBRARY, BP, 1, 5, blocked=everything)


def test_excel_matches_siadu_template(tmp_path):
    items = plan_structure_section(LIBRARY, BP, 5, 1)[0]
    path = tmp_path / "P1_structure.xlsx"
    write_section_workbook(path, items, "seed-5", 5)
    wb = openpyxl.load_workbook(path)
    rows = list(wb["SOAL"].iter_rows(values_only=True))
    assert list(rows[0]) == SIADU_HEADERS
    assert len(rows) == 41
    col = {h: i for i, h in enumerate(SIADU_HEADERS)}
    for row in rows[1:]:
        assert row[col["level"]] in ("Mudah", "Sedang", "Sulit")
        assert row[col["jawaban_benar"]] in "ABCD"
        assert all(row[col[f"skor_{c}"]] is None for c in "abcdef")
        assert row[col["opsi_e"]] is None
        assert all(row[col[f"opsi_{c}"]] for c in "abcd")
        assert row[col["answer_type"]] == "option_new"
    assert "META" in wb.sheetnames
