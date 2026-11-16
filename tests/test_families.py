import random
import re

import pytest

from toefl_gen.families import load_library, validate_library
from toefl_gen.models import LETTERS

LIBRARY = load_library()
FRAMES = [fr for fam in LIBRARY.values() for fr in fam.frames]


def test_library_is_valid():
    assert validate_library(LIBRARY) == []


@pytest.mark.parametrize("frame", FRAMES, ids=lambda fr: fr.key)
def test_frame_builds_valid_items(frame):
    rng = random.Random(7)
    for values in frame.variants():
        for key in frame.feasible_keys(values):
            item = frame.build(values, key, rng)
            assert item.key == key
            assert len(item.options) == 4
            assert len({o.lower() for o in item.options}) == 4
            assert item.pembahasan.startswith(f"Jawaban: {key}\n")
            assert "{" not in item.stem + item.pembahasan + "".join(item.options)
            if frame.format == "structure":
                assert item.stem.count("___") == 1
                assert item.options[LETTERS.index(key)] == re.sub(r"\{(\w+)\}", lambda m: values[m.group(1)], frame.correct)
            else:
                assert re.findall(r"\(([A-D])\)", item.stem) == list(LETTERS)
                for letter, option in zip(LETTERS, item.options):
                    assert f"{option}({letter})" in item.stem
                assert "[" not in item.stem and "](" not in item.stem


def test_every_family_has_both_levels_spread():
    for fam in LIBRARY.values():
        assert fam.frames, fam.id
        assert len({fr.level for fr in fam.frames}) >= 2, fam.id
