"""Website generator untuk tim: satu halaman statis yang menyusun tryout dari bank soal.

Bank berisi "bentuk" per section, masing-masing sudah lolos QC komposisi dan sebaran kunci. Seed memilih
kombinasi bentuk di browser, jadi tidak perlu server, API key, atau biaya per generate. Batch yang punya
`label` (misalnya latihan Part C) ditampilkan sebagai set latihan, bukan masuk ke kombinasi tryout.

File paket memuat kunci jawaban, sedangkan host statis biasanya bisa dibuka siapa saja. Karena itu setiap
file dan daftar isinya dienkripsi AES-GCM dengan kunci dari kata sandi (PBKDF2-SHA256), lalu dibuka di
browser. Nama file di server acak, jadi nama soal atau paket juga tidak terlihat tanpa kata sandi.

Tanpa kata sandi (`password=None`), file disimpan apa adanya. Versi ini hanya untuk dibuka di komputer sendiri,
karena memuat kunci jawaban tanpa perlindungan. Foldernya diberi `.vercelignore` yang mengabaikan semua file, dan
build ini menolak menulis ke folder yang sudah disiapkan untuk Vercel.

`check_site` memeriksa folder deploy sebelum diunggah: bukan versi tanpa sandi, tidak ada file lain yang ikut,
semua file yang dirujuk ada dan terbuka dengan kata sandi, serta ukurannya masih di bawah batas unggah Vercel.
"""

import base64
import hashlib
import json
import os
import re
import secrets
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .branding import EMBEDDED, embed_assets  # noqa: F401  (EMBEDDED dipakai tes)
from .models import Item
from .packaging import GUIDE
from .review_html import PART_LABELS, SECTIONS, TEMPLATE_PATH as REVIEW_TEMPLATE_PATH, collect
from .simulate import AWAM_BASELINE
from .word_siadu import write_section_word

TEMPLATE_PATH = Path(__file__).with_name("site_template.html")
PASSWORD_ENV = "SITUS_PASSWORD"
MIN_PASSWORD = 12
ITERATIONS = 600_000
NONCE_BYTES = 12
SHORT_LABELS = {"listening": "Listening", "structure": "Structure", "reading": "Reading"}

# Batas unggah lewat Vercel CLI (vercel.com/docs/limits): 100 MB untuk Hobby, 1 GB untuk Pro, 15.000 file.
HOBBY_UPLOAD_MB = 100
PRO_UPLOAD_MB = 1000
MAX_UPLOAD_FILES = 15_000
SITE_FILES = {"index.html", "robots.txt", "vercel.json"}
BIN_NAME = re.compile(r"files/[0-9a-f]{24}\.bin")
CONFIG_TAG = re.compile(r'<script id="site-config" type="application/json">(.*?)</script>', re.S)
DEPLOY_MARKERS = ("vercel.json", ".vercel")
LOCAL_GUARD = "# Versi tanpa sandi berisi kunci jawaban. Semua file diabaikan agar tidak pernah terunggah.\n*\n"
VERCEL_CONFIG = {
    "headers": [
        {"source": "/(.*)", "headers": [
            {"key": "X-Robots-Tag", "value": "noindex, nofollow, noarchive"},
            {"key": "Referrer-Policy", "value": "no-referrer"},
            {"key": "X-Content-Type-Options", "value": "nosniff"},
            {"key": "X-Frame-Options", "value": "DENY"},
            {"key": "Permissions-Policy", "value": "camera=(), microphone=(), geolocation=()"},
        ]},
        {"source": "/files/(.*)", "headers": [{"key": "Cache-Control", "value": "public, max-age=31536000, immutable"}]},
    ],
}


class SiteError(Exception):
    pass


def derive_key(password, salt, iterations=ITERATIONS):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def encrypt(key, data):
    nonce = os.urandom(NONCE_BYTES)
    return nonce + AESGCM(key).encrypt(nonce, data, None)


