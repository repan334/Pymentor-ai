# PyMentor AI

PyMentor AI adalah tutor AI adaptif untuk mempelajari Python yang menggunakan
teknik *retrieval-augmented generation* (RAG).

## Tujuan Utama

- Menjawab pertanyaan menggunakan materi pembelajaran yang diunggah.
- Menyertakan referensi dokumen dan halaman.
- Membuat kuis dari materi yang telah diindeks.
- Memantau tingkat penguasaan siswa berdasarkan topik.
- Menyesuaikan tingkat kesulitan kuis berdasarkan performa siswa.
- Merekomendasikan topik yang perlu ditinjau ulang.

## Tumpukan Teknologi

- Python 3.11
- FastAPI
- Streamlit
- PostgreSQL dengan pgvector
- Neon managed PostgreSQL
- SQLAlchemy
- Alembic
- pytest
- Ruff
- uv

## Arsitektur Tingkat Tinggi

Siswa
-> Streamlit
-> FastAPI REST API
-> Mesin RAG dan Pembelajaran Adaptif
-> Neon PostgreSQL dengan pgvector
-> Penyedia LLM dan Embedding

## Lingkungan Pengembangan

Aplikasi dan lingkungan virtual Python disimpan di drive D.

PostgreSQL dan pgvector menggunakan Neon managed PostgreSQL. Docker tidak
diperlukan untuk lingkungan pengembangan awal.

## Setup Lokal

Gunakan PowerShell 5.1 dari root repository. Dependensi dan virtual environment
dikelola oleh `uv` dengan cache di drive D.

```powershell
$env:UV_CACHE_DIR = "D:\uv-cache"
uv sync --frozen
```

Autentikasi Neon dilakukan melalui browser; jangan menaruh API key atau connection
string di source control maupun chat.

```powershell
neon auth
Copy-Item .env.example .env
neon link --project-id twilight-firefly-94879334 --branch production -y --no-config
```

Perintah `neon link` menarik `DATABASE_URL` (pooled) dan
`DATABASE_URL_UNPOOLED` (direct) ke `.env`. Aplikasi memakai URL pooled, sedangkan
Alembic memakai URL direct. Query parameter keamanan dari URL Neon, termasuk
`sslmode` dan `channel_binding`, dipertahankan saat driver diubah secara eksplisit
ke Psycopg 3.

Terapkan dan periksa migrasi:

```powershell
uv run alembic upgrade head
uv run alembic current
uv run alembic check
uv run python backend\scripts\database_status.py
```

Tes lokal tidak mengakses database remote. Tes integrasi Neon harus diaktifkan
secara eksplisit dan melakukan round-trip data di dalam transaksi yang di-rollback.

```powershell
uv run pytest -q -m "not integration"
$env:RUN_DATABASE_TESTS = "1"
uv run pytest -q backend\tests\integration
Remove-Item Env:\RUN_DATABASE_TESTS
uv run ruff check .
uv run ruff format --check .
```

Lihat [panduan database](docs/DATABASE.md) untuk keputusan skema dan prosedur
migrasi yang aman.

## Menjalankan API Lokal

Jalankan server dari root repository:

```powershell
$env:UV_CACHE_DIR = "D:\uv-cache"
uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Pada terminal PowerShell lain, periksa proses API:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/health
```

Dokumentasi interaktif tersedia di `http://127.0.0.1:8000/docs`, sedangkan schema
OpenAPI tersedia di `http://127.0.0.1:8000/openapi.json`. Tekan `Ctrl+C` pada
terminal server untuk menghentikannya. Health endpoint hanya memeriksa proses API;
endpoint tersebut tidak mengakses Neon atau penyedia model.

Upload satu dokumen melalui Swagger UI di `http://127.0.0.1:8000/docs`, atau dari
PowerShell 5.1 dengan executable curl bawaan Windows:

```powershell
curl.exe -X POST -F "file=@data\sample\perulangan-python.txt" http://127.0.0.1:8000/api/v1/documents
curl.exe http://127.0.0.1:8000/api/v1/documents
```

Lihat [panduan API](docs/API.md) untuk kontrak HTTP dan
[panduan ingestion](docs/DOCUMENT-INGESTION.md) untuk format, limit, offset,
deduplikasi, dan keterbatasan PDF.

Untuk indexing dan pencarian semantik, simpan `GEMINI_API_KEY` hanya di `.env`,
jalankan smoke test model, lalu gunakan ID hasil upload:

```powershell
uv run python backend\scripts\embedding_smoke.py
$documentId = 1
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/documents/$documentId/index"
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/documents/$documentId/index-status"
$body = @{ query = "Bagaimana fungsi mengembalikan hasil?"; top_k = 3; document_ids = @($documentId) } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/search" -ContentType "application/json" -Body $body
```

Detail profil, batas kuota, status kegagalan, dan arti cosine distance tersedia di
[panduan embedding dan retrieval](docs/EMBEDDINGS-AND-RETRIEVAL.md).

Untuk tutor grounded, verifikasi akses model chat terlebih dahulu lalu kirim satu
pertanyaan mandiri. Endpoint memakai retrieval Phase 5 secara internal dan tidak
menerima system prompt atau key dari client:

