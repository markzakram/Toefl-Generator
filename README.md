# Generator Soal TOEFL ITP

Generator paket soal TOEFL ITP untuk TOEFL Academy. Satu kali jalan menghasilkan beberapa paket
setara (default 5) dalam format Excel impor SiAdu. Acuan produk: PRD di Claude Docs. Acuan isi soal:
[docs/standar-toefl-itp.md](docs/standar-toefl-itp.md).

| Section | Status |
|---|---|
| Structure & Written Expression | Siap (template famili, tanpa API) |
| Reading | Siap secara kode, butuh Claude API; belum diuji dengan API sungguhan |
| Listening + audio | Naskah siap secara kode (butuh Claude API, belum diuji dengan API sungguhan); audio edge-tts sudah diuji nyata |

## Persiapan

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

## Membuat batch

```bash
.venv\Scripts\python -m toefl_gen generate --seed 2026
```

- `--paket N` mengganti jumlah paket (default dari `config/blueprint.yaml`).
- `--no-register` membuat batch uji tanpa mencatatnya ke registri.
- Seed yang sama dengan versi pustaka dan registri yang sama selalu menghasilkan batch yang sama.

Hasilnya ada di `output/seed-<seed>/`:

| File | Isi |
|---|---|
| `P1/P1_structure.xlsx` … `P5/...` | Sheet `SOAL` (format SiAdu) dan sheet `META` (famili, frame, fingerprint, status) |
| `P1/P1_structure_siadu.docx` … `P5/...` | Word format input SiAdu untuk tim input |
| `P1/audio/` | File mp3 Listening, satu per soal |
| `P1_paket_input.zip` | Word, Excel, audio, dan petunjuk input satu paket |
| `P1_audio.zip` | Hanya audio satu paket |
| `ringkasan_batch.xlsx` | Info batch, statistik per paket, daftar semua soal, hasil QC |
| `batch.json` | Arsip lengkap batch |

Batch yang lolos QC otomatis dicatat di `data/registry.json`. Soal yang sudah tercatat tidak akan
muncul lagi di batch dengan seed lain.

### Reading (lewat Claude API)

```bash
.venv\Scripts\python -m toefl_gen generate --seed 2026 --sections structure,reading
```

- Butuh `ANTHROPIC_API_KEY`. Isi di file `.env` di folder proyek (contoh di `.env.example`); file ini
  dibaca otomatis saat CLI berjalan dan sudah dikecualikan di `.gitignore`. Variabel yang sudah ada di
  environment tidak ditimpa.
- Model default `claude-opus-5-5` dengan effort `high`; bisa diganti dengan `--model` dan `--effort`.
  Fallback sisi server (`fallbacks: "default"`) aktif, jadi permintaan yang ditolak model otomatis
  dilanjutkan model lain dalam panggilan yang sama.
- Setiap teks divalidasi (jumlah kata, bukti kutipan ada di teks, kata yang ditanya ada di paragrafnya,
  NOT/EXCEPT kapital). Kalau gagal, Claude diminta menulis ulang dengan umpan balik, paling banyak 3 kali.
- Teks yang sudah jadi disimpan di `output/seed-<seed>/cache/reading/`. Kalau proses terhenti, jalankan
  perintah yang sama untuk melanjutkan tanpa biaya ulang.
- Perkiraan biaya dicetak di akhir dan dicatat di `ringkasan_batch.xlsx`.
- Tipe soal ada di `data/reading/question_types.yaml`, bank topik di `data/reading/topics.yaml`.

### Listening (naskah lewat Claude API, audio lewat edge-tts)

```bash
.venv\Scripts\python -m toefl_gen generate --seed 2026 --sections listening,structure,reading
```

- Part A (30 percakapan pendek) dibuat 10 per panggilan; Part B (2 percakapan) dan Part C (3 kuliah)
  satu panggilan per naskah. Validator menolak opsi yang menyalin kalimat naskah, pertanyaan yang tidak
  menyebut pembicara kedua, kutipan bukti yang tidak ada di naskah, dan panjang naskah di luar batas.
- Audio: satu file mp3 per soal di `output/seed-<seed>/P#/audio/`, nama `P1_L_A_001.mp3`. Nama file
  juga tercatat di kolom `file_audio` sheet `META`. `--no-audio` membuat naskah saja.