def decrypt(key, blob):
    return AESGCM(key).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], None)


class _Store:
    """Menyimpan file dengan nama acak, terenkripsi kalau ada kunci."""

    def __init__(self, files_dir, key):
        self.files_dir = files_dir
        self.key = key

    def data(self, data):
        name = secrets.token_hex(12) + ".bin"
        (self.files_dir / name).write_bytes(data if self.key is None else encrypt(self.key, data))
        return name

    def file(self, path, display_name=None):
        data = path.read_bytes()
        return {"name": display_name or path.name, "size": len(data), "file": self.data(data)}

    def optional(self, path):
        return self.file(path) if path.exists() else None


def _audio_content(script, part):
    if len(script) == 1:
        return "Pertanyaan saja"
    return "Kuliah dan pertanyaan" if part == "C" else "Percakapan dan pertanyaan"


def _audio_rows(rows, batch_dir, paket, store, missing):
    audio = []
    for it in rows:
        path = batch_dir / f"P{paket}" / "audio" / it["meta"]["audio_file"]
        if not path.exists():
            missing.append(it["meta"]["audio_file"])
            continue
        audio.append({
            **store.file(path), "no": it["number"], "part": it["part"], "partLabel": PART_LABELS.get(it["part"], it["part"]),
            "content": _audio_content(it["meta"]["audio_script"], it["part"]), "seconds": it["meta"].get("audio_seconds"),
            "group": it["meta"].get("group"), "topic": it["topic"],
        })
    return audio


def _bank_word(batch_dir, archive, paket, section, store):
    """Judul Word menyebut sumbernya di bank, bukan nomor paket asal, karena seed bisa menaruhnya di paket mana saja."""
    info = archive["info"]
    path = batch_dir / f"P{paket}" / f"P{paket}_{section}_siadu.docx"
    if info.get("label") or not path.exists():
        return store.optional(path)
    with TemporaryDirectory() as folder:
        copy = Path(folder) / path.name
        items = [Item(**it) for it in archive["sections"][section][paket - 1]]
        write_section_word(copy, items, section, paket, info["seed"], label=f"Bank {info['batch']} P{paket}")
        return store.file(copy)


def _forms(batch_dir, store, missing):
    """Semua bentuk per section dari satu batch: (section, data untuk daftar isi)."""
    archive = json.loads((batch_dir / "batch.json").read_text(encoding="utf-8"))
    info = archive["info"]
    forms = []
    for paket in range(1, info["paket"] + 1):
        data, _, _, _ = collect(batch_dir, paket)
        for spec, doc in zip(data["sections"], data["docs"]):
            section = spec["id"]
            audio = _audio_rows(archive["sections"][section][paket - 1], batch_dir, paket, store, missing) if section == "listening" else []
            body = {
                "section": spec,
                "items": [it for it in data["items"] if it["section"] == section],
                "passages": data["passages"] if section == "reading" else {},
                "doc": {"label": doc["label"], "word": _bank_word(batch_dir, archive, paket, section, store),
                        "excel": store.optional(batch_dir / f"P{paket}" / f"P{paket}_{section}.xlsx")},
                "audio": audio,
                "meta": {"batch": info["batch"], "seed": info["seed"], "versiPustaka": info.get("versi_pustaka", ""),
                         "model": info.get("model", ""), "dibuat": info.get("dibuat", "")},
            }
            forms.append((section, {
                "id": f"{info['batch']}-P{paket}-{section}",
                "source": f"{info['batch']} paket {paket}",
                "count": spec["count"],
                "title": info.get("label"),
                "file": store.data(json.dumps(body, ensure_ascii=False).encode("utf-8")),
            }))
    return forms


