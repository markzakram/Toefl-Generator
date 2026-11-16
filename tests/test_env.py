from toefl_gen.env import load_env


def test_load_env(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text(
        "# komentar\n"
        "TOEFL_TEST_A=nilai-a\n"
        "export TOEFL_TEST_B=\"nilai b\"\n"
        "TOEFL_TEST_EMPTY=\n"
        "TOEFL_TEST_KEEP=dari-file\n"
        "baris tanpa sama dengan\n",
        encoding="utf-8",
    )
    for name in ("TOEFL_TEST_A", "TOEFL_TEST_B", "TOEFL_TEST_EMPTY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TOEFL_TEST_KEEP", "dari-environment")

    loaded = load_env(path)

    import os
    assert loaded == ["TOEFL_TEST_A", "TOEFL_TEST_B"]
    assert os.environ["TOEFL_TEST_A"] == "nilai-a"
    assert os.environ["TOEFL_TEST_B"] == "nilai b"
    assert "TOEFL_TEST_EMPTY" not in os.environ
    assert os.environ["TOEFL_TEST_KEEP"] == "dari-environment"
    for name in loaded:
        monkeypatch.delenv(name)


def test_missing_env_file(tmp_path):
    assert load_env(tmp_path / "tidak-ada.env") == []
