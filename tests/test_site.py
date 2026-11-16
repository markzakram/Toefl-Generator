import base64
import io
import json
import re
import zipfile

import pytest
from cryptography.exceptions import InvalidTag
from docx import Document

from toefl_gen.cli import main, site_dir
from toefl_gen.packaging import audio_zip_path, paket_zip_path, write_paket_zips
from toefl_gen.site import EMBEDDED, ITERATIONS, PASSWORD_ENV, SiteError, build_site, check_site, decrypt, derive_key

PASSWORD = "sandi-uji-untuk-tes"
AUDIO_BYTES = b"\xff\xfb\x90\x00fake-mp3"
SECRET_WORD = "RAHASIA-ISI-WORD"


def _listening(number, part, audio_file, script):
    return {"section": "listening", "part": part, "family_id": "x", "topic": "Topik", "level": "Sedang", "stem": "Listen.",
            "options": list("abcd"), "key": "B", "pembahasan": "-", "frame_id": "f", "fingerprint": f"L{number}", "number": number,
            "meta": {"audio_file": audio_file, "audio_script": script, "audio_seconds": 65.0, "transcript": "MAN: Hi.",
                     "question": "What?", "group": 1 if part != "A" else None}}


def _make_batch(root, name, label=None):
    batch = root / name
    paket = batch / "P1"
    (paket / "audio").mkdir(parents=True)
    for file in ("P1_L_A_001.mp3", "P1_L_B_031.mp3", "P1_L_B_032.mp3", "P1_L_C_039.mp3"):
        (paket / "audio" / file).write_bytes(AUDIO_BYTES)
    (paket / "audio" / "manifest.json").write_text("{}", encoding="utf-8")
    for section in ("listening", "structure"):
        (paket / f"P1_{section}_siadu.docx").write_bytes(SECRET_WORD.encode())
        (paket / f"P1_{section}.xlsx").write_bytes(b"excel-" + section.encode())
    full = [["MAN", "Hi"], ["NARRATOR", "What?"]]
    items = [_listening(1, "A", "P1_L_A_001.mp3", full), _listening(31, "B", "P1_L_B_031.mp3", full),
             _listening(32, "B", "P1_L_B_032.mp3", [["NARRATOR", "What?"]]), _listening(39, "C", "P1_L_C_039.mp3", full)]
    info = {"batch": name, "seed": 7, "paket": 1, "dibuat": "2026-11-04T10:00:00"}
    if label:
        info["label"] = label
    archive = {"info": info, "sections": {"listening": [items], "structure": [[]]}}
    (batch / "batch.json").write_text(json.dumps(archive), encoding="utf-8")
    return batch


@pytest.fixture
def batch_dir(tmp_path):
    return _make_batch(tmp_path, "seed-7")


def _config(out):
    html = (out / "index.html").read_text(encoding="utf-8")
    return json.loads(re.search(r'<script id="site-config" type="application/json">(.*?)</script>', html, re.S).group(1))


def _open_manifest(out, password=PASSWORD):
    config = _config(out)
    key = derive_key(password, base64.b64decode(config["salt"]), config["iterations"])
    return key, json.loads(decrypt(key, base64.b64decode(config["manifest"])))


def _body(out, key, form):
    return json.loads(decrypt(key, (out / "files" / form["file"]).read_bytes()))


def test_zip_lengkap_berisi_semua_kecuali_file_internal(batch_dir):
    write_paket_zips(batch_dir, 1)
    with zipfile.ZipFile(paket_zip_path(batch_dir, 1)) as archive:
        names = archive.namelist()
        assert "P1/CARA_INPUT.txt" in names
        assert "P1/P1_listening_siadu.docx" in names and "P1/P1_structure.xlsx" in names
        assert "P1/audio/P1_L_A_001.mp3" in names
        assert not any("manifest" in n for n in names)
        assert archive.read("P1/audio/P1_L_A_001.mp3") == AUDIO_BYTES
        assert "File audio" in archive.read("P1/CARA_INPUT.txt").decode()


def test_zip_audio_hanya_berisi_mp3(batch_dir):
    write_paket_zips(batch_dir, 1)
    with zipfile.ZipFile(audio_zip_path(batch_dir, 1)) as archive:
        assert sorted(archive.namelist()) == ["P1_audio/P1_L_A_001.mp3", "P1_audio/P1_L_B_031.mp3",
                                              "P1_audio/P1_L_B_032.mp3", "P1_audio/P1_L_C_039.mp3"]


