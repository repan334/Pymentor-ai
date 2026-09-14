# Phase 7 Quiz Generation and Scoring

## Cakupan dan profil

Phase 7 menyediakan kuis pilihan tunggal berbasis chunk yang sudah eligible untuk
retrieval. Kuis dibuat sinkron dalam satu request dengan profil
`gemini:gemini-3.6-flash:grounded-quiz-v1`. Default `question_count` adalah 3 dan
maksimum MVP adalah 5. Tidak ada difficulty adaptif, mastery, atau rekomendasi;
bagian tersebut tetap milik Phase 8.

Konfigurasi quiz memakai `Settings` yang sama dengan API lain:

| Setting | Default |
| --- | --- |
| `QUIZ_PROMPT_VERSION` | `grounded-quiz-v1` |
| `QUIZ_MAX_TOPIC_CHARACTERS` | `500` |
| `QUIZ_MAX_QUESTION_COUNT` | `5` |
| `QUIZ_RETRIEVAL_TOP_K` | `8` |
| `QUIZ_MAX_CONTEXT_CHARACTERS` | `12000` |
| `QUIZ_MAX_CONTEXT_CHUNK_CHARACTERS` | `4000` |
| `QUIZ_MAX_OUTPUT_TOKENS` | `2048` |
| `QUIZ_THINKING_BUDGET` | `128` |

## Alur pembuatan

1. Backend memvalidasi topik, jumlah soal, dan scope dokumen. `document_ids=null`
   berarti semua dokumen eligible; `document_ids=[]` berarti corpus kosong.
2. `SearchService` dipanggil langsung dan menutup transaksi bacanya sebelum
   generation. Hanya dokumen dengan profil embedding/checksum aktif yang dipakai.
3. Chunk dideduplikasi, dibatasi, lalu diberi ID lokal `S1`, `S2`, dan seterusnya.
   Topik serta dokumen diperlakukan sebagai data tidak tepercaya.
4. Gemini mengembalikan structured output. Backend menolak soal/opsi kosong, opsi
   duplikat, jumlah soal tidak lengkap, indeks kunci di luar 0-3, dan reference ID
   di luar konteks.
5. Setelah output lengkap tervalidasi, quiz, pertanyaan, empat opsi, kunci,
   explanation, dan snapshot sumber disimpan dalam satu transaksi singkat.

Provider dipanggil sebelum transaksi penyimpanan dimulai. Error provider tidak
meninggalkan quiz setengah jadi. Validasi empat opsi dan satu key adalah pemeriksaan
struktur; kebenaran semantik dan fakta bahwa hanya satu opsi benar tetap perlu review.

## Kontrak API

### Membuat dan membaca quiz

```http
POST /api/v1/quizzes
```

```json
{
  "topic": "fungsi tanpa return eksplisit",
  "document_ids": [20],
  "question_count": 1
}
```

Respons HTTP 201 dan `GET /api/v1/quizzes/{quiz_id}` hanya memuat ID, pertanyaan,
serta opsi. Keduanya sengaja tidak menampilkan `correct_option_id`, `is_correct`,
explanation, atau sumber.

### Menilai attempt

```http
POST /api/v1/quizzes/{quiz_id}/attempts
Idempotency-Key: nilai-unik-client
```

```json
{
  "answers": [
    {"question_id": 31, "option_id": 122}
  ]
}
```

Semua soal wajib dijawab tepat sekali. Backend memastikan soal berasal dari quiz
tersebut dan opsi berasal dari soalnya, kemudian menghitung nilai dari kunci di
database. Persentase adalah `benar / jumlah_soal * 100`, dibulatkan half-up ke dua
desimal. Respons HTTP 201 membuka review: pilihan pengguna, kunci, benar/salah,
explanation, dan snapshot sumber backend.

Idempotency key unik per quiz. Key serta payload jawaban yang sama (urutan jawaban
boleh berbeda) mengembalikan attempt lama dengan HTTP 200 dan
`idempotent_replay=true`. Key sama dengan payload berbeda menghasilkan HTTP 409.
Constraint PostgreSQL melindungi race antar-request; request dengan key baru boleh
membuat attempt lain.

Hasil lama dapat dibaca melalui:

```http
GET /api/v1/quiz-attempts/{attempt_id}
```

Error utama: 404 untuk quiz/attempt tidak ada, 409 untuk konflik idempotency, 422
untuk input atau konteks tidak cukup, 429 untuk kuota, 502 untuk output provider
tidak valid, dan 503 untuk database/provider tidak tersedia. Pesan tidak memuat key,
connection string, stack trace, atau dokumen lengkap.

## Mencoba dari PowerShell 5.1

Jalankan server dan buka `http://127.0.0.1:8000/docs`. Di Swagger, jalankan create,
salin `quiz_id`, pilih satu `option_id` untuk setiap soal, lalu submit dengan header
`Idempotency-Key`. Alternatif terminal:

```powershell
$documentId = 20
$createBody = @{
    topic = "fungsi tanpa return eksplisit"
    document_ids = @($documentId)
    question_count = 1
} | ConvertTo-Json
$quiz = Invoke-RestMethod -Method Post `
    -Uri "http://127.0.0.1:8000/api/v1/quizzes" `
    -ContentType "application/json" -Body $createBody

$quizId = $quiz.id
$question = $quiz.questions[0]
$attemptBody = @{
    answers = @(@{
        question_id = $question.id
        option_id = $question.options[0].id
    })
} | ConvertTo-Json -Depth 5
$attempt = Invoke-RestMethod -Method Post `
    -Uri "http://127.0.0.1:8000/api/v1/quizzes/$quizId/attempts" `
    -Headers @{ "Idempotency-Key" = "manual-attempt-001" } `
    -ContentType "application/json" -Body $attemptBody
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/quiz-attempts/$($attempt.id)"
```

## Keterbatasan

Quiz adalah snapshot stabil dan tidak digenerasi ulang saat dibaca atau dinilai.
Snapshot sumber tetap tersedia walaupun corpus berubah. Namun generation bersifat
probabilistik: validasi schema, reference ID, dan constraint tidak membuktikan semua
distractor salah secara semantik. Review manusia tetap diperlukan untuk materi atau
penilaian berisiko tinggi.
