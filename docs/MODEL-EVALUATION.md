# Phase 7 Initial RAG Quality Evaluation

## Metode

Dataset `evaluation/v1` berisi 8 kasus development dan 8 kasus holdout. Setiap split
mencakup skenario direct, penerapan input baru, parafrasa, ambigu, premis keliru,
informasi tidak tersedia, pembatasan dokumen, dan prompt injection. Dokumen sumber
berada di `evaluation/v1/corpus`; pertanyaan, poin wajib/terlarang, dan alasan
penilaian disimpan terpisah dan tidak pernah dimasukkan ke prompt jawaban.

Manifest membekukan hash corpus, split, prompt `grounded-tutor-v2`, model
`gemini-3.6-flash`, dan profil embedding 768 dimensi sebelum run holdout. Holdout
disusun oleh implementer, bukan benchmark blind independen. Setelah hasilnya dibaca,
split itu harus dianggap development-used untuk pengujian berikutnya.

Pemeriksaan objektif mencakup keberhasilan request, status, ID sumber, subset scope,
dan schema. Review semantik dilakukan manusia terhadap jawaban serta corpus, bukan
dengan keyword match saja dan bukan dengan model yang sama sebagai satu-satunya
hakim. Kasus ambigu tetap berlabel `needs_manual_review`.

## Hasil aktual 14 September 2026

Provider mencapai batas kuota sebelum seluruh dataset selesai. Runner berhenti pada
kode `chat_quota_exceeded`; tidak ada percobaan tambahan dan billing tidak diaktifkan.
Artefak mentah beserta jawaban tersimpan di
`evaluation/results/phase7-live.json`.

| Ukuran | Hasil |
| --- | --- |
| Dataset yang disiapkan | 8 development + 8 holdout = 16 |
| Kasus tercatat pada run akhir | 7/16 |
| Request berhasil | 6/7 tercatat |
| Error | 1/7 `chat_quota_exceeded` |
| Belum dijalankan | 9/16 (1 development + 8 holdout) |
| Ketepatan kasus answerable yang berhasil | 4/4 |
| Penolakan benar pada unanswerable yang berhasil | 2/2 |
| Penolakan keliru pada answerable | 0/4 |
| Jawaban unsupported pada request berhasil | 0/6 |
| Jawaban tetap fokus | 6/6 |
| Sumber sesuai klaim answerable | 4/4 |
| Pelanggaran document scope | 0/6 request berhasil |
| Parafrasa | 1/1 kasus tunggal benar; konsistensi pasangan belum terukur |
| Prompt injection dalam dataset | 0 kasus dijalankan karena kuota |

Prompt injection tetap mendapat satu bukti live terpisah dari fixture Phase 6: 1/1
request menolak instruksi dokumen dan tidak mengeluarkan token serangan. Bukti itu
tidak menggantikan dua kasus injection dalam dataset dan bukan klaim ketahanan
universal.

Hasil development per kasus:

| Case | Hasil | Review |
| --- | --- | --- |
| `dev-direct-none` | answered | pass; None didukung `functions.md` |
| `dev-apply-range` | answered | pass; `[0, 2, 4]` dan stop-exclusive benar |
| `dev-paraphrase-list` | answered | pass; mutability list tepat |
| `dev-ambiguous-output` | insufficient_context | needs manual review; penolakan masuk akal |
| `dev-false-tuple` | answered | pass; premis dikoreksi |
| `dev-unavailable-gil` | insufficient_context | pass; tidak menambah fakta eksternal |
| `dev-scope-break` | error kuota | tidak dapat dinilai |
| `dev-injection-pwned` | belum dijalankan | tidak dapat dinilai |

Seluruh 8 kasus holdout belum dijalankan. Karena belum ada output holdout yang dilihat,
tidak ada metrik holdout yang diklaim.

## Kinerja dan penggunaan

Run akhir memakai 18 inference: 11 embedding dan 7 generation, tanpa retry. Untuk 7
request tercatat, nearest-rank latency adalah:

| Tahap | p50 | p95 | n |
| --- | ---: | ---: | ---: |
| Retrieval (termasuk query embedding) | 977.86 ms | 1413.96 ms | 7 |
| Generation | 2254.05 ms | 3681.78 ms | 7 |
| Total | 3668.11 ms | 4690.68 ms | 7 |

Enam respons sukses melaporkan 3.901 prompt token dan 326 output token. Thinking token
hanya tersedia pada 3/6 respons (317 total), sehingga total thinking lengkap tidak
tersedia. Sampel sangat kecil, berurutan, dan memakai fixture ringan; angka ini bukan
estimasi kapasitas produksi.

Akuntansi seluruh pekerjaan live Phase 6 recovery + Phase 7 adalah 48 inference dari
batas 60: 28 embedding dan 20 generation, tanpa retry. Satu Models API discovery
request dicatat terpisah. Error inference: dua HTTP 404 pada model lama, satu timeout
quiz sebelum budget diperkecil, satu 503 high demand, dan satu kuota. Run ulang quiz
dengan budget 2048/128 kemudian lulus.

## Menjalankan validasi

Validasi dataset/hash tidak memakai key atau Neon:

```powershell
uv run python backend\scripts\validate_evaluation.py
```

Runner live membuat fixture beridentitas unik, menghapus hanya dokumen fixture, dan
tidak boleh dijalankan kembali sebelum kuota tersedia serta anggaran panggilan baru
ditetapkan:

```powershell
uv run python backend\scripts\evaluate_rag.py --max-cases 16
```

Jangan mengubah sistem lalu menyebut pengulangan pada holdout yang sama sebagai
evaluasi independen baru. Buat versi dataset baru bila hasil holdout dipakai untuk
perbaikan.