- `audio_mode` di blueprint: `first` (percakapan Part B/C hanya di file soal pertama tiap kelompok,
  seperti tes asli) atau `every` (diulang di setiap file soal).
- Suara memakai peran (male1/male2/female1/female2/narrator) yang dipetakan oleh mesin TTS di
  `toefl_gen/tts.py`. Mesin lain (misalnya Voicemaker) cukup ditambahkan sebagai kelas baru.
- Bahan ada di `data/listening/question_types.yaml` dan `data/listening/topics.yaml`.

## Paket untuk tim input

Kirim `P1_paket_input.zip`, atau minta tim mengunduhnya dari website di bawah. Isinya file Word, file Excel, folder
`audio/`, dan `CARA_INPUT.txt`. Word dan Excel hanya berisi teks, jadi audio tetap berupa file terpisah. Setiap soal Listening di Word menyebut nama file-nya di baris `File audio:`, dan nomor di nama
file sama dengan nomor soal. Contohnya, `Soal 1` memakai `P1_L_A_001.mp3`. Di Excel, nama file ada di kolom `file_audio`
pada sheet `META`.

Alur input satu soal Listening:

1. Masukkan teks soal, opsi, kunci, level, dan pembahasan.
2. Ubah tipe soal menjadi audio di form SiAdu, lalu unggah file yang namanya tertulis di soal itu.
3. Simpan.

Kalau memakai SiAdu Auto Input v2.7.1:

- Unggah file Excel, bukan Word. Pembaca Word di skrip itu hanya menerima opsi A–E atau A–F, sehingga Word TOEFL dengan
  opsi A–D ditolak. Mengisi lewat Word baru bisa kalau batas itu dilonggarkan.
- Skrip selalu mengisi tipe soal sebagai teks. Untuk Listening, pakai `Isi 1 Soal Tanpa Simpan`, lalu lanjutkan langkah 2
  dan 3 di atas secara manual. Antrean simpan otomatis akan menyimpan soal tanpa audio.

Baris `Category`, `Lesson`, dan `Chapter` di Word masih usulan generator dan perlu dicocokkan dengan nama di bank soal.

## Website generator

Tim mengisi seed, jumlah paket, dan section, lalu website menyusun tryout dari bank soal. Tidak perlu server, API key,
atau biaya per generate, karena semua berjalan di browser. Hasilnya bisa diunduh sebagai paket lengkap (ZIP), semua
audio (ZIP), file HTML tryout, Word, Excel, atau satu mp3. Ada juga daftar kerja audio dengan pemutar, centang "sudah
diinput", penghitung kemajuan, dan saringan. Centang tersimpan di browser masing-masing, jadi tidak terbagi antaranggota
tim dan hilang kalau data browser dibersihkan.

**Cara kerja bank.** Setiap section dari setiap paket di batch menjadi satu "bentuk", misalnya `Listening 2`. Seed memilih
kombinasi bentuk, dan seed yang sama selalu menghasilkan susunan yang sama selama isi bank tidak berubah. Ganti seed
hanya mengubah kombinasi. Soal baru hanya bertambah kalau bank ditambah. Satu generate paling banyak sejumlah bentuk
tersedikit di section yang dipilih, supaya soal antarpaket tidak berulang. Batch berlabel, seperti `part-c`, tampil sebagai
set latihan dan tidak ikut kombinasi.

**Tampilan.** Website dan file HTML tryout memakai gaya yang sama. Tata letaknya mengikuti SKD Generator: sidebar atau
bilah atas berlogo, panel putih, huruf jawaban berbentuk kotak, serta font Manrope dan DM Sans. Warnanya dari logo
TOEFL Academy. Di mode terang, navy `#262364` dipakai untuk tombol dan judul. Di mode gelap, latarnya navy sangat gelap,
tombolnya navy yang dicerahkan (`#5753D1`), dan judulnya putih kebiruan. Merah `#ED2B2D` menjadi aksen di kedua mode.
Logo dan font ada di `toefl_gen/assets` (`branding.py`) dan disematkan saat build, jadi halaman tidak memuat apa pun
dari luar dan file tryout tetap utuh tanpa internet. Untuk mengganti logo, timpa `assets/logo.png` dan
`assets/logo-mark.png`, lalu bangun ulang website dan file tryout.