def test_paket_tanpa_audio_tidak_membuat_zip_audio(tmp_path):
    (tmp_path / "P1").mkdir()
    (tmp_path / "P1" / "P1_structure.xlsx").write_bytes(b"x")
    paket_zip, audio_zip = write_paket_zips(tmp_path, 1)
    assert paket_zip.exists() and audio_zip is None


def test_kata_sandi_pendek_ditolak(batch_dir, tmp_path):
    with pytest.raises(SiteError, match=PASSWORD_ENV):
        build_site([batch_dir], tmp_path / "situs", "pendek")
    assert not (tmp_path / "situs").exists()


def test_batch_yang_tidak_ada_ditolak(tmp_path):
    with pytest.raises(FileNotFoundError, match="batch.json"):
        build_site([tmp_path / "tidak-ada"], tmp_path / "situs", PASSWORD)
    assert not (tmp_path / "situs").exists()


def test_bank_berisi_bentuk_per_section(batch_dir, tmp_path):
    out = tmp_path / "situs"
    result = build_site([batch_dir], out, PASSWORD)
    key, manifest = _open_manifest(out)
    assert _config(out)["iterations"] == ITERATIONS
    assert result["missing"] == [] and result["forms"] == {"listening": 1, "structure": 1, "reading": 0}
    listening = manifest["forms"]["listening"][0]
    assert listening["label"] == "Listening 1" and listening["id"] == "seed-7-P1-listening"
    assert listening["source"] == "seed-7 paket 1" and listening["count"] == 4
    body = _body(out, key, listening)
    assert body["section"]["id"] == "listening" and len(body["items"]) == 4
    assert body["meta"]["batch"] == "seed-7"
    rows = {a["no"]: a for a in body["audio"]}
    assert rows[1]["partLabel"] == "Part A" and rows[1]["content"] == "Percakapan dan pertanyaan"
    assert rows[32]["content"] == "Pertanyaan saja"
    assert rows[39]["content"] == "Kuliah dan pertanyaan" and rows[39]["group"] == 1 and rows[39]["topic"] == "Topik"
    assert rows[1]["seconds"] == 65.0
    assert manifest["forms"]["structure"][0]["label"] == "Structure 1"
    assert [s["id"] for s in manifest["sections"]] == ["listening", "structure", "reading"]


def test_beberapa_batch_menambah_bentuk(tmp_path):
    out = tmp_path / "situs"
    build_site([_make_batch(tmp_path, "seed-1"), _make_batch(tmp_path, "seed-2")], out, PASSWORD)
    _, manifest = _open_manifest(out)
    assert [f["label"] for f in manifest["forms"]["listening"]] == ["Listening 1", "Listening 2"]
    assert [f["source"] for f in manifest["forms"]["listening"]] == ["seed-1 paket 1", "seed-2 paket 1"]


def test_batch_berlabel_menjadi_set_latihan(tmp_path):
    out = tmp_path / "situs"
    result = build_site([_make_batch(tmp_path, "seed-1"), _make_batch(tmp_path, "part-c-9", label="Latihan Part C, 4 soal")], out, PASSWORD)
    _, manifest = _open_manifest(out)
    assert result["forms"]["listening"] == 1
    assert [f["title"] for f in manifest["practice"]] == ["Latihan Part C, 4 soal", "Latihan Part C, 4 soal"]
    assert manifest["practice"][0]["id"] == "part-c-9-P1-listening"


def test_kata_sandi_salah_tidak_bisa_membuka(batch_dir, tmp_path):
    out = tmp_path / "situs"
    build_site([batch_dir], out, PASSWORD)
    with pytest.raises(InvalidTag):
        _open_manifest(out, "kata-sandi-lain-yang-salah")


def test_file_bisa_dibuka_dan_kembali_utuh(batch_dir, tmp_path):
    out = tmp_path / "situs"
    build_site([batch_dir], out, PASSWORD)
    key, manifest = _open_manifest(out)
    body = _body(out, key, manifest["forms"]["listening"][0])
    audio = body["audio"][0]
    assert decrypt(key, (out / "files" / audio["file"]).read_bytes()) == AUDIO_BYTES
    assert audio["size"] == len(AUDIO_BYTES)
    word = body["doc"]["word"]
    assert word["name"] == "P1_listening_siadu.docx"
    document = Document(io.BytesIO(decrypt(key, (out / "files" / word["file"]).read_bytes())))
    assert document.paragraphs[0].text == "TOEFL ITP - Bank seed-7 P1 - Listening Comprehension"
    excel = body["doc"]["excel"]
    assert decrypt(key, (out / "files" / excel["file"]).read_bytes()) == b"excel-listening"


