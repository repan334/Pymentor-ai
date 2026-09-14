# Phase 8 Topic Progress and Recommendations

## Model data

Topic memakai ID slug eksplisit dan stabil, misalnya `python-functions`. ID tidak
berubah ketika nama tampil berubah. Setiap quiz baru wajib membawa tepat satu
`topic_id`; field teks `topic` pada quiz tetap menjadi snapshot prompt generation dan
tidak ditulis ulang ketika assignment berubah.

Quiz dari revision `0004` tetap valid dengan `topic_id=null`. Saat topic dibuat,
backend hanya mengisi quiz legacy yang belum ditetapkan bila normalisasi nama snapshot
(case-insensitive dan whitespace tunggal) tepat sama dengan display name topic. Nama
yang tidak cocok persis dianggap ambigu dan dibiarkan unassigned. Gunakan endpoint
assignment untuk keputusan manual.

## Perhitungan

Progress tidak memakai counter tersimpan. Query memilih satu attempt final terbaru
per quiz dengan urutan deterministik `created_at DESC, id DESC`, lalu menjumlahkan
`correct_count` dan `total_questions` dari attempt terpilih.

`score = correct_questions / counted_questions * 100`, dibulatkan half-up ke dua
desimal. Mengulang quiz mengganti kontribusi quiz itu dan tidak menambah jumlah soal
bukti. Replay idempotent memakai attempt yang sama sehingga tidak mengubah hasil.

Aturan rekomendasi:

| Bukti/skor | Recommendation |
| --- | --- |
| 0 soal | `insufficient_evidence`, score `null` |
| 1-4 soal | `insufficient_evidence` |
| >=5 dan score <60 | `review_material` |
| >=5 dan 60 <= score <80 | `practice_more` |
| >=5 dan 80 <= score <=100 | `try_advanced` |

Score adalah performa latihan pada quiz yang dihitung, bukan mastery yang tervalidasi
secara ilmiah. Aturan tidak memanggil model dan tidak memilih difficulty quiz secara
adaptif.

## Endpoint

- `POST /api/v1/topics`: buat ID stabil; respons menyebut jumlah quiz legacy exact-match.
- `GET /api/v1/topics?limit=20&offset=0`: daftar berbatas.
- `GET /api/v1/topics/{topic_id}`: detail topic.
- `PUT /api/v1/quizzes/{quiz_id}/topic`: assign/reassign tanpa mengubah snapshot quiz.
- `GET /api/v1/topics/{topic_id}/progress`: score, evidence, dan recommendation.

Membuat topic dan mencoba progress dari PowerShell 5.1:

```powershell
$topic = @{
    id = "python-functions"
    display_name = "Fungsi Python"
    description = "Latihan return dan parameter"
} | ConvertTo-Json
Invoke-RestMethod -Method Post `
    -Uri "http://127.0.0.1:8000/api/v1/topics" `
    -ContentType "application/json" -Body $topic

$assignment = @{ topic_id = "python-functions" } | ConvertTo-Json
Invoke-RestMethod -Method Put `
    -Uri "http://127.0.0.1:8000/api/v1/quizzes/10/topic" `
    -ContentType "application/json" -Body $assignment

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/api/v1/topics/python-functions/progress"
```

Contoh tanpa attempt:

```json
{
  "topic_id": "python-functions",
  "topic_name": "Fungsi Python",
  "score": null,
  "counted_questions": 0,
  "counted_quizzes": 0,
  "recommendation": "insufficient_evidence",
  "message": "Belum cukup soal yang dihitung untuk memberi rekomendasi berbasis latihan."
}
```
