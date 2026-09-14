# Phase 6 Grounded RAG Tutor

## Profil dan batas

Phase 6 memakai profil chat tunggal yang tervalidasi:

| Setting | Default |
| --- | --- |
| `LLM_PROVIDER` | `gemini` |
| `LLM_MODEL` | `gemini-2.5-flash` |
| `LLM_PROMPT_VERSION` | `grounded-tutor-v1` |
| `CHAT_MAX_QUESTION_CHARACTERS` | `2000` |
| `CHAT_MAX_DOCUMENT_IDS` | `100` |
| `CHAT_MAX_TOP_K` | `8` |
| `CHAT_MAX_CONTEXT_CHARACTERS` | `12000` |
| `CHAT_MAX_CONTEXT_CHUNK_CHARACTERS` | `4000` |
| `CHAT_MAX_OUTPUT_TOKENS` | `2048` |
| `CHAT_THINKING_BUDGET` | `512` |
| `CHAT_REQUEST_TIMEOUT_SECONDS` | `45` |
| `CHAT_MAX_ATTEMPTS` | `2` |

SDK resmi `google-genai` yang sama dengan Phase 5 dipakai untuk generation. Key
dibaca eksplisit dari `GEMINI_API_KEY` melalui `Settings`/`SecretStr`; aplikasi tidak
menerima key, system prompt, atau konfigurasi tool dari request. Adapter tidak
melakukan network call saat import, startup, atau health check. Retry internal SDK
dinonaktifkan dan retry aplikasi hanya berlaku terbatas untuk timeout, transport,
429, dan error server sementara. Autentikasi serta request invalid tidak diulang.

`max_output_tokens` mencakup token thinking dan output. Finish reason
`MAX_TOKENS` diperlakukan sebagai output terpotong, bukan jawaban sukses. Safety
block, kuota, timeout, provider unavailable, dan output invalid juga dibedakan.

## Alur satu pertanyaan

1. API memvalidasi satu pertanyaan mandiri, `top_k`, dan filter dokumen.
2. `RagTutorService` memanggil `SearchService` secara langsung. Tidak ada HTTP
   loopback ke endpoint aplikasi sendiri.
3. Search hanya memakai dokumen `ready` dengan checksum serta profil embedding
   Phase 5 yang cocok. `document_ids=[]` tetap berarti corpus kosong.
4. Hasil dideduplikasi menurut pasangan document/chunk dan dipotong sesuai batas.
   Transaksi database ditutup sebelum embedding query maupun generation.
5. Backend memberi ID lokal `S1`, `S2`, dan seterusnya pada teks yang benar-benar
   dikirim sebagai konteks tidak tepercaya.
6. Gemini diminta mengembalikan structured output berisi status, bagian jawaban,
   dan ID sumber pendukung. Jalur normal memakai tepat satu generation call.
7. Backend memvalidasi seluruh ID, mewajibkan referensi pada setiap bagian jawaban,
   menyusun marker `[S1]`, dan mengambil nama, offset, halaman, metadata, serta
   excerpt langsung dari hasil retrieval. Metadata atau kutipan buatan model tidak
   diterima.

Jika tidak ada chunk eligible, service mengembalikan `insufficient_context` tanpa
memanggil embedding query maupun model chat. Jika ada konteks tetapi model menilai
tidak cukup, status yang sama dikembalikan tanpa menjadikan chunk yang tidak relevan
sebagai sitasi. Penilaian kecukupan dan dukungan semantik oleh model tetap bersifat
probabilistik; JSON valid dan ID valid bukan bukti bahwa sebuah klaim benar-benar
didukung. Cosine distance juga bukan confidence atau ukuran kebenaran.

Pertanyaan dan isi dokumen diperlakukan sebagai data. Prompt tutor melarang instruksi
di dalam dokumen mengganti aturan aplikasi, menjalankan kode, membuka URL, memakai
web, atau memanggil tool. Tes deterministik membuktikan pemisahan instruksi ini, tetapi
bukan bukti universal bahwa model live selalu tahan terhadap prompt injection.

