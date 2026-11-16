"""ZIP per paket untuk tim input: satu berisi semua file, satu lagi hanya audio."""

import zipfile

STORED = {".mp3", ".docx", ".xlsx"}  # Sudah terkompresi, jadi tidak perlu dikompres ulang.
GUIDE = """Paket {paket} untuk tim input

1. Masukkan soal dari file Word: teks soal, opsi, kunci, level, dan pembahasan.
2. Untuk Listening, ubah tipe soal menjadi audio, lalu unggah file dari folder audio
   yang namanya tertulis di baris "File audio" pada soal itu.
3. Simpan.

Di Part B dan C, percakapan atau kuliah hanya ada di audio soal pertama tiap kelompok.
File Word dan Excel memuat kunci jawaban. Jangan dibagikan ke luar tim.
"""


def paket_zip_path(batch_dir, paket):
    return batch_dir / f"P{paket}_paket_input.zip"


def audio_zip_path(batch_dir, paket):
    return batch_dir / f"P{paket}_audio.zip"


def audio_files(paket_dir):
    return sorted((paket_dir / "audio").glob("*.mp3"))


def _add(archive, path, name):
    archive.write(path, name, compress_type=zipfile.ZIP_STORED if path.suffix in STORED else zipfile.ZIP_DEFLATED)


def write_paket_zips(batch_dir, paket):
    """Tulis ZIP satu paket. Kembalikan (ZIP lengkap, ZIP audio); ZIP audio None kalau paket tanpa audio."""
    paket_dir = batch_dir / f"P{paket}"
    root = f"P{paket}"
    audio = audio_files(paket_dir)
    with zipfile.ZipFile(paket_zip_path(batch_dir, paket), "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{root}/CARA_INPUT.txt", GUIDE.format(paket=paket).replace("\n", "\r\n"))
        for path in sorted(paket_dir.glob("*.docx")) + sorted(paket_dir.glob("*.xlsx")):
            _add(archive, path, f"{root}/{path.name}")
        for path in audio:
            _add(archive, path, f"{root}/audio/{path.name}")
    if not audio:
        return paket_zip_path(batch_dir, paket), None
    with zipfile.ZipFile(audio_zip_path(batch_dir, paket), "w") as archive:
        for path in audio:
            _add(archive, path, f"{root}_audio/{path.name}")
    return paket_zip_path(batch_dir, paket), audio_zip_path(batch_dir, paket)
