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

## Status Proyek

Phase 3 — PostgreSQL dan pgvector selesai pada 13 September 2026.

- Target: project `twilight-firefly-94879334`, branch `production`, database `neondb`.
- SQLAlchemy 2 menggunakan Psycopg 3 dan membaca konfigurasi dari environment,
  `.env`, atau `.env.local`.
- Alembic berada pada revision `20260913_0001`.
- Ekstensi pgvector aktif. Kolom embedding berdimensi tetap belum dibuat karena
  model dan dimensinya belum dipilih; keputusan itu ditunda ke Phase 5.
- Phase 1 dan fondasi API Phase 2 tetap mengikuti checkpoint terpisah pada roadmap;
  penyelesaian Phase 3 tidak menyatakan kedua fase tersebut selesai.