## Kontrak chat

```http
POST /api/v1/chat
Content-Type: application/json
```

```json
{
  "question": "Mengapa fungsi dapat mengembalikan None?",
  "top_k": 4,
  "document_ids": [20]
}
```

`document_ids` boleh dihilangkan untuk seluruh corpus eligible. Array kosong tidak
diperluas menjadi seluruh corpus. Respons `answered` berisi jawaban dengan marker
yang disusun backend dan hanya sitasi yang dipakai:

```json
{
  "status": "answered",
  "answer": "Fungsi mengembalikan None ketika ...\n[S1]",
  "citations": [
    {
      "reference_id": "S1",
      "document_id": 20,
      "chunk_id": 51,
      "source_name": "fungsi-python.md",
      "start_char": 0,
      "end_char": 187,
      "excerpt": "teks persis yang dikirim ke model",
      "page_number": null,
      "metadata": {}
    }
  ]
}
```

Respons tanpa dukungan memakai HTTP 200 karena ini hasil domain yang valid:

```json
{
  "status": "insufficient_context",
  "answer": "Materi yang tersedia belum cukup untuk menjawab pertanyaan ini. Unggah atau indeks materi yang relevan, lalu coba lagi.",
  "citations": []
}
```

Error yang dapat ditindaklanjuti:

- 422: request tidak valid atau safety block (`chat_safety_blocked`).
- 429: quota provider habis (`chat_quota_exceeded`).
- 502: structured output malformed, terpotong, atau sitasi invalid.
- 503: database, embedding, konfigurasi/auth chat, timeout, atau provider unavailable.

Pesan error tidak memuat key, connection string, stack trace, vector, atau dokumen
lengkap.

## Setup dan mencoba

Simpan key hanya di `.env` lokal yang diabaikan Git:

```powershell
Copy-Item .env.example .env
notepad .env
$env:UV_CACHE_DIR = "D:\uv-cache"
$env:TEMP = "D:\Temp\pymentor"
$env:TMP = "D:\Temp\pymentor"
uv run python backend\scripts\chat_smoke.py
```

Smoke test hanya mencetak provider, model, versi prompt, status validasi, dan kode
HTTP provider ketika gagal. Key, isi jawaban, serta sumber tidak dicetak.

Jalankan API dan gunakan dokumen yang sudah di-upload serta di-index:

```powershell
uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Di terminal lain:

```powershell
$documentId = 20
$request = @{
    question = "Mengapa fungsi dapat mengembalikan None?"
    top_k = 4
    document_ids = @($documentId)
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
    -Uri "http://127.0.0.1:8000/api/v1/chat" `
    -ContentType "application/json" `
    -Body $request
```

Swagger UI tersedia di `http://127.0.0.1:8000/docs`. Hentikan server dengan
`Ctrl+C` pada terminal Uvicorn.

## Verifikasi

Tes default dan database deterministik tidak membutuhkan chat key. Tes live bersifat
opt-in, menggunakan fixture unik, maksimum tujuh provider request tanpa retry, dan
membersihkan hanya dokumen fixture tersebut:

```powershell
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv lock --check

$env:RUN_DATABASE_TESTS = "1"
uv run pytest -q backend\tests\integration\test_rag_database.py
Remove-Item Env:\RUN_DATABASE_TESTS

$env:RUN_LIVE_RAG_TESTS = "1"
uv run pytest -q backend\tests\integration\test_rag_live_api.py
Remove-Item Env:\RUN_LIVE_RAG_TESTS
```

Pada verifikasi 14 September 2026, key lokal dan embedding tetap berfungsi, tetapi
request generation minimal ke `gemini-2.5-flash` mengembalikan HTTP 404. Delapan
percobaan generation awal dihentikan tanpa retry, penggantian model, atau aktivasi
billing. Karena itu smoke chat, RAG live, dan HTTP end-to-end tetap tertunda sampai
model target tersedia untuk project/key yang sama.
