# Phase 4 Document Ingestion

## Scope and flow

`POST /api/v1/documents` menerima tepat satu field multipart bernama `file`.
Implementasi membaca byte dalam blok terbatas, memverifikasi ekstensi sekaligus isi,
mengekstrak teks di threadpool, memakai `TextChunker` Phase 1, lalu membuka transaksi
database singkat untuk menyimpan document dan seluruh chunk secara atomik. Isi file
tidak pernah dijalankan atau diperlakukan sebagai instruksi.

Format yang didukung:

- `.txt`: UTF-8 atau UTF-8 dengan BOM.
- `.md`: aturan encoding yang sama; Markdown tetap menjadi teks sumber sehingga code
  fence, indentasi, spasi internal, dan newline dipertahankan.
- `.pdf`: PDF berbasis teks yang dapat diekstrak pypdf 6.x.

Content-Type dan nama ekstensi dari client tidak dipercaya sendirian. Dispatcher juga
memeriksa signature PDF, decoding UTF-8, dan karakter kontrol binary. Nama upload
hanya dibersihkan menjadi nama tampilan; nama itu tidak pernah menjadi path storage.

## Resource limits

| Setting | Default | Meaning |
| --- | ---: | --- |
| `MAX_UPLOAD_SIZE_MB` | 10 | byte aktual file |
| `MAX_MULTIPART_BODY_SIZE_MB` | 11 | byte body request termasuk boundary/header multipart |
| `MAX_PDF_PAGES` | 200 | jumlah halaman sebelum ekstraksi |
| `MAX_EXTRACTED_CHARACTERS` | 2,000,000 | karakter hasil ekstraksi sebelum separator halaman |
| `INGESTION_CHUNK_SIZE` | 500 | ukuran window karakter |
| `INGESTION_CHUNK_OVERLAP` | 100 | overlap karakter |

Middleware membaca body multipart ke buffer yang tidak dapat melewati limit request;
setelah itu `UploadFile` dibaca per 64 KiB dan kembali diperiksa terhadap limit file.
Jadi pemeriksaan tidak bergantung pada `Content-Length`. Limit request harus lebih
besar daripada limit file untuk menyediakan ruang envelope multipart.

## Reference text and offsets

Normalisasi selalu nonaktif pada endpoint Phase 4. Untuk TXT/Markdown,
`reference_text` adalah hasil decode `utf-8-sig` persis (BOM dilepas oleh codec), dan
offset chunk bersifat global terhadap string tersebut.

Untuk PDF, teks halaman hasil pypdf digabung dengan separator `LF-FF-LF`. Setiap
halaman di-chunk secara terpisah agar sebuah chunk memiliki satu `page_number`, tetapi
`start_char`/`end_char` tetap global terhadap `documents.reference_text`. Offset ini
adalah indeks karakter Python pada hasil ekstraksi—bukan posisi byte, glyph, atau
object stream dalam PDF asli.

## Persistence and deduplication

Identitas deduplikasi adalah `(SHA-256 byte file, extraction_profile)`. Nama file dan
Content-Type tidak memengaruhi identitas. Unique constraint PostgreSQL melindungi race
request: transaksi yang kalah di-rollback dan membaca document pemenang. Upload baru
memberi 201/`duplicate=false`; upload identik memberi 200/`duplicate=true` tanpa chunk
tambahan.

Status `processed` berarti ekstraksi dan chunking telah selesai. Belum ada embedding,
vector index, atau jaminan bahwa dokumen siap retrieval AI. Data persisten meliputi
identitas, nama tampilan, tipe, ukuran, checksum, extraction profile, reference text,
metadata, serta chunk. File asli dan endpoint download tidak termasuk Phase 4.

## PDF limitations

pypdf mengekstrak text layer yang tersedia dan tidak menjalankan OCR. PDF kosong atau
PDF yang tidak menghasilkan teks berguna ditolak dengan pesan bahwa ekstraksi gagal
dan file *mungkin* membutuhkan OCR; implementasi tidak menyimpulkan bahwa semua file
tersebut pasti hasil scan. PDF rusak dan PDF terenkripsi/password-protected juga
ditolak. Layout visual, tabel, urutan baca kompleks, font encoding, dan ligature dapat
menghasilkan teks yang berbeda dari tampilan halaman.

## Try three sample documents

Jalankan API, lalu dari PowerShell 5.1:

```powershell
curl.exe -X POST -F "file=@data\sample\perulangan-python.txt" http://127.0.0.1:8000/api/v1/documents
curl.exe -X POST -F "file=@data\sample\fungsi-python.md" http://127.0.0.1:8000/api/v1/documents
curl.exe -X POST -F "file=@data\sample\list-python.pdf" http://127.0.0.1:8000/api/v1/documents
curl.exe "http://127.0.0.1:8000/api/v1/documents?limit=20&offset=0"
```

Ambil `id` dari respons, kemudian:

```powershell
$documentId = 1
curl.exe "http://127.0.0.1:8000/api/v1/documents/$documentId"
curl.exe "http://127.0.0.1:8000/api/v1/documents/$documentId/chunks?limit=20&offset=0"
```
