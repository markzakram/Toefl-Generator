import argparse
import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

from .blueprint import LEVELS, ROOT, level_counts, load_blueprint, validate
from .exporter import write_archive, write_section_workbook, write_summary
from .families import FORMATS, library_version, load_library, validate_library
from .common import GenerationError, cache_only, used_topics
from .env import load_env
from .listening import generate_listening, generate_part_c_set, plan_listening, plan_part_c_set
from .listening import load_topics as load_listening_topics
from .reading import load_topics as load_reading_topics
from .llm import DEFAULT_EFFORT, DEFAULT_MODEL, ClaudeClient, LLMError
from .packaging import write_paket_zips
from .planner import PlanError, plan_structure_section
from .qc import ERROR, check_batch, check_part_c_set
from .reading import generate_reading, plan_reading
from .registry import blocked_fingerprints, load_registry, register_batch, save_registry
from .review_html import build_review_html
from .simulate import simulate_section, summarize
from .site import PASSWORD_ENV, SiteError, build_site, check_site
from .tts import EdgeTTS, TTSError, render_items
from .word_siadu import write_section_word

AVAILABLE_SECTIONS = ("listening", "structure", "reading")


def cmd_generate(args):
    bp = load_blueprint()
    errors = validate(bp)
    if errors:
        sys.exit("Blueprint tidak valid:\n" + "\n".join(errors))
    names = [s.strip() for s in args.sections.split(",")]
    unknown = [s for s in names if s not in AVAILABLE_SECTIONS]
    if unknown:
        sys.exit(f"Section belum tersedia: {', '.join(unknown)}. Yang tersedia: {', '.join(AVAILABLE_SECTIONS)}.")

    registry = load_registry()
    batch_id = f"seed-{args.seed}"
    blocked = blocked_fingerprints(registry, except_batch=batch_id)
    paket = args.paket or bp["paket_per_batch"]
    out = Path(args.out) / batch_id
    sections = {}
    client = None

    client_lock = threading.Lock()

    def get_client():
        nonlocal client
        with client_lock:
            if client is None:
                client = ClaudeClient(args.model, args.effort)
            return client

    source = cache_only if args.cache_only else get_client

    try:
        if "listening" in names:
            plan = plan_listening(bp, args.seed, paket, blocked)
            sections["listening"] = generate_listening(plan, bp, out / "cache" / "listening", source)
            if not args.no_audio:
                engine = EdgeTTS()
                for p, items in enumerate(sections["listening"], start=1):
                    made = render_items(items, out / f"P{p}" / "audio", engine)
                    print(f"Audio paket {p}: {made} file dibuat, {len(items) - made} dipakai ulang")
        if "structure" in names:
            sections["structure"] = plan_structure_section(load_library(), bp, args.seed, paket, blocked)
        if "reading" in names:
            plan = plan_reading(bp, args.seed, paket, blocked)
            sections["reading"] = generate_reading(plan, bp, out / "cache" / "reading", source)
        sim_issues = []
        if args.simulate:
            for section, batch in sections.items():
                simulate_section(section, batch, out / "cache" / "simulasi", source, effort=args.sim_effort)
                sim_issues += summarize(section, batch)
    except (PlanError, GenerationError, LLMError, TTSError) as e:
        _print_usage(client)
        sys.exit(f"Gagal menyusun batch: {e}\nHasil yang sudah jadi tersimpan di cache; jalankan perintah yang sama untuk melanjutkan.")
    _print_usage(client)

    issues = check_batch(sections, bp, blocked) + sim_issues
    info = {
        "batch": batch_id,
        "seed": args.seed,
        "paket": paket,
        "sections": ",".join(sections),
        "versi_pustaka": library_version(),
        "model": args.model if client else "-",
        "audio": "-" if args.no_audio or "listening" not in sections else EdgeTTS.name,
        "biaya_api_usd": round(client.cost_usd(), 2) if client else 0,
        "dibuat": datetime.now().isoformat(timespec="seconds"),
        "fingerprint_diblok": len(blocked),
    }
    if args.cache_only and (out / "batch.json").exists():
        # Isi soalnya tetap dari pembuatan awal, jadi model dan biayanya juga tetap.
        previous = json.loads((out / "batch.json").read_text(encoding="utf-8"))["info"]
        info.update(model=previous["model"], biaya_api_usd=previous["biaya_api_usd"])
    for section, batch in sections.items():
        for p, items in enumerate(batch, start=1):
            write_section_workbook(out / f"P{p}" / f"P{p}_{section}.xlsx", items, batch_id, args.seed)
            write_section_word(out / f"P{p}" / f"P{p}_{section}_siadu.docx", items, section, p, args.seed)
    for p in range(1, paket + 1):
        write_paket_zips(out, p)
    write_summary(out / "ringkasan_batch.xlsx", info, sections, issues)
    write_archive(out / "batch.json", info, sections)

    n_err = sum(level == ERROR for level, _ in issues)
    for level, msg in issues:
        print(f"[{level}] {msg}")
    for section, batch in sections.items():
        print(f"{section}: {paket} paket x {len(batch[0])} soal")
    print(f"Hasil: {out}")
    print(f"QC: {n_err} error, {len(issues) - n_err} peringatan")
    if n_err:
        print("Batch tidak didaftarkan ke registri karena ada error QC.")
        return 1
    if args.no_register:
        print("Registri tidak diubah (--no-register).")
    else:
        # Dibaca ulang karena proses lain bisa saja mendaftarkan batch selama proses ini berjalan.
        registry = load_registry()
        register_batch(registry, batch_id, {k: info[k] for k in ("seed", "paket", "versi_pustaka", "dibuat")},
                       [it for batch in sections.values() for items in batch for it in items])
        save_registry(registry)
        print(f"Batch {batch_id} didaftarkan ke registri.")
    return 0