**Menambah bank.** Buat batch baru, lalu sertakan folder batch-nya saat membangun website. Structure bisa ditambah tanpa
biaya API dengan `generate --sections structure`. Reading dan Listening memakai Claude API.

Isi website dienkripsi dengan kata sandi, jadi aman ditaruh di host statis mana pun, termasuk yang bisa dibuka publik.

1. Isi `SITUS_PASSWORD` di `.env`, minimal 12 karakter. Sebaiknya panjang dan acak, karena file terenkripsi bisa
   diunduh siapa saja yang tahu alamatnya.
2. Bangun website ke `output/situs`. `--batch` diulang untuk setiap batch di bank. Setelah selesai, perintah ini langsung
   menjalankan pemeriksaan sebelum deploy:

```bash
.venv\Scripts\python -m toefl_gen site --batch output/tryout-3/seed-2028 --batch output/bank/seed-3001 --batch output/bank/seed-3002 --batch output/part-c-120/part-c-2029
```

3. Coba di komputer sendiri. Halaman harus dibuka lewat server, bukan dengan klik dua kali:

```bash
.venv\Scripts\python -m http.server 8000 --directory output/situs
```

4. Deploy ke Vercel (lihat di bawah). Alamatnya harus `https`, karena browser hanya membuka enkripsi lewat `https` atau
   `localhost`. Vercel selalu memakai `https`.

Untuk melihat website di komputer sendiri tanpa kata sandi, tambahkan `--tanpa-sandi`. Hasilnya masuk ke folder
terpisah, `output/situs-lokal`:

```bash
.venv\Scripts\python -m toefl_gen site --batch output/tryout-3/seed-2028 --tanpa-sandi
```

Versi ini tidak terenkripsi, memuat kunci jawaban, dan menampilkan peringatan di bagian atas halaman. Jangan diunggah ke
internet. Ada dua pengaman. Foldernya berisi `.vercelignore` yang mengabaikan semua file, dan `--tanpa-sandi` menolak
menulis ke folder yang sudah disiapkan untuk Vercel (ada `vercel.json` atau `.vercel`).

Setiap kali ada batch baru atau kata sandi berubah, bangun ulang dan deploy ulang. Satu kata sandi berlaku untuk semua
orang, jadi kalau ada anggota yang keluar dari tim, kata sandinya perlu diganti.

### Deploy ke Vercel

**Paket Vercel.** Menurut ketentuan layanan Vercel (bagian 4), paket gratis Hobby hanya untuk pemakaian pribadi atau
non-komersial. Website ini alat kerja tim, jadi pakai tim Vercel kantor dengan paket Pro. Batas unggah lewat CLI adalah
100 MB untuk Hobby dan 1 GB untuk Pro, dengan maksimal 15.000 file. Bank sekarang memakai 44 MB: Listening sekitar 6 MB
per bentuk, set latihan Part C 120 soal sekitar 23 MB, Structure dan Reading kecil.

**Yang dibuat otomatis.** Build terenkripsi menulis `vercel.json` berisi header `noindex`, `no-referrer`, `nosniff`,
larangan dibingkai situs lain, dan cache panjang untuk `files/` (nama file acak, jadi aman di-cache). Website ini statis,
tanpa build command dan tanpa environment variable. Kata sandi tidak pernah dikirim ke Vercel.

**Pertama kali**, dengan Node.js terpasang. Vercel CLI dijalankan lewat `npx`, tidak perlu diinstal:

```bash
npx vercel login
```

```bash
npx vercel switch
```

```bash
npx vercel link --cwd output/situs
```

`switch` dipakai untuk memilih tim kantor. Saat `link`, buat proyek baru (misalnya `toefl-generator`) dan biarkan
pengaturan bawaan: framework Other, tanpa build command. Tautan proyek disimpan di `output/situs/.vercel`. Build ulang
tidak menghapusnya, tetapi kalau folder `output/situs` dihapus, jalankan `link` lagi.

**Setiap deploy:**

```bash
.venv\Scripts\python -m toefl_gen cek-situs
```

```bash
npx vercel deploy --prod --cwd output/situs
```

`cek-situs` memakai `SITUS_PASSWORD` dari `.env` untuk membuka setiap file. Pemeriksaan gagal kalau folder berisi versi
tanpa sandi, kata sandi tidak cocok dengan build, ada file lain yang ikut terbawa (misalnya Word yang tidak sengaja
disalin), ada file yang dirujuk tapi hilang atau tidak terenkripsi, atau ukurannya melewati batas Pro. Ukuran di atas
batas Hobby hanya muncul sebagai peringatan. Deploy hanya kalau hasilnya "Siap di-deploy".

`npx vercel deploy` tanpa `--prod` membuat alamat pratinjau. Alamat ini juga terkunci kata sandi, jadi aman dipakai
untuk mencoba sebelum alamat utama diganti. Proteksi bawaan Vercel tidak diperlukan, karena gerbang kata sandinya sudah
ada di halaman.

## Set latihan Listening Part C

Untuk membuat Part C saja, tanpa paket utuh:

```bash
.venv\Scripts\python -m toefl_gen part-c --seed 2029 --soal 120 --simulate
```

Jumlah soal harus kelipatan 4, karena setiap kuliah berisi 4 soal, dan nomornya mulai dari 1. Hasilnya ada di
`output/part-c-<seed>/`, dengan susunan yang sama seperti paket biasa. Audio menyebut nomor soal, misalnya
"Questions 1 through 4". Kalau ada batch lain yang masih berjalan dan belum tercatat di registri, tambahkan
`--hindari SEED:PAKET` supaya topiknya tidak sama, dan `--no-register` supaya catatan registrinya tidak saling menimpa.

## File HTML per tryout

```bash
.venv\Scripts\python -m toefl_gen review-html --batch output/seed-2026 --paket 1
```

Hasilnya satu file `QC_P1.html` di folder batch, atau di lokasi pilihan lewat `--out`. Isinya soal, audio, Word, dan
Excel satu paket, sekitar 9 MB. File ini bisa dibuka tanpa internet dengan klik dua kali.

- **Mode Tim Input:** unduh paket lengkap, semua audio, Word, Excel, atau satu mp3. Ada juga daftar kerja audio dengan
  pemutar, centang "sudah diinput", dan saringan.
- **Mode Peserta:** mengerjakan per section dengan timer, audio, tandai ragu, lalu melihat skor mentah,
  kunci, dan pembahasan.
- **Mode Peninjau:** semua soal dengan kunci, pembahasan, dan jawaban simulasi. Tiap soal bisa diberi status,
  kategori masalah, dan catatan, lalu diunduh sebagai CSV atau JSON. Catatan beberapa peninjau digabung lewat
  Impor catatan JSON.
- Jawaban dan catatan tersimpan di browser masing-masing peninjau, bukan di dalam file. Jangan membuka file
  ini dari folder yang berbeda-beda kalau catatannya belum diunduh, karena browser bisa menganggapnya file lain.
- File ini memuat kunci jawaban, jadi hanya untuk tim peninjau, bukan untuk peserta sungguhan.

## Menyusun ulang tanpa biaya API

Kalau hanya format hasil yang berubah, misalnya format pembahasan, susun ulang batch lama dari cache:

```bash
.venv\Scripts\python -m toefl_gen generate --seed 2026 --sections listening,structure,reading --simulate --cache-only --no-register
```

Teks, opsi, dan alasan tetap dari pembuatan awal, walau prompt sudah berubah. Kalau ada bagian yang belum ada di
cache, perintah ini berhenti dan tidak memanggil API. Teks `Cara cepat` dan kalimat konsep diambil dari file data,
jadi perubahannya langsung ikut.

## Mengecek pustaka famili

```bash
.venv\Scripts\python -m toefl_gen check-library
```

Perintah ini memvalidasi semua frame dan menghitung sisa kapasitas per part dan level.

## Menambah frame

Famili ada di `data/families/structure_we.yaml`. Format penanda:

- **Structure:** satu rumpang `___`, satu `correct`, minimal tiga `distractors` beserta alasannya.
- **Written Expression:** `[teks](m)` untuk bagian benar yang boleh ditandai, `[teks](e:bentuk benar)`
  untuk satu bagian yang salah.
- `{nama}` diisi dari `vars` frame. Usahakan setiap frame punya minimal 6 variasi, supaya satu slot
  bisa terisi di kelima paket.

Setelah mengubah file, jalankan `check-library` dan tes.

## Tes

```bash
.venv\Scripts\python -m pytest -q
```
