# Phase 5 Embeddings and Semantic Retrieval

## Fixed profile

Phase 5 memakai satu profil aktif yang sengaja sederhana:

| Setting | Value/default |
| --- | --- |
| `EMBEDDING_PROVIDER` | `gemini` |
| `EMBEDDING_MODEL` | `gemini-embedding-2` |
| `EMBEDDING_DIMENSIONS` | `768` |
| `EMBEDDING_INPUT_VERSION` | `retrieval-asymmetric-v1` |

SDK resmi `google-genai` mengirim setiap chunk sebagai `Content` terpisah. Input
dokumen berbentuk `title: {title} | text: {content}` dan input query berbentuk
`task: search result | query: {query}`. Model ini tidak diberi parameter `task_type`.
Prefix hanya masuk ke request provider; `content`, `reference_text`, serta offset yang
tersimpan tidak berubah. Mengganti model, dimensi, atau versi format berarti profil
baru dan memerlukan re-index; ruang vector antarprofil tidak dianggap kompatibel.

Setiap respons divalidasi: jumlah vector harus sama dengan input, dimensi tepat 768,
semua angka finite, dan norm tidak nol. Timeout dan retry eksponensial terbatas berada
di adapter; retry internal SDK dinonaktifkan untuk mencegah retry berlapis. Error 400,
401, dan 403 tidak diulang; error sementara dan 429 diulang hanya sampai batas.

## Setup and smoke test

Simpan key di `.env` atau process environment, jangan di source control atau chat:

```powershell
Copy-Item .env.example .env
notepad .env
$env:UV_CACHE_DIR = "D:\uv-cache"
$env:TEMP = "D:\Temp\pymentor"
$env:TMP = "D:\Temp\pymentor"
uv run python backend\scripts\embedding_smoke.py
```

Smoke test hanya mencetak provider, model, dimensi aktual, dan hasil validasi—tidak
mencetak key maupun nilai vector. Jangan mengaktifkan billing untuk menjalankan fase
ini. Jika free-tier quota tidak tersedia atau habis, hentikan pengujian live dan
tunggu/reset quota sesuai akun; aplikasi mengembalikan 429 yang aman.

## Bounded synchronous indexing

`POST /api/v1/documents/{id}/index` memproses maksimal `MAX_INDEX_CHUNKS` dalam batch
`EMBEDDING_BATCH_SIZE`, dengan timeout request dan `MAX_INDEXING_SECONDS`. Semua chunk
harus berhasil; indexing parsial tidak pernah diberi status `ready`.

Alurnya memakai tiga bagian:

1. transaksi singkat mengambil row lock, memeriksa idempotensi, dan menyimpan token claim;
2. transaksi ditutup sebelum panggilan Gemini;
3. transaksi singkat baru memverifikasi token/hash lalu menyimpan seluruh vector dan
   menandai status `ready`.

Permintaan bersamaan mendapat 409. Claim yang ditinggalkan proses mati dapat dipulihkan
setelah `INDEX_CLAIM_TIMEOUT_SECONDS`. Kegagalan provider ditandai `failed`; retry dapat
memanggil provider lagi jika panggilan sebelumnya berhasil tetapi persistence gagal.
Karena provider eksternal tidak berada dalam transaksi PostgreSQL, sistem tidak
menjanjikan exactly-once call.

`processed` hanya berarti ingestion selesai. Eligibility membutuhkan status indexing
`ready`, profil aktif yang sama, checksum corpus sama, dan embedding valid untuk setiap
chunk. File asli tetap tidak disimpan.

## Exact retrieval

`POST /api/v1/search` membuat satu embedding query hanya setelah menemukan corpus
eligible. Ranking dihitung di PostgreSQL dengan exact cosine nearest-neighbor; vector
database tidak dimuat ke Python. Tie pada distance diurutkan berdasarkan `chunk_id`.
Tidak ada index approximate atau threshold relevansi universal pada fase ini.

`document_ids` yang tidak dikirim berarti seluruh corpus eligible. Array kosong berarti
corpus kosong secara eksplisit dan tidak memanggil provider. Distance yang lebih kecil
menandakan vector lebih dekat dalam profil ini, bukan confidence, kebenaran jawaban,
atau jaminan bahwa sumber mengandung jawaban.

## PowerShell example

Setelah menjalankan Uvicorn dan mengunggah tiga dokumen sesuai
`docs/DOCUMENT-INGESTION.md`:

```powershell
$documentIds = @(1, 2, 3)
foreach ($documentId in $documentIds) {
    Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/documents/$documentId/index"
    Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/documents/$documentId/index-status"
}

$request = @{
    query = "Bagaimana fungsi mengembalikan hasil?"
    top_k = 3
    document_ids = $documentIds
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
    -Uri "http://127.0.0.1:8000/api/v1/search" `
    -ContentType "application/json" `
    -Body $request
```

Swagger UI di `http://127.0.0.1:8000/docs` menyediakan kontrak dan contoh schema.
Tekan `Ctrl+C` pada terminal Uvicorn untuk menghentikan server.

## Verification commands

Tes default tidak membutuhkan key atau Neon. Tes live bersifat opt-in dan fixture-nya
unik; cleanup hanya menghapus data tes sendiri.

```powershell
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv lock --check

$env:RUN_DATABASE_TESTS = "1"
uv run pytest -q backend\tests\integration\test_embedding_retrieval_database.py
Remove-Item Env:\RUN_DATABASE_TESTS

$env:RUN_GEMINI_TESTS = "1"
uv run pytest -q backend\tests\integration\test_gemini_embeddings.py
Remove-Item Env:\RUN_GEMINI_TESTS

$env:RUN_LIVE_RETRIEVAL_TESTS = "1"
uv run pytest -q backend\tests\integration\test_retrieval_live_api.py
Remove-Item Env:\RUN_LIVE_RETRIEVAL_TESTS
```