def _avoided_part_c(value, bp, blocked):
    """Fingerprint Part C dari batch "seed:paket" yang masih dibuat proses lain, jadi belum ada di registri."""
    seed, paket = (int(x) for x in value.split(":"))
    return {f"LISC:{group['topic']['id']}#1" for entry in plan_listening(bp, seed, paket, blocked) for group in entry["C"]}


def cmd_part_c(args):
    bp = load_blueprint()
    per_group = bp["sections"]["listening"]["parts"]["C"]["per_group"]
    if args.soal % per_group:
        sys.exit(f"Jumlah soal Part C harus kelipatan {per_group}, karena setiap kuliah berisi {per_group} soal.")
    batch_id = f"part-c-{args.seed}"
    registered = blocked_fingerprints(load_registry(), except_batch=batch_id)
    blocked = set(registered)
    for value in args.hindari:
        blocked |= _avoided_part_c(value, bp, registered)
    out = Path(args.out) / batch_id
    client = None
    client_lock = threading.Lock()

    def get_client():
        nonlocal client
        with client_lock:
            if client is None:
                client = ClaudeClient(args.model, args.effort)
            return client

    source = cache_only if args.cache_only else get_client
    try:
        groups = plan_part_c_set(bp, args.seed, args.soal // per_group, blocked)
        items = generate_part_c_set(groups, bp, out / "cache" / "listening", source)
        made = render_items(items, out / "P1" / "audio", EdgeTTS())
        print(f"Audio: {made} file dibuat, {len(items) - made} dipakai ulang")
        sim_issues = []
        if args.simulate:
            simulate_section("listening", [items], out / "cache" / "simulasi", source, effort=args.sim_effort)
            sim_issues = summarize("listening", [items])
    except (GenerationError, LLMError, TTSError) as e:
        _print_usage(client)
        sys.exit(f"Gagal menyusun set Part C: {e}\nHasil yang sudah jadi tersimpan di cache; jalankan perintah yang sama untuk melanjutkan.")
    _print_usage(client)

    issues = check_part_c_set(items, bp, blocked) + sim_issues
    info = {
        "batch": batch_id, "seed": args.seed, "paket": 1, "sections": "listening", "versi_pustaka": library_version(),
        "model": args.model if client else "-", "audio": EdgeTTS.name,
        "biaya_api_usd": round(client.cost_usd(), 2) if client else 0,
        "dibuat": datetime.now().isoformat(timespec="seconds"), "fingerprint_diblok": len(blocked),
        "label": f"Latihan Part C, {args.soal} soal",
    }
    if args.cache_only and (out / "batch.json").exists():
        previous = json.loads((out / "batch.json").read_text(encoding="utf-8"))["info"]
        info.update(model=previous["model"], biaya_api_usd=previous["biaya_api_usd"])
    sections = {"listening": [items]}
    write_section_workbook(out / "P1" / "P1_listening.xlsx", items, batch_id, args.seed)
    write_section_word(out / "P1" / "P1_listening_siadu.docx", items, "listening", 1, args.seed, label=info["label"])
    write_paket_zips(out, 1)
    write_summary(out / "ringkasan_batch.xlsx", info, sections, issues)
    write_archive(out / "batch.json", info, sections)

    n_err = sum(level == ERROR for level, _ in issues)
    for level, msg in issues:
        print(f"[{level}] {msg}")
    print(f"Hasil: {out}")
    print(f"QC: {n_err} error, {len(issues) - n_err} peringatan")
    if n_err:
        print("Set tidak didaftarkan ke registri karena ada error QC.")
        return 1
    if args.no_register:
        print("Registri tidak diubah (--no-register).")
    else:
        registry = load_registry()
        register_batch(registry, batch_id, {k: info[k] for k in ("seed", "paket", "versi_pustaka", "dibuat")}, items)
        save_registry(registry)
        print(f"Set {batch_id} didaftarkan ke registri.")
    return 0


def _print_usage(client):
    if client and client.usage["calls"]:
        u = client.usage
        print(f"Claude API ({client.model}): {u['calls']} panggilan, input {u['input']:,} token, "
              f"output {u['output']:,} token, baca cache {u['cache_read']:,} token, "
              f"perkiraan biaya ${client.cost_usd():.2f}")


def cmd_check_library(args):
    bp = load_blueprint()
    library = load_library()
    errors = validate_library(library)
    for e in errors:
        print(f"[ERROR] {e}")
    blocked = blocked_fingerprints(load_registry())
    paket = bp["paket_per_batch"]
    print(f"Versi pustaka {library_version()}: {len(library)} famili, "
          f"{sum(len(f.frames) for f in library.values())} frame. Fingerprint terpakai: {len(blocked)}.")
    print(f"{'part':<20}{'level':<8}{'frame':>6}{'sisa soal':>11}{'per batch':>11}{'cukup utk':>11}")
    for fmt in FORMATS:
        need = level_counts(bp["sections"]["structure"]["parts"][fmt]["items"], bp["level_mix"])
        for level in LEVELS:
            frames = [fr for fam in library.values() for fr in fam.frames_for(fmt, level)]
            left = sum(fr.fingerprint(v) not in blocked for fr in frames for v in fr.variants())
            per_batch = need[level] * paket
            print(f"{fmt:<20}{level:<8}{len(frames):>6}{left:>11}{per_batch:>11}{left / per_batch:>10.1f}x")

    print(f"\n{'bank topik':<28}{'sisa':>6}{'per batch':>11}{'cukup utk':>11}")
    reading_topics = load_reading_topics()
    used_read = used_topics(blocked, "READ:")
    for field, items in reading_topics.items():
        left = sum(t["id"] not in used_read for t in items)
        print(f"{'Reading ' + field:<28}{left:>6}{paket:>11}{left / paket:>10.1f}x")
    listening_topics = load_listening_topics()
    parts = bp["sections"]["listening"]["parts"]
    for part, key in (("B", "part_b"), ("C", "part_c")):
        used = used_topics(blocked, f"LIS{part}:")
        left = sum(t["id"] not in used for t in listening_topics[key])
        need = parts[part]["items"] // parts[part]["per_group"] * paket
        print(f"{'Listening Part ' + part:<28}{left:>6}{need:>11}{left / need:>10.1f}x")
    return 1 if errors else 0


def cmd_review_html(args):
    try:
        path, size_mb, missing = build_review_html(args.batch, args.paket, args.out)
    except (FileNotFoundError, ValueError) as e:
        sys.exit(f"Gagal membuat file QC: {e}")
    print(f"File QC: {path} ({size_mb:.1f} MB)")
    if missing:
        print(f"[WARN] {len(missing)} file audio tidak ditemukan: {', '.join(missing[:5])}")
    return 0


def site_dir(tanpa_sandi):
    """Versi lokal tanpa sandi dan versi deploy terenkripsi tidak pernah berbagi folder."""
    return ROOT / "output" / ("situs-lokal" if tanpa_sandi else "situs")


def _print_check(report):
    print(f"Isi folder deploy: {report['files']} file, {report['size_mb']:.1f} MB (file terbesar {report['largest_mb']:.1f} MB)")
    if report["parts_mb"]:
        print("  " + ", ".join(f"{part} {mb:.1f} MB" for part, mb in sorted(report["parts_mb"].items(), key=lambda kv: -kv[1])))
    for warning in report["warnings"][:10]:
        print(f"[WARN] {warning}")
    for problem in report["problems"]:
        print(f"[MASALAH] {problem}")
    if report["problems"]:
        print("Belum siap di-deploy.")
    else:
        try:
            folder = report["out"].resolve().relative_to(ROOT)
        except ValueError:
            folder = report["out"]
        print(f"Siap di-deploy: commit dan push {folder.as_posix()} ke GitHub, Vercel akan deploy otomatis.")


def cmd_site(args):
    password = None if args.tanpa_sandi else os.environ.get(PASSWORD_ENV, "")
    out = Path(args.out) if args.out else site_dir(args.tanpa_sandi)
    try:
        result = build_site([Path(b) for b in args.batch], out, password)
    except (FileNotFoundError, SiteError) as e:
        sys.exit(f"Gagal membuat website: {e}")
    print(f"Website: {result['out']} ({result['files']} file, {result['size_mb']:.1f} MB)")
    print("Bank: " + ", ".join(f"{n} {section}" for section, n in result["forms"].items()) + f", {result['practice']} set latihan")
    if args.tanpa_sandi:
        print("[WARN] Website ini tanpa kata sandi dan memuat kunci jawaban. Jangan diunggah ke internet.")
    if result["missing"]:
        print(f"[WARN] {len(result['missing'])} file audio tidak ditemukan: {', '.join(result['missing'][:5])}")
    if not args.tanpa_sandi:
        _print_check(check_site(out, password))
    return 0


def cmd_check_site(args):
    report = check_site(Path(args.dir) if args.dir else site_dir(False), os.environ.get(PASSWORD_ENV, ""))
    _print_check(report)
    return 1 if report["problems"] else 0


def main(argv=None):
    load_env()
    parser = argparse.ArgumentParser(prog="toefl_gen", description="Generator soal TOEFL ITP")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Buat satu batch paket soal")
    gen.add_argument("--seed", type=int, required=True)
    gen.add_argument("--paket", type=int, help="jumlah paket (default dari blueprint)")
    gen.add_argument("--sections", default="structure", help="dipisah koma: listening,structure,reading")
    gen.add_argument("--no-audio", action="store_true", help="buat naskah Listening tanpa file audio")
    gen.add_argument("--simulate", action="store_true", help="jalankan simulasi peserta 0/50/80%% lewat Claude API")
    gen.add_argument("--sim-effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    gen.add_argument("--cache-only", action="store_true",
                     help="susun ulang dari cache tanpa memanggil Claude API, walau prompt sudah berubah")
    gen.add_argument("--out", default=str(ROOT / "output"))
    gen.add_argument("--no-register", action="store_true", help="jangan catat batch ke registri")
    gen.add_argument("--model", default=DEFAULT_MODEL, help="model Claude untuk Reading")
    gen.add_argument("--effort", default=DEFAULT_EFFORT, choices=["low", "medium", "high", "xhigh", "max"])
    gen.set_defaults(func=cmd_generate)

    pc = sub.add_parser("part-c", help="Buat set latihan Listening Part C saja, bernomor dari 1")
    pc.add_argument("--seed", type=int, required=True)
    pc.add_argument("--soal", type=int, default=120, help="jumlah soal, kelipatan 4 (default 120, yaitu 30 kuliah)")
    pc.add_argument("--hindari", action="append", default=[], metavar="SEED:PAKET",
                    help="hindari topik Part C batch yang masih dibuat proses lain, misalnya 2028:3")
    pc.add_argument("--simulate", action="store_true", help="jalankan simulasi peserta 0/50/80%% lewat Claude API")
    pc.add_argument("--sim-effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    pc.add_argument("--cache-only", action="store_true", help="susun ulang dari cache tanpa memanggil Claude API")
    pc.add_argument("--no-register", action="store_true", help="jangan catat set ke registri")
    pc.add_argument("--out", default=str(ROOT / "output"))
    pc.add_argument("--model", default=DEFAULT_MODEL)
    pc.add_argument("--effort", default=DEFAULT_EFFORT, choices=["low", "medium", "high", "xhigh", "max"])
    pc.set_defaults(func=cmd_part_c)

    chk = sub.add_parser("check-library", help="Validasi pustaka famili dan hitung kapasitasnya")
    chk.set_defaults(func=cmd_check_library)

    rev = sub.add_parser("review-html", help="Buat satu file HTML untuk QC (mode Peserta dan Peninjau)")
    rev.add_argument("--batch", required=True, help="folder batch, misalnya output/seed-2026")
    rev.add_argument("--paket", type=int, default=1)
    rev.add_argument("--out", help="lokasi file (default: QC_P<paket>.html di folder batch)")
    rev.set_defaults(func=cmd_review_html)

    web = sub.add_parser("site", help="Buat website generator terenkripsi dari bank soal")
    web.add_argument("--batch", action="append", required=True, help="folder batch; boleh diulang untuk beberapa batch")
    web.add_argument("--out", help="folder website (default output/situs, atau output/situs-lokal untuk --tanpa-sandi)")
    web.add_argument("--tanpa-sandi", action="store_true", help="versi lokal tanpa enkripsi; jangan diunggah ke internet")
    web.set_defaults(func=cmd_site)

    cek = sub.add_parser("cek-situs", help="Periksa folder website terenkripsi sebelum di-deploy ke Vercel")
    cek.add_argument("--dir", help="folder website (default output/situs)")
    cek.set_defaults(func=cmd_check_site)

    args = parser.parse_args(argv)
    return args.func(args)
