# PyMentor AI Project Roadmap

## Project Scope

PyMentor AI is an adaptive Python learning assistant based on RAG.

The first version supports:

- PDF, Markdown, and TXT learning materials.
- Source-grounded question answering.
- Document and page citations.
- Multiple-choice quiz generation.
- Topic mastery tracking.
- Adaptive difficulty selection.
- Learning recommendations.

## Architecture Decisions

- Python version: 3.11.16.
- Backend: FastAPI.
- Frontend: Streamlit.
- Database: Neon PostgreSQL.
- Vector extension: pgvector.
- Dependency manager: uv.
- Local Docker is not required.
- Project files and dependency cache are stored on drive D.
- Application clients never access the database directly.
- Business and adaptive-learning logic belongs in the backend.

## Development Phases

### Phase 0 — Environment and Project Foundation

- [x] Verify Python, Git, VS Code, disk, and system environment.
- [x] Create project directory on drive D.
- [x] Initialize Git repository using branch main.
- [x] Create Python 3.11.16 virtual environment.
- [x] Redirect uv cache to drive D.
- [x] Create project structure and configuration files.
- [x] Validate ignored secrets and generated files.
- [x] Create the initial Git commit.

### Phase 1 — Python Foundations

- [x] Functions and type hints.
- [x] Classes and validated data structures.
- [x] Conservative UTF-8 TXT file processing.
- [x] Explicit input and file error behavior.
- [x] Unit testing for normalization, offsets, metadata, and edge cases.
- [x] Fixed-size character chunker exercise with validated overlap.

Phase 1 is complete. Chunk coordinates are Python character positions in the exact
text representation passed to the chunker, not byte positions. Optional
normalization is disabled by default for code-like material because whitespace
rewrites can alter multiline string content. See `docs/TEXT-PROCESSING.md`.

### Phase 2 — FastAPI Foundation

- [x] FastAPI application entrypoint and application factory.
- [x] API versioning through the validated `API_V1_PREFIX` setting.
- [x] Typed health response schema.
- [x] Process-only `GET /api/v1/health` endpoint.
- [x] Standard HTTP 404 and 405 error behavior.
- [x] Automated TestClient coverage for routing, OpenAPI, and local docs.

Phase 2 is complete. Import and startup do not connect to Neon, run migrations, or
mutate database state. The health route checks only the API process. Interactive
documentation is available at `/docs`; see `docs/API.md`. Upload, chat, quiz, and
document CRUD endpoints remain outside this phase.

### Phase 3 — PostgreSQL and pgvector

- [x] Create and verify Neon PostgreSQL project `twilight-firefly-94879334`.
- [x] Pin and verify branch `production` and database `neondb`.
- [x] Load pooled/direct database configuration from environment or dotenv files.
- [x] Configure SQLAlchemy 2 with Psycopg 3 while preserving Neon TLS parameters.
- [x] Configure Alembic to use the direct connection for migrations.
- [x] Enable pgvector through tracked revision `20260913_0001`.
- [x] Create the initial `documents` and `document_chunks` relational schema.
- [x] Test the real database connection, migration state, and rollback-isolated writes.

Phase 3 was verified against the selected production branch on 2026-09-13. The
database is at Alembic head `20260913_0001`, pgvector `0.8.6` is available, and no
schema drift is reported. A fixed-dimension embedding column is intentionally
deferred to Phase 5 because the embedding model and its output dimension have not
yet been selected.

### Phase 4 — Document Ingestion

- File validation.
- PDF, Markdown, and TXT extraction.
- Text cleaning.
- Chunk creation.
- Document metadata storage.

### Phase 5 — Embedding and Retrieval

- Embedding provider abstraction.
- Vector storage.
- Similarity search.
- Top-k retrieval.
- Relevance threshold.

### Phase 6 — RAG Answer Engine

- Context construction.
- Prompt construction.
- Grounded answer generation.
- Source citations.
- Unsupported-question handling.

### Phase 7 — Quiz Engine

- Structured question generation.
- Difficulty levels.
- Answer validation.
- Explanations.
- Attempt history.

### Phase 8 — Adaptive Learning Engine

- Mastery score.
- Topic weakness detection.
- Difficulty selection.
- Review recommendation.

### Phase 9 — Streamlit Interface

- Document upload.
- Tutor chat.
- Quiz interface.
- Progress dashboard.
- API client.

### Phase 10 — Evaluation and Testing

- Unit tests.
- Integration tests.
- Retrieval evaluation dataset.
- Citation validation.
- RAG quality report.

### Phase 11 — Security and Deployment

- Input and file validation.
- Secret management.
- Logging.
- Rate limiting.
- Production deployment.
- Optional Docker packaging.

### Phase 12 — Portfolio Completion

- Complete README.
- Architecture documentation.
- Demo screenshots.
- Demo video.
- Evaluation results.
- Known limitations.

## Definition of Done

The project is complete when:

- Documents can be uploaded and indexed.
- Questions retrieve relevant source chunks.
- Answers include valid citations.
- Unsupported questions are rejected safely.
- Quizzes can be generated and scored.
- Topic mastery changes after quiz attempts.
- Difficulty adapts to student performance.
- Automated tests pass.
- The application is deployed.
- Secrets are not committed to Git.

#### Checkpoint Progress

- [x] 1.1 Text normalization and unit tests.
- [x] 1.2 TextChunk validation and unit tests.
- [x] 1.3 Fixed-size character chunking with overlap.
- [x] 1.4 File processing and integrated edge cases.
- [x] 1.5 Final Phase 1 quality gate.

Chunk offsets refer to the exact input passed to TextChunker.split().
Character-based chunking is a baseline, not token-aware or syntax-aware.
