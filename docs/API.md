# FastAPI Contract

## Scope

Phase 2 menyediakan fondasi HTTP lokal, Phase 4 menambahkan ingestion, dan Phase 5
menambahkan indexing serta semantic retrieval:

- entrypoint ASGI `app.main:app`;
- application factory `create_app()` untuk konfigurasi tes yang terisolasi;
- router berversi berdasarkan `API_V1_PREFIX`;
- process-health endpoint;
- upload dan pembacaan dokumen/chunk;
- indexing dokumen dan pemeriksaan status;
- exact cosine top-k search terhadap chunk yang eligible;
- dokumentasi Swagger UI dan schema OpenAPI bawaan FastAPI.

Import dan startup aplikasi tidak membuat engine, melakukan query, membuat tabel,
menjalankan Alembic, atau memanggil provider. Endpoint chat, kuis, dan download file
asli belum tersedia.

## Configuration

Phase 2 memperluas `app.core.config.Settings`, sistem settings yang sama dengan
konfigurasi database Phase 3. Nilai default API adalah:

- `APP_NAME=PyMentor AI`
- `APP_ENV=development`
- `APP_DEBUG=false`
- `API_V1_PREFIX=/api/v1`

Database URL bersifat opsional selama proses API tidak menggunakan database. Jika
fitur database dipanggil, helper Phase 3 tetap mewajibkan URL yang sesuai. Nilai
rahasia tetap disimpan sebagai `SecretStr` dan tidak dimasukkan ke respons maupun
OpenAPI.

Limit ingestion default:

- `MAX_UPLOAD_SIZE_MB=10`: byte file aktual setelah multipart diparse.
- `MAX_MULTIPART_BODY_SIZE_MB=11`: seluruh body multipart termasuk envelope.
- `MAX_PDF_PAGES=200`.
- `MAX_EXTRACTED_CHARACTERS=2000000`.
- `INGESTION_CHUNK_SIZE=500` dan `INGESTION_CHUNK_OVERLAP=100`.

## Health contract

```http
GET /api/v1/health
```

Respons sukses:

```json
{
  "status": "ok"
}
```

Status ini hanya berarti proses FastAPI mampu melayani request. Endpoint tidak
memeriksa Neon, migrasi, pgvector, LLM, embedding, filesystem, atau layanan lain.
Route yang tidak ada tetap menghasilkan HTTP 404 dan metode yang tidak didukung
tetap menghasilkan HTTP 405 melalui perilaku standar FastAPI.

## Document contracts

```http
POST /api/v1/documents
Content-Type: multipart/form-data
field: file
```

Upload baru mengembalikan HTTP 201; upload dengan byte dan extraction profile yang
identik mengembalikan HTTP 200, ID lama, dan `duplicate: true`. Status `processed`
hanya berarti ekstraksi dan chunking selesai, bukan siap retrieval AI.

```json
{
  "id": 6,
  "source_name": "lesson.txt",
  "source_type": "text",
  "file_size_bytes": 31,
  "checksum_sha256": "64-hex-character checksum",
  "extraction_profile": "text:utf-8-sig:v1",
  "status": "processed",
  "indexing_status": "not_indexed",
  "character_count": 31,
  "chunk_count": 1,
  "reference_text": "Materi Python...",
  "metadata": {
    "normalization_applied": false,
    "offset_scope": "document_reference_text"
  },
  "created_at": "2026-09-13T00:00:00Z",
  "updated_at": "2026-09-13T00:00:00Z",
  "duplicate": false
}
```

Endpoint baca:

- `GET /api/v1/documents?limit=20&offset=0`
- `GET /api/v1/documents/{document_id}`
- `GET /api/v1/documents/{document_id}/chunks?limit=20&offset=0`

`limit` wajib 1–100 dan `offset` minimal 0. Detail dokumen memuat persisted
`reference_text`; setiap chunk memenuhi
`content == reference_text[start_char:end_char]`. PDF memakai offset global dokumen
dan `page_number`; TXT/Markdown tidak mengarang nomor halaman dan mengembalikan null.

Error ingestion aman dan tidak membawa stack trace atau detail koneksi:

