# Standar Soal TOEFL ITP — TOEFL Academy

Standar ini dipakai saat menulis famili soal, saat generator membuat soal, dan saat QC.
Sumber: PRD Generator Soal TOEFL ITP dan temuan dari tryout 3892/3889 di Markaz.

## 1. Susunan paket

| Section | Part | Nomor | Isi |
|---|---|---|---|
| Listening | A | 1–30 | Percakapan pendek 2 orang, 1 soal per percakapan |
| Listening | B | 31–38 | 2 percakapan panjang × 4 soal |
| Listening | C | 39–50 | 3 kuliah/monolog × 4 soal |
| Structure & WE | Structure | 1–15 | Melengkapi kalimat |
| Structure & WE | Written Expression | 16–40 | Menemukan 1 bagian yang salah dari 4 bagian bertanda |
| Reading | – | 1–50 | 5 teks akademik 250–350 kata, 8–12 soal per teks |

Angka yang mengikat ada di `config/blueprint.yaml`.

## 2. Aturan umum semua soal

- Empat opsi (A–D), tepat satu jawaban benar.
- Konteks akademik atau kehidupan kampus. Hindari topik sensitif (politik praktis, SARA, kekerasan).
- Opsi sejajar bentuk, panjang, dan kerinciannya. Dalam satu teks atau kelompok soal, opsi benar paling
  banyak 40% menjadi yang terpanjang. Uji nyata pertama: tanpa batas ini angkanya 48% di Reading, dan persona
  yang hanya menebak benar di 24 dari 24 soal itu. Opsi benar tidak memakai pola "X or Y".
- Peserta yang hanya melihat opsi, tanpa soal atau teks, tidak boleh bisa menebak jawabannya.
- Pengecoh harus salah dengan alasan yang bisa dijelaskan, bukan sekadar aneh.
- Dalam satu teks atau kelompok soal, opsi benar tidak boleh menjadi satu-satunya yang saling menguatkan. Istilah yang
  berulang di opsi benar juga muncul di pengecoh soal lain. Aturan ini baru ada di prompt Reading dan Listening, belum
  diperiksa validator, dan belum diuji dengan API.
- Tidak menyalin soal dari buku persiapan atau soal resmi ETS.
- Level: Mudah, Sedang, Sulit. Label "Hots" tidak dipakai untuk TOEFL.

## 3. Structure & Written Expression

**Structure (melengkapi kalimat)**
- Satu rumpang ditulis `___`.
- Ketiga pengecoh menguji kesalahan yang umum: bentuk kata kerja, jumlah, urutan kata, klausa ganda.

**Written Expression (mencari kesalahan)**
- Empat bagian ditandai dengan huruf tepat sesudahnya, misalnya `works(B)`.
- Tepat satu bagian salah. Tiga bagian lain benar dalam kalimat itu.
- Kesalahan cukup diperbaiki dengan mengganti bagian itu saja.

**Topik yang disebar** (paling banyak 4 soal per topik per paket): subject-verb agreement, tenses,
passive voice, gerund/infinitive, adjective clause, reduced clause, noun clause, parallel structure,
comparison, inversion, conditional, word form, noun & quantifier, preposition, conjunction,
sentence completeness, pronoun.

## 4. Listening

- Naskah memakai label pembicara: `MAN`, `WOMAN`, `PROFESSOR`, `NARRATOR`.
- Pertanyaan selalu dibacakan narator dalam bahasa Inggris.
- Kolom soal di Excel berisi "Listen to the audio carefully."; opsi ada di kolom opsi.
- Part A memakai jenis yang bervariasi: makna tersirat, saran, idiom, kalimat negatif, pengandaian,
  perasaan pembicara, rencana berikutnya.
- Pengecoh tidak boleh menyalin kalimat dari naskah.
- Standar audio natural ada di PRD (bagian Audio Listening).

## 5. Reading