def test_word_set_latihan_tetap_memakai_file_aslinya(tmp_path):
    out = tmp_path / "situs"
    build_site([_make_batch(tmp_path, "part-c-9", label="Latihan Part C, 4 soal")], out, PASSWORD)
    key, manifest = _open_manifest(out)
    body = _body(out, key, manifest["practice"][0])
    assert decrypt(key, (out / "files" / body["doc"]["word"]["file"]).read_bytes()) == SECRET_WORD.encode()


def test_template_file_tryout_ikut_tersimpan(batch_dir, tmp_path):
    out = tmp_path / "situs"
    build_site([batch_dir], out, PASSWORD)
    key, manifest = _open_manifest(out)
    template = decrypt(key, (out / "files" / manifest["template"]).read_bytes()).decode("utf-8")
    for placeholder in ("__TITLE__", "__DATA__", "__AUDIO__", "__FILES__"):
        assert placeholder in template


def test_tidak_ada_isi_atau_nama_file_yang_terbaca_tanpa_kata_sandi(batch_dir, tmp_path):
    out = tmp_path / "situs"
    build_site([batch_dir], out, PASSWORD)
    html = (out / "index.html").read_text(encoding="utf-8")
    for leak in ("P1_L_A_001", "seed-7", SECRET_WORD, PASSWORD):
        assert leak not in html
    stored = list((out / "files").iterdir())
    assert all(re.fullmatch(r"[0-9a-f]{24}\.bin", p.name) for p in stored)
    assert all(SECRET_WORD.encode() not in p.read_bytes() and AUDIO_BYTES not in p.read_bytes() for p in stored)


def test_mesin_pencari_diminta_tidak_mengindeks(batch_dir, tmp_path):
    out = tmp_path / "situs"
    build_site([batch_dir], out, PASSWORD)
    assert "Disallow: /" in (out / "robots.txt").read_text(encoding="utf-8")
    assert 'content="noindex' in (out / "index.html").read_text(encoding="utf-8")


def test_bangun_ulang_menghapus_file_lama(batch_dir, tmp_path):
    out = tmp_path / "situs"
    first = build_site([batch_dir], out, PASSWORD)
    second = build_site([batch_dir], out, PASSWORD)
    assert first["files"] == second["files"] == len(list((out / "files").iterdir()))


def test_audio_yang_hilang_dilaporkan(batch_dir, tmp_path):
    (batch_dir / "P1" / "audio" / "P1_L_C_039.mp3").unlink()
    assert build_site([batch_dir], tmp_path / "situs", PASSWORD)["missing"] == ["P1_L_C_039.mp3"]


def test_mode_tanpa_sandi_menyimpan_file_apa_adanya(batch_dir, tmp_path):
    out = tmp_path / "situs"
    build_site([batch_dir], out, None)
    config = _config(out)
    assert config["plain"] is True and "salt" not in config
    manifest = json.loads(base64.b64decode(config["manifest"]))
    body = json.loads((out / "files" / manifest["forms"]["listening"][0]["file"]).read_bytes())
    assert (out / "files" / body["audio"][0]["file"]).read_bytes() == AUDIO_BYTES
    assert (out / "files" / body["doc"]["excel"]["file"]).read_bytes() == b"excel-listening"
    assert "Disallow: /" in (out / "robots.txt").read_text(encoding="utf-8")


def test_mode_terenkripsi_tidak_menandai_diri_tanpa_sandi(batch_dir, tmp_path):
    out = tmp_path / "situs"
    build_site([batch_dir], out, PASSWORD)
    assert "plain" not in _config(out)


