# Database Guide

## Target

- Neon project: `pymentor-ai` (`twilight-firefly-94879334`)
- Branch: `production` (`br-jolly-river-b3ynw0pc`)
- Database: `neondb`
- PostgreSQL: 18

Project ini menggunakan Neon PostgreSQL saja. Docker dan database lokal tidak
dibutuhkan untuk Phase 3.

## Konfigurasi

`app.core.config.DatabaseSettings` membaca nilai dari process environment,
`.env`, lalu `.env.local`. Process environment tetap memiliki prioritas tertinggi.
Connection string disimpan sebagai `SecretStr` agar representasi object konfigurasi
tidak membocorkan kredensial.

- `DATABASE_URL`: endpoint pooled untuk trafik aplikasi.
- `DATABASE_URL_UNPOOLED`: endpoint direct yang diwajibkan ketika Alembic berjalan
  dan `DATABASE_URL` memakai host `-pooler`.
- `NEON_BRANCH`: konteks branch lokal; saat ini `production`.

File `.env`, `.env.*`, dan `.neon` diabaikan Git; `.env.example` adalah satu-satunya
template environment yang boleh dilacak dan tidak mengandung kredensial.

## Skema

Revision `20260913_0001` mengaktifkan extension `vector` dan membuat:

- `documents`: metadata sumber, checksum SHA-256, status pemrosesan, dan timestamp.
- `document_chunks`: potongan teks berurutan, offset sumber, halaman opsional, dan
  foreign key cascade ke dokumen.

Constraint database menjaga tipe sumber/status yang dikenal, urutan chunk unik per
dokumen, isi tidak kosong, serta rentang karakter dan nomor halaman yang valid.

Revision `20260913_0002` menambahkan fondasi ingestion tanpa mengubah data lama:

- `documents.file_size_bytes`: jumlah byte file upload; baris legacy diberi `0`.
- `documents.reference_text`: teks persisten yang menjadi ruang koordinat chunk;
  baris legacy diberi string kosong karena file asalnya tidak tersedia.
- `documents.extraction_profile`: versi strategi ekstraksi untuk identitas deduplikasi.
- unique constraint `(checksum_sha256, extraction_profile)` agar nama file tidak
  menentukan identitas dan request bersamaan tidak membuat dokumen ganda.
- status `processed` untuk ekstraksi dan chunking yang selesai. Nilai `ready` tetap
  diterima hanya untuk kompatibilitas baris legacy; nilainya tidak berarti siap RAG.

Seluruh document dan chunk baru ditulis dalam satu transaksi singkat setelah parsing
selesai. Konflik unique di-rollback lalu document pemenang dibaca kembali. Original
file tidak disimpan; hanya checksum, metadata, reference text, dan chunk yang persisten.

Tidak ada kolom `vector(n)` pada revision ini. Nilai `n` harus berasal dari model
embedding yang benar-benar dipilih. Model dan dimensi tersebut belum ditentukan,
jadi kolom serta index vector ditunda ke Phase 5 agar skema tidak mengunci asumsi
yang salah.

## Alur migrasi aman

Tinjau revision dan SQL sebelum menerapkan perubahan:

```powershell
$env:UV_CACHE_DIR = "D:\uv-cache"
uv run alembic history --verbose
uv run alembic upgrade head --sql
```

Setelah memastikan target `.neon` dan isi SQL, jalankan:

```powershell
uv run alembic upgrade head
uv run alembic current
uv run alembic check
```

Downgrade migration awal menghapus tabel aplikasi, sehingga jangan menjalankannya
pada data pengguna tanpa rencana pemulihan. Downgrade `0002` juga dapat gagal bila
satu checksum telah tersimpan dengan beberapa extraction profile, karena skema lama
hanya mengizinkan satu checksum. Extension `vector` sengaja tidak dihapus oleh
downgrade karena mungkin dipakai object lain di database.

## Verifikasi

Status non-rahasia dapat diperiksa melalui:

```powershell
uv run python backend\scripts\database_status.py
```

Tes integrasi memakai koneksi nyata, memverifikasi TLS, pgvector, dan revision,
lalu menguji insert/query dengan ID acak di dalam transaksi yang selalu di-rollback.

```powershell
$env:RUN_DATABASE_TESTS = "1"
uv run pytest -q backend\tests\integration
Remove-Item Env:\RUN_DATABASE_TESTS
```