def build_site(batch_dirs, out, password):
    """Bangun website di `out`. `password=None` membuat versi lokal tanpa enkripsi.
    Kembalikan ringkasan: lokasi, jumlah file, ukuran MB, audio yang hilang, jumlah bentuk per section."""
    if password is not None and len(password) < MIN_PASSWORD:
        raise SiteError(f"Isi {PASSWORD_ENV} di file .env dengan kata sandi minimal {MIN_PASSWORD} karakter.")
    out = Path(out)
    if password is None and any((out / name).exists() for name in DEPLOY_MARKERS):
        raise SiteError(f"{out} sudah disiapkan untuk Vercel. Buat versi tanpa sandi di folder lain, misalnya output/situs-lokal.")
    for batch_dir in batch_dirs:
        if not (Path(batch_dir) / "batch.json").exists():
            raise FileNotFoundError(f"batch.json tidak ditemukan di {batch_dir}")

    salt = os.urandom(16)
    key = None if password is None else derive_key(password, salt)
    files_dir = out / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    for old in files_dir.glob("*.bin"):
        old.unlink()
    store = _Store(files_dir, key)

    missing = []
    forms = {section: [] for section in SECTIONS}
    practice = []
    for batch_dir in batch_dirs:
        for section, form in _forms(Path(batch_dir), store, missing):
            if form["title"]:
                practice.append(form)
            else:
                form["label"] = f"{SHORT_LABELS[section]} {len(forms[section]) + 1}"
                forms[section].append(form)

    manifest = {
        "forms": forms,
        "practice": practice,
        "sections": [{"id": section, "label": spec["label"], "short": SHORT_LABELS[section]} for section, spec in SECTIONS.items()],
        "template": store.data(embed_assets(REVIEW_TEMPLATE_PATH.read_text(encoding="utf-8")).encode("utf-8")),
        "guide": GUIDE,
        "baseline": AWAM_BASELINE,
    }
    listing = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
    if key is None:
        config = {"plain": True, "manifest": base64.b64encode(listing).decode("ascii")}
    else:
        config = {
            "salt": base64.b64encode(salt).decode("ascii"),
            "iterations": ITERATIONS,
            "manifest": base64.b64encode(encrypt(key, listing)).decode("ascii"),
        }
    html = embed_assets(TEMPLATE_PATH.read_text(encoding="utf-8")).replace("__CONFIG__", json.dumps(config))
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    guard = out / ".vercelignore"
    if key is None:
        guard.write_text(LOCAL_GUARD, encoding="utf-8")
    else:
        if guard.exists() and guard.read_text(encoding="utf-8") == LOCAL_GUARD:
            guard.unlink()
        (out / "vercel.json").write_text(json.dumps(VERCEL_CONFIG, indent=2) + "\n", encoding="utf-8")

    stored = list(files_dir.glob("*.bin"))
    return {
        "out": out, "files": len(stored), "size_mb": sum(p.stat().st_size for p in stored) / 1_000_000, "missing": missing,
        "forms": {section: len(rows) for section, rows in forms.items()}, "practice": len(practice),
    }


def site_config(out):
    """Konfigurasi yang tertanam di index.html, atau None kalau index.html tidak ada atau bukan buatan `build_site`."""
    index = Path(out) / "index.html"
    if not index.exists():
        return None
    match = CONFIG_TAG.search(index.read_text(encoding="utf-8"))
    return json.loads(match.group(1)) if match else None