```powershell
uv run python backend\scripts\chat_smoke.py
$chatBody = @{ question = "Mengapa fungsi dapat mengembalikan None?"; top_k = 4; document_ids = @($documentId) } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/chat" -ContentType "application/json" -Body $chatBody
```

Lihat [panduan Grounded RAG Tutor](docs/RAG-TUTOR.md) untuk kontrak sitasi,
pemisahan error, batas konteks, dan keterbatasan grounding.

Topic Phase 8 harus dibuat sebelum quiz baru. Progress memakai perhitungan
terbaru-per-quiz tanpa model call:

```powershell
$topic = @{ id = "python-functions"; display_name = "Fungsi Python" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/topics" -ContentType "application/json" -Body $topic

$quizBody = @{ topic_id = "python-functions"; topic = "fungsi Python"; document_ids = @($documentId); question_count = 1 } | ConvertTo-Json
$quiz = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/quizzes" -ContentType "application/json" -Body $quizBody
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/topics/python-functions/progress"
```

Field `difficulty` (`basic`/`intermediate`/`advanced`) bersifat opsional; jika
dihilangkan, backend menurunkannya dari progress topic tanpa model call dan
menyimpannya pada quiz.

Respons create/get quiz menyembunyikan kunci; kunci, explanation, dan sumber baru
dibuka setelah semua soal disubmit dengan idempotency key.

Lihat [panduan quiz](docs/QUIZZES.md) untuk submit/replay dan
[laporan evaluasi model](docs/MODEL-EVALUATION.md) untuk denominator serta batasan
hasil aktual.
Lihat [panduan topic progress](docs/TOPIC-PROGRESS.md).

## Menjalankan Frontend Lokal

Jalankan API dan Streamlit pada dua terminal PowerShell 5.1. Frontend hanya menerima
alamat API dan tidak memerlukan connection string atau key model:

```powershell
# Terminal 1
$env:UV_CACHE_DIR = "D:\uv-cache"
uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000

# Terminal 2
$env:UV_CACHE_DIR = "D:\uv-cache"
$env:API_BASE_URL = "http://127.0.0.1:8000/api/v1"
uv run streamlit run frontend\app.py --server.address 127.0.0.1 --server.port 8501
```

Buka `http://127.0.0.1:8501`. Hentikan masing-masing server dengan `Ctrl+C`.
Alur UI, batas state sesi, dan acceptance checklist ada di
[panduan frontend](docs/FRONTEND.md).

## Status Proyek

Phase 1 sampai Phase 9 selesai dan telah diverifikasi per 15 September 2026.
Model chat
dipindahkan dari model 2.5 yang sudah ditutup bagi pengguna baru ke
`gemini-3.6-flash`; embedding dan indeks tidak berubah.

- Target: project `twilight-firefly-94879334`, branch `production`, database `neondb`.
- FastAPI menyediakan `GET /api/v1/health`, `/docs`, dan `/openapi.json` tanpa
  melakukan koneksi database saat import atau startup.
- SQLAlchemy 2 menggunakan Psycopg 3 dan membaca konfigurasi dari environment,
  `.env`, atau `.env.local`.
- Alembic berada pada revision `20260914_0006`.
- API ingestion mendukung UTF-8 TXT/Markdown dan PDF berbasis teks, menyimpan teks
  acuan serta chunk secara atomik, dan mengembalikan dokumen lama untuk upload
  identik tanpa menggandakan chunk.
- Ekstensi pgvector aktif. Chunk dapat diindeks dengan profil tetap
  `gemini/gemini-embedding-2/768/retrieval-asymmetric-v1`, disimpan sebagai
  `vector(768)`, dan dicari dengan exact cosine nearest-neighbor.
- `POST /api/v1/chat` membangun konteks berbatas, memakai instruksi tutor berversi,
  memvalidasi structured output, dan merakit sitasi hanya dari chunk yang benar-benar
  dikirim. Model embedding serta data yang sudah diindeks tidak diubah.
- Implementasi quiz Phase 7, persistence Neon, race idempotency, dan HTTP live
  create/get/submit/result/replay lulus. Evaluasi RAG eksternal masih parsial karena
  kuota: 6 request sukses, 1 error kuota, dan 9/16 kasus belum dijalankan.
- Phase 8 menambahkan topic ID stabil, assignment quiz, score latihan dari attempt
  terbaru per quiz, dan rekomendasi berbasis aturan tanpa model call atau counter.
- Difficulty adaptif Phase 8 selesai pada 15 September 2026: prompt quiz
  `grounded-quiz-v2` menerima `basic`/`intermediate`/`advanced`, nilai dihilangkan
  berarti turunan rule-based dari progress topic, dan quiz legacy tetap
  `difficulty=null`. Verifikasi live lulus dengan satu quiz difficulty turunan.
- Phase 9 menyediakan UI Streamlit lokal untuk materi, tutor, quiz, dan progres melalui
  satu HTTP client FastAPI. UI tidak memiliki akses database atau provider langsung.
- Phase 11 dimulai dengan batas body JSON (`MAX_JSON_BODY_SIZE_MB=1`, HTTP 413) pada
  seluruh route mutation, hasil review QC/pentest 15 September 2026. Rate limiting,
  logging, dan deployment masih terbuka.
- Status dan batasan setiap fase dicatat terpisah dalam roadmap.
