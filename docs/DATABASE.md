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

## Skema awal

Revision `20260913_0001` mengaktifkan extension `vector` dan membuat:

- `documents`: metadata sumber, checksum SHA-256, status pemrosesan, dan timestamp.
- `document_chunks`: potongan teks berurutan, offset sumber, halaman opsional, dan
  foreign key cascade ke dokumen.

Constraint database menjaga tipe sumber/status yang dikenal, urutan chunk unik per
dokumen, isi tidak kosong, serta rentang karakter dan nomor halaman yang valid.

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
pada data pengguna tanpa rencana pemulihan. Extension `vector` sengaja tidak
dihapus oleh downgrade karena mungkin dipakai object lain di database.

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