def _noindex(out):
    try:
        config = json.loads((out / "vercel.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return any(h.get("key") == "X-Robots-Tag" and "noindex" in h.get("value", "")
               for rule in config.get("headers", []) for h in rule.get("headers", []))


def check_site(out, password):
    """Periksa folder deploy sebelum diunggah. `problems` harus kosong, `warnings` cukup dibaca.
    Isi file dibuka dengan kata sandi, jadi pemeriksaan butuh kata sandi yang sama dengan saat build."""
    out = Path(out)
    problems, warnings = [], []
    report = {"out": out, "problems": problems, "warnings": warnings, "files": 0, "size_mb": 0.0,
              "largest_mb": 0.0, "parts_mb": {}}
    config = site_config(out)
    if config is None:
        problems.append(f"{out} belum berisi website. Bangun dulu dengan perintah site.")
        return report
    if config.get("plain"):
        problems.append("Ini versi tanpa sandi yang memuat kunci jawaban. Bangun ulang dengan kata sandi.")
        return report

    uploads = [p for p in out.rglob("*") if p.is_file() and ".vercel" not in p.relative_to(out).parts]
    sizes = {p.relative_to(out).as_posix(): p.stat().st_size for p in uploads}
    report.update(files=len(sizes), size_mb=sum(sizes.values()) / 1_000_000, largest_mb=max(sizes.values()) / 1_000_000)
    for name in sorted(sizes):
        if name not in SITE_FILES and not BIN_NAME.fullmatch(name):
            problems.append(f"File di luar isi website ikut terunggah: {name}")
    if not _noindex(out):
        problems.append("vercel.json tidak ada atau tidak meminta noindex. Bangun ulang dengan perintah site.")
    robots = out / "robots.txt"
    if not robots.exists() or "Disallow: /" not in robots.read_text(encoding="utf-8"):
        problems.append("robots.txt tidak melarang pengindeksan. Bangun ulang dengan perintah site.")
    if report["size_mb"] > PRO_UPLOAD_MB:
        problems.append(f"Ukuran {report['size_mb']:.0f} MB melebihi batas unggah Vercel Pro ({PRO_UPLOAD_MB} MB).")
    elif report["size_mb"] > HOBBY_UPLOAD_MB:
        warnings.append(f"Ukuran {report['size_mb']:.0f} MB melebihi batas unggah Vercel Hobby ({HOBBY_UPLOAD_MB} MB), "
                        "jadi perlu paket Pro.")
    if len(sizes) > MAX_UPLOAD_FILES:
        problems.append(f"{len(sizes)} file melebihi batas {MAX_UPLOAD_FILES} file per deploy.")

    if not password or len(password) < MIN_PASSWORD:
        problems.append(f"Isi {PASSWORD_ENV} di .env dengan kata sandi build ini agar isinya bisa diperiksa.")
        return report
    key = derive_key(password, base64.b64decode(config["salt"]), config.get("iterations", ITERATIONS))
    try:
        manifest = json.loads(decrypt(key, base64.b64decode(config["manifest"])))
    except InvalidTag:
        problems.append(f"{PASSWORD_ENV} di .env tidak cocok dengan build ini. Pakai kata sandi saat build, atau bangun ulang.")
        return report

    owners = {}

    def read(name, part):
        owners.setdefault(name, part)
        path = out / "files" / name
        if not path.exists():
            problems.append(f"File yang dirujuk tidak ada: files/{name}")
            return None
        try:
            return decrypt(key, path.read_bytes())
        except InvalidTag:
            problems.append(f"File tidak terenkripsi dengan kata sandi ini: files/{name}")
            return None

    read(manifest["template"], "lainnya")
    groups = [(section, form) for section, rows in manifest["forms"].items() for form in rows]
    groups += [("latihan", form) for form in manifest["practice"]]
    for part, form in groups:
        data = read(form["file"], part)
        if data is None:
            continue
        body = json.loads(data)
        for entry in filter(None, [body["doc"].get("word"), body["doc"].get("excel"), *body.get("audio", [])]):
            read(entry["file"], part)

    parts = {}
    for name, size in sizes.items():
        stored = name.removeprefix("files/")
        if BIN_NAME.fullmatch(name) and stored not in owners:
            warnings.append(f"File tidak dipakai (aman, hanya menambah ukuran): {name}")
        part = owners.get(stored, "lainnya")
        parts[part] = parts.get(part, 0) + size
    report["parts_mb"] = {part: size / 1_000_000 for part, size in parts.items()}
    return report
