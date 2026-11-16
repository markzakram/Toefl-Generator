from toefl_gen.blueprint import key_bounds, level_counts, load_blueprint, validate


def test_blueprint_valid():
    assert validate(load_blueprint()) == []


def test_level_counts_sum_and_shape():
    mix = load_blueprint()["level_mix"]
    assert level_counts(15, mix) == {"Mudah": 5, "Sedang": 7, "Sulit": 3}
    assert level_counts(25, mix) == {"Mudah": 8, "Sedang": 12, "Sulit": 5}
    for n in range(1, 60):
        assert sum(level_counts(n, mix).values()) == n


def test_key_bounds():
    rules = load_blueprint()["key_rules"]
    assert key_bounds(40, rules) == (8, 12)
    assert key_bounds(50, rules) == (10, 15)