def test_cli_tanpa_sandi_harus_diminta_dengan_jelas(batch_dir, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(PASSWORD_ENV, raising=False)
    monkeypatch.setattr("toefl_gen.cli.load_env", lambda: [])
    with pytest.raises(SystemExit, match=PASSWORD_ENV):
        main(["site", "--batch", str(batch_dir), "--out", str(tmp_path / "ditolak")])
    assert not (tmp_path / "ditolak").exists()
    assert main(["site", "--batch", str(batch_dir), "--out", str(tmp_path / "situs"), "--tanpa-sandi"]) == 0
    printed = capsys.readouterr().out
    assert "Jangan diunggah" in printed and "Bank: 1 listening, 1 structure, 0 reading" in printed
    assert _config(tmp_path / "situs")["plain"] is True


def test_perintah_cli_meminta_kata_sandi(batch_dir, tmp_path, monkeypatch):
    monkeypatch.setenv(PASSWORD_ENV, "pendek")
    with pytest.raises(SystemExit, match=PASSWORD_ENV):
        main(["site", "--batch", str(batch_dir), "--out", str(tmp_path / "situs")])


def test_perintah_cli_membuat_website(batch_dir, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(PASSWORD_ENV, PASSWORD)
    out = tmp_path / "situs"
    assert main(["site", "--batch", str(batch_dir), "--out", str(out)]) == 0
    assert (out / "index.html").exists()
    assert PASSWORD not in capsys.readouterr().out


def test_perintah_generate_membuat_zip(tmp_path):
    args = ["generate", "--seed", "1", "--paket", "1", "--sections", "structure", "--no-register", "--out", str(tmp_path)]
    assert main(args) == 0
    with zipfile.ZipFile(tmp_path / "seed-1" / "P1_paket_input.zip") as archive:
        assert "P1/P1_structure_siadu.docx" in archive.namelist()
    assert not (tmp_path / "seed-1" / "P1_audio.zip").exists()


def test_build_terenkripsi_menyiapkan_header_vercel(batch_dir, tmp_path):
    out = tmp_path / "situs"
    build_site([batch_dir], out, PASSWORD)
    config = json.loads((out / "vercel.json").read_text(encoding="utf-8"))
    headers = {h["key"]: h["value"] for rule in config["headers"] if rule["source"] == "/(.*)" for h in rule["headers"]}
    assert "noindex" in headers["X-Robots-Tag"] and headers["Referrer-Policy"] == "no-referrer"
    files_rule = next(rule for rule in config["headers"] if rule["source"] == "/files/(.*)")
    assert "immutable" in files_rule["headers"][0]["value"]
    assert not (out / ".vercelignore").exists()


def test_build_tanpa_sandi_tidak_akan_terunggah(batch_dir, tmp_path):
    out = tmp_path / "lokal"
    build_site([batch_dir], out, None)
    assert not (out / "vercel.json").exists()
    assert (out / ".vercelignore").read_text(encoding="utf-8").splitlines()[-1] == "*"


@pytest.mark.parametrize("marker", ["vercel.json", ".vercel"])
def test_build_tanpa_sandi_menolak_folder_deploy(batch_dir, tmp_path, marker):
    out = tmp_path / "situs"
    build_site([batch_dir], out, PASSWORD)
    if marker == ".vercel":
        (out / "vercel.json").unlink()
        (out / ".vercel").mkdir()
    before = (out / "index.html").read_text(encoding="utf-8")
    with pytest.raises(SiteError, match="situs-lokal"):
        build_site([batch_dir], out, None)
    assert (out / "index.html").read_text(encoding="utf-8") == before


def test_build_terenkripsi_mengganti_folder_lokal(batch_dir, tmp_path):
    out = tmp_path / "situs"
    build_site([batch_dir], out, None)
    build_site([batch_dir], out, PASSWORD)
    assert not (out / ".vercelignore").exists()
    assert check_site(out, PASSWORD)["problems"] == []


def test_cek_situs_lolos_untuk_build_terenkripsi(batch_dir, tmp_path):
    out = tmp_path / "situs"
    build_site([batch_dir], out, PASSWORD)
    (out / ".vercel").mkdir()
    (out / ".vercel" / "project.json").write_text("{}", encoding="utf-8")
    report = check_site(out, PASSWORD)
    assert report["problems"] == [] and report["warnings"] == []
    assert report["files"] == len(list((out / "files").iterdir())) + 3
    assert set(report["parts_mb"]) == {"listening", "structure", "lainnya"}


def test_cek_situs_menolak_versi_tanpa_sandi(batch_dir, tmp_path):
    out = tmp_path / "lokal"
    build_site([batch_dir], out, None)
    assert "tanpa sandi" in check_site(out, PASSWORD)["problems"][0]


def test_cek_situs_menolak_folder_kosong(tmp_path):
    assert "belum berisi website" in check_site(tmp_path / "tidak-ada", PASSWORD)["problems"][0]


def test_cek_situs_butuh_kata_sandi_yang_sama(batch_dir, tmp_path):
    out = tmp_path / "situs"
    build_site([batch_dir], out, PASSWORD)
    assert any("tidak cocok" in p for p in check_site(out, "sandi-lain-yang-panjang")["problems"])
    assert any(PASSWORD_ENV in p for p in check_site(out, "")["problems"])


def test_cek_situs_menemukan_file_yang_ikut_terbawa(batch_dir, tmp_path):
    out = tmp_path / "situs"
    build_site([batch_dir], out, PASSWORD)
    (out / "P1_listening_siadu.docx").write_bytes(SECRET_WORD.encode())
    (out / "files" / "catatan.txt").write_text("kunci", encoding="utf-8")
    problems = check_site(out, PASSWORD)["problems"]
    assert any("P1_listening_siadu.docx" in p for p in problems) and any("catatan.txt" in p for p in problems)


def test_cek_situs_menemukan_file_hilang_atau_tidak_terenkripsi(batch_dir, tmp_path):
    out = tmp_path / "situs"
    build_site([batch_dir], out, PASSWORD)
    key, manifest = _open_manifest(out)
    body = _body(out, key, manifest["forms"]["listening"][0])
    (out / "files" / body["audio"][0]["file"]).unlink()
    (out / "files" / body["doc"]["excel"]["file"]).write_bytes(b"excel-listening")
    problems = check_site(out, PASSWORD)["problems"]
    assert any("tidak ada" in p and body["audio"][0]["file"] in p for p in problems)
    assert any("tidak terenkripsi" in p and body["doc"]["excel"]["file"] in p for p in problems)


def test_cek_situs_memberi_tahu_file_tak_terpakai(batch_dir, tmp_path):
    out = tmp_path / "situs"
    build_site([batch_dir], out, PASSWORD)
    (out / "files" / ("ab" * 12 + ".bin")).write_bytes(b"x")
    report = check_site(out, PASSWORD)
    assert report["problems"] == [] and any("tidak dipakai" in w for w in report["warnings"])


def test_cek_situs_memperingatkan_batas_hobby(batch_dir, tmp_path, monkeypatch):
    out = tmp_path / "situs"
    build_site([batch_dir], out, PASSWORD)
    monkeypatch.setattr("toefl_gen.site.HOBBY_UPLOAD_MB", 0)
    assert any("Hobby" in w for w in check_site(out, PASSWORD)["warnings"])
    monkeypatch.setattr("toefl_gen.site.PRO_UPLOAD_MB", 0)
    assert any("Pro" in p for p in check_site(out, PASSWORD)["problems"])


def test_folder_bawaan_lokal_dan_deploy_berbeda():
    assert site_dir(True) != site_dir(False)
    assert site_dir(False).name == "situs" and site_dir(True).name == "situs-lokal"


def test_perintah_cek_situs(batch_dir, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(PASSWORD_ENV, PASSWORD)
    out = tmp_path / "situs"
    assert main(["site", "--batch", str(batch_dir), "--out", str(out)]) == 0
    assert "Siap di-deploy" in capsys.readouterr().out
    assert main(["cek-situs", "--dir", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "Siap di-deploy: commit dan push" in printed and PASSWORD not in printed
    build_site([batch_dir], tmp_path / "lokal", None)
    assert main(["cek-situs", "--dir", str(tmp_path / "lokal")]) == 1
    assert "Belum siap" in capsys.readouterr().out


def test_logo_dan_font_tersemat_tanpa_sumber_luar(batch_dir, tmp_path):
    out = tmp_path / "situs"
    build_site([batch_dir], out, PASSWORD)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert not any(placeholder in html for placeholder in [*EMBEDDED, "__CONFIG__"])
    assert html.count("data:font/woff2;base64,") == 2 and "data:image/png;base64,iVBOR" in html
    assert re.search(r'(src|href)="https?://', html) is None and "@import" not in html


def _snapshot(out):
    return {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob("*") if p.is_file()}


def test_build_ulang_dengan_sandi_sama_tidak_mengubah_file(batch_dir, tmp_path):
    out = tmp_path / "situs"
    build_site([batch_dir], out, PASSWORD)
    first = _snapshot(out)
    build_site([batch_dir], out, PASSWORD)
    assert _snapshot(out) == first


def test_ganti_sandi_mengganti_semua_file_terenkripsi(batch_dir, tmp_path):
    out = tmp_path / "situs"
    build_site([batch_dir], out, PASSWORD)
    old_salt, old_files = _config(out)["salt"], set((out / "files").iterdir())
    build_site([batch_dir], out, "sandi-baru-yang-panjang")
    assert _config(out)["salt"] != old_salt
    assert not old_files & set((out / "files").iterdir())
    assert check_site(out, "sandi-baru-yang-panjang")["problems"] == []


def test_file_yang_tidak_dipakai_lagi_dihapus(batch_dir, tmp_path):
    out = tmp_path / "situs"
    build_site([batch_dir], out, PASSWORD)
    (batch_dir / "P1" / "P1_structure.xlsx").write_bytes(b"excel-baru")
    build_site([batch_dir], out, PASSWORD)
    report = check_site(out, PASSWORD)
    assert report["problems"] == [] and not any("tidak dipakai" in w for w in report["warnings"])