- Teks akademik orisinal, 250–350 kata, bertopik berbeda dari kuliah Listening di paket yang sama.
- Tipe soal dicampur: main idea, detail, inference, vocabulary, reference, author's purpose,
  NOT/EXCEPT, organisasi teks. Soal tone/attitude paling banyak 2 per paket.
- Soal vocabulary dan reference menyebut paragrafnya.

## 6. Format pembahasan

Format dari tim akademik, berlaku untuk semua section:

```
Jawaban: B
Pembahasan:

Soal ini membahas <konsep>. <Mengapa opsi benar paling sesuai, ditulis mengalir.>

* Opsi A keliru karena ...
* Opsi C keliru karena ...
* Opsi D keliru karena ...

Cara cepat:
<Cara umum menjawab soal sejenis.>
```

- **Jawaban** hanya berisi huruf.
- **Paragraf penjelasan** ditulis mengalir, tanpa label dan tanpa titik dua. Isinya konsep yang diuji dan alasan opsi
  benar paling sesuai.
- **Opsi yang salah** ditulis sebagai poin. Alasannya menjelaskan letak kelirunya, bukan hanya mengulang isi teks.
- **Cara cepat** menjelaskan cara menjawab soal sejenis secara umum, tidak terikat situasi di teks. Isinya ditulis
  sekali per famili atau tipe soal, di `cara_cepat` pada `data/families/structure_we.yaml`,
  `data/reading/question_types.yaml`, dan `data/listening/question_types.yaml`.

Tambahan per section:

- **Listening**: blok `Transkrip Audio:` berisi ucapan berlabel pembicara, tepat setelah baris `Pembahasan:`.
- **Reading dan Listening Part B/C**: paragraf penjelasan ditutup dengan kutipan bukti dari teks atau naskah.
- **Written Expression**: paragraf penjelasan menyebut bagian yang keliru dan bentuk yang benar. Poin opsi lain
  menyatakan bahwa bagian itu sudah benar.

## 7. Aturan QC otomatis

| Aturan | Batas |
|---|---|
| Jumlah soal per part | Sesuai blueprint |
| Sebaran kunci per section | Tiap huruf 20–30% |
| Kunci sama berturut-turut | Paling banyak 3 |
| Level per part | Sesuai `level_mix` |
| Topik per paket | Paling banyak 4 soal per topik |
| Duplikat | 0 soal kembar dalam batch dan dengan batch sebelumnya (registri) |
| Frame yang sama dalam satu paket | Tidak boleh |
| Pembahasan | Mengikuti format bagian 6: kunci sama, semua opsi salah dijelaskan, ada Cara cepat, tanpa label lama |
| Penjelasan buatan Claude | Minimal 20 kata dan tanpa titik dua; alasan tiap opsi salah minimal 8 kata; tidak menyebut huruf opsi karena opsi dipindahkan setelah ditulis |
| Opsi benar paling panjang | Per teks/kelompok paling banyak 40%; per paket diperingatkan di atas 35% |

**Simulasi peserta (`--simulate`) adalah alat bantu, bukan ukuran kesulitan.** Personanya Claude, jadi skor 80% yang
selalu benar hanya berarti tidak ada kunci yang terdeteksi salah. Skor persona yang hanya melihat opsi dibandingkan
dengan tryout 3892 (Listening 68%, Structure & WE 40%, Reading 84%), bukan dengan tebakan acak 25%. Level yang akurat
tetap perlu data jawaban peserta sungguhan.

Skor persona hanya-opsi tinggi terutama karena ia melihat semua opsi satu teks atau kelompok sekaligus. Saat diuji satu
soal per prompt (November 2026, satu kali jalan), skor Reading turun dari 94% ke 50% pada seed 2027 dan dari 84% ke 64%
pada tryout 3892. Skor Part C turun dari 100% ke 58% pada seed 2027 dan dari 58% ke 42% pada tryout 3892 (12 soal per
paket). Jadi skor berkelompok yang tinggi belum berarti kunci bisa ditebak dari satu soal, dan selisih dengan tryout 3892
per soal belum bermakna secara statistik.
