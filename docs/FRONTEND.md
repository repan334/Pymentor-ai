# Streamlit Frontend

## Arsitektur dan konfigurasi

Entrypoint Phase 9 adalah `frontend/app.py`. Semua upload, indexing, tutor, quiz,
attempt, assignment, dan progress melewati satu `PyMentorApiClient` berbasis HTTPX.
Frontend tidak mengimpor service backend, membuka database, memanggil provider,
menilai jawaban, atau menghitung rekomendasi.

Set `API_BASE_URL` ke base API yang memuat prefix versi. Default lokalnya
`http://127.0.0.1:8000/api/v1`. URL tidak boleh memuat user/password, query, atau
fragment. HTTP client memakai connect timeout 3 detik dan read/write timeout 65
detik, tanpa retry otomatis. Frontend tidak memerlukan `DATABASE_URL` atau
`GEMINI_API_KEY`.

## Menjalankan pada PowerShell 5.1

```powershell
# Terminal API
$env:UV_CACHE_DIR = "D:\uv-cache"
$env:TEMP = "D:\Temp\pymentor"
$env:TMP = "D:\Temp\pymentor"
uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000

# Terminal UI
$env:UV_CACHE_DIR = "D:\uv-cache"
$env:TEMP = "D:\Temp\pymentor"
$env:TMP = "D:\Temp\pymentor"
$env:API_BASE_URL = "http://127.0.0.1:8000/api/v1"
uv run streamlit run frontend\app.py --server.address 127.0.0.1 --server.port 8501
```

Buka `http://127.0.0.1:8501`. Kedua proses hanya bind ke localhost. Tekan `Ctrl+C`
di masing-masing terminal untuk berhenti.

## Alur penggunaan

1. **Materi:** upload TXT/MD/PDF, pastikan ingestion `processed`, lalu tekan tindakan
   indexing secara eksplisit. Status ingestion dan indexing ditampilkan terpisah.
   Gunakan inspeksi untuk melihat teks acuan, offset karakter, halaman, dan chunk.
2. **Tutor:** pilih semua dokumen siap, subset tertentu, atau corpus kosong. Ketiga
   pilihan mempertahankan semantik `null`, daftar ID, dan `[]` dari backend. Setiap
   request berdiri sendiri; tidak ada riwayat percakapan.
3. **Kuis:** buat/pilih topic, tentukan scope dan jumlah soal, lalu generate secara
   eksplisit. UI tidak mengirim field difficulty sehingga backend memakai turunan
   adaptif dari progress topic. Kunci tidak dimuat sebelum submit. Semua soal wajib
   dijawab. Hasil, pembahasan, dan sumber berasal dari server dan dapat dibuka
   kembali.
4. **Progres:** lihat score latihan, evidence, dan rekomendasi backend. Assignment quiz
   legacy bersifat eksplisit karena memindahkan kontribusi histori ke topic tujuan.

## State, timeout, dan keamanan tampilan

Draft jawaban disalin ke session state agar bertahan pada rerun dan navigasi biasa.
Refresh browser keras, restart Streamlit, atau sesi yang kedaluwarsa dapat
menghilangkan draft lokal. Quiz dan hasil yang sudah persisten dapat dimuat ulang
melalui API.

Untuk submit attempt yang timeout/tidak pasti, frontend menyimpan idempotency key dan
payload yang tepat sama. Tombol retry mengirim ulang pasangan itu; frontend tidak
menilai atau membentuk payload baru sampai hasil pasti atau pengguna memulai attempt
baru. Mutation lain juga tidak di-retry otomatis. Periksa status/list terbaru sebelum
mengulang upload, indexing, generation, atau assignment yang hasilnya belum pasti.

Tidak ada cache global untuk hasil privat. Semua konten pengguna/model dirender dengan
primitive Streamlit tanpa `unsafe_allow_html`; traceback, raw response, credential,
dan detail koneksi tidak ditampilkan.

## Acceptance manual

- Pastikan API health berhasil, lalu UI memuat tanpa credential database pada proses UI.
- Upload fixture kecil; periksa status ingestion, lakukan indexing sekali, dan buka chunk.
- Di Tutor, uji scope semua, subset, dan kosong; buka citation dan periksa kode tetap rapi.
- Buat quiz 1 soal, pilih jawaban, pindah halaman lalu kembali; draft harus tetap ada.
- Submit, buka pembahasan, buka lagi hasil dari daftar, kemudian coba attempt baru.
- Periksa topic tanpa attempt, topic dengan evidence, dan assignment quiz legacy.
- Kecilkan lebar browser untuk memastikan kontrol tetap dapat digunakan.

AppTest memeriksa kontrak/interaksi deterministik, tetapi bukan bukti visual browser
nyata atau keberhasilan generation live. Sembilan kasus evaluasi Phase 7 tetap pending.
