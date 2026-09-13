# Phase 1 Text Processing

## Scope and status

Phase 1 provides a small, dependency-free text-processing foundation for learning
materials. It supports UTF-8 TXT loading, optional conservative normalization,
validated character-window chunking, source metadata, and explicit errors. PDF and
Markdown extraction remain Phase 4 work.

## Processing flow

1. `load_text_file()` validates the path type and `.txt` extension, then reads UTF-8
   or UTF-8-with-BOM without newline translation.
2. `process_text_file()` retains that exact value as `source_text`.
3. By default, normalization is disabled, so code-like material is chunked without
   whitespace rewriting. When explicitly enabled, `normalize_text()` creates the
   separate `processed_text` representation.
4. `TextChunker.split()` creates fixed-size character windows with the configured
   overlap. Each non-whitespace window becomes a validated `TextChunk`.
5. Every chunk receives the source filename and normalization flag as metadata.

## Normalization contract

Normalization performs only these transformations:

- CRLF and CR line endings become LF.
- Trailing whitespace is removed from every line.
- Three or more consecutive newlines become two.
- Leading and trailing newline characters are removed from the whole document.

Leading indentation and internal spaces or tabs are retained. This is deliberately
not described as semantic preservation: trailing spaces and blank lines inside a
Python multiline string are still content, so normalization can change that string.
For code and mixed prose/code material, keep the pipeline default `normalize=False`.

## Chunk and offset contract

- `chunk_size` must be a positive integer.
- `overlap` must be an integer satisfying `0 <= overlap < chunk_size`.
- Those constraints make `chunk_size - overlap` positive, so every iteration advances.
- Empty input returns no chunks.
- Whitespace-only windows are omitted; remaining chunk indexes stay contiguous.
- `start_char` and `end_char` are Python string character indexes into the exact text
  passed to the chunker. They are not UTF-8 byte offsets.
- Pipeline chunks address `processed_text`. When normalization is enabled, those
  positions generally do not address the same content in raw `source_text`.
- Metadata dictionaries are copied for each chunk, so mutations do not leak between
  the caller and sibling chunks.

## Errors and encoding

Only `.txt` files are accepted in Phase 1, case-insensitively. Missing files,
directories, permission failures, and invalid UTF-8 retain their standard Python
exception types and details. Invalid argument types and invalid chunk settings raise
explicit `TypeError` or `ValueError` messages.

## Verification

From the repository root in PowerShell 5.1:

```powershell
$env:UV_CACHE_DIR = "D:\uv-cache"
uv run ruff check backend\app\text_processing backend\tests\unit
uv run ruff format --check backend\app\text_processing backend\tests\unit
uv run pytest -q backend\tests\unit\test_normalizer.py backend\tests\unit\test_text_chunk.py backend\tests\unit\test_chunker.py backend\tests\unit\test_text_pipeline.py
```
