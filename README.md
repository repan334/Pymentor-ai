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

## Status Proyek

Fase 0 — Fondasi proyek dan lingkungan pengembangan.