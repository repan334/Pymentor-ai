# Phase 2 FastAPI Foundation

## Scope

Phase 2 menyediakan proses HTTP lokal yang kecil dan teruji:

- entrypoint ASGI `app.main:app`;
- application factory `create_app()` untuk konfigurasi tes yang terisolasi;
- router berversi berdasarkan `API_V1_PREFIX`;
- process-health endpoint;
- dokumentasi Swagger UI dan schema OpenAPI bawaan FastAPI.

Tidak ada endpoint upload, dokumen, chat, kuis, atau database dalam fase ini. Import
dan startup aplikasi tidak membuat engine, melakukan query, membuat tabel, atau
menjalankan Alembic.

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

Hentikan server dengan `Ctrl+C` pada terminal yang menjalankan Uvicorn.

## Tests

Tes API memakai application factory dengan dotenv dinonaktifkan dan database URL
kosong, sehingga tidak memerlukan Neon atau kredensial sungguhan.

```powershell
$env:UV_CACHE_DIR = "D:\uv-cache"
uv run pytest -q backend\tests\api backend\tests\unit\test_app_config.py
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv lock --check
```

Tes integrasi Neon tetap opt-in melalui `RUN_DATABASE_TESTS=1` dan tidak perlu
dijalankan ulang ketika hanya kode API Phase 2 yang berubah.