- 413: `file_too_large` atau `multipart_body_too_large`.
- 415: `unsupported_format`.
- 422: input kosong/whitespace, encoding salah, PDF rusak/terenkripsi/tanpa teks,
  atau limit ekstraksi terlampaui.
- 404: `document_not_found`.
- 503: `database_unavailable`, hanya untuk exception database SQLAlchemy.

## Indexing contracts

```http
POST /api/v1/documents/{document_id}/index
GET /api/v1/documents/{document_id}/index-status
```

POST berjalan sinkron dan mengembalikan HTTP 200 setelah seluruh chunk tersimpan
atau gagal; tidak ada worker tersembunyi dan tidak ada respons 202. Contoh sukses:

```json
{
  "document_id": 20,
  "indexing_status": "ready",
  "indexed_chunk_count": 1,
  "embedding_profile": "gemini:gemini-embedding-2:768:retrieval-asymmetric-v1",
  "idempotent": false
}
```

Pengulangan dengan profil dan hash isi yang sama memberi `idempotent: true` tanpa
memanggil provider lagi. Claim baru ditolak dengan 409 selama indexing aktif; claim
yang lebih lama dari `INDEX_CLAIM_TIMEOUT_SECONDS` dapat diambil alih. Limit chunk dan
waktu total memberi 422/503 yang jelas. Kegagalan autentikasi/konfigurasi/provider
dipetakan secara aman tanpa key, vector, isi dokumen lengkap, atau detail koneksi.

## Search contract

```http
POST /api/v1/search
Content-Type: application/json
```

```json
{
  "query": "Bagaimana fungsi mengembalikan hasil?",
  "top_k": 3,
  "document_ids": [20]
}
```

`top_k` wajib 1–20. Query harus berisi teks dan tunduk pada limit karakter. Jumlah ID
juga dibatasi konfigurasi. Jika `document_ids` dihilangkan, semua dokumen eligible
dipertimbangkan; array kosong secara eksplisit menghasilkan `results: []` dengan
`reason: "document_ids_empty"` dan tidak diperluas menjadi seluruh corpus. Jika tidak
ada dokumen/profil eligible, reason adalah `no_eligible_documents` dan embedding query
tidak dipanggil.

Setiap hasil memuat `chunk_id`, `document_id`, `source_name`, `content`, offset karakter,
metadata halaman, dan `cosine_distance`. Nilai distance lebih kecil berarti lebih
dekat, bukan confidence, kebenaran jawaban, atau bukti bahwa jawaban tersedia. Belum
ada threshold universal karena belum dikalibrasi.

## Run locally

Dari root repository menggunakan PowerShell 5.1:

```powershell
$env:UV_CACHE_DIR = "D:\uv-cache"
uv sync --frozen
uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Buka:

- Health: `http://127.0.0.1:8000/api/v1/health`
- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI: `http://127.0.0.1:8000/openapi.json`

Atau panggil health dari terminal lain:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/health
```

Swagger UI menyediakan tombol **Try it out** pada `POST /api/v1/documents`: pilih
satu file pada field `file`, lalu tekan **Execute**. Dari PowerShell 5.1 gunakan
`curl.exe`, bukan alias `curl`:

```powershell
curl.exe -X POST -F "file=@data\sample\perulangan-python.txt" http://127.0.0.1:8000/api/v1/documents
curl.exe "http://127.0.0.1:8000/api/v1/documents?limit=20&offset=0"
```

Hentikan server dengan `Ctrl+C` pada terminal yang menjalankan Uvicorn.

## Tests

Tes default memakai application factory, dependency override, dan database URL
kosong, sehingga tidak memerlukan Neon atau kredensial sungguhan. Tes integrasi
PostgreSQL bersifat opt-in.

```powershell
$env:UV_CACHE_DIR = "D:\uv-cache"
uv run pytest -q backend\tests\api backend\tests\unit\test_app_config.py
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv lock --check
```

```powershell
$env:RUN_DATABASE_TESTS = "1"
uv run pytest -q backend\tests\integration
Remove-Item Env:\RUN_DATABASE_TESTS
```
