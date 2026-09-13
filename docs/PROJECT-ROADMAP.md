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

- Functions and type hints.
- Classes and data structures.
- File processing.
- Exception handling.
- Unit testing.
- Text chunker exercise.

### Phase 2 — FastAPI Foundation

- FastAPI application.
- API versioning.
- Request and response schemas.
- Health endpoint.
- Exception handling.
- Automated API test.

### Phase 3 — PostgreSQL and pgvector

- Create Neon PostgreSQL project.
- Enable pgvector.
- Configure SQLAlchemy.
- Configure Alembic migrations.
- Create initial relational schema.
- Test database connection.

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
- [ ] 1.4 File processing and integrated edge cases.
- [ ] 1.5 Final Phase 1 quality gate.

Chunk offsets refer to the exact input passed to TextChunker.split().
Character-based chunking is a baseline, not token-aware or syntax-aware.