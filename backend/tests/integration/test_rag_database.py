import os
import uuid
from hashlib import sha256

import pytest
from app.chat.models import ModelAnswerSection, ModelTutorOutput, TutorSource
from app.core.config import Settings
from app.db.models import Document, DocumentChunk
from app.db.session import create_database_engine
from app.embeddings.models import DocumentEmbeddingInput, EmbeddingProfile
from app.rag.service import RagTutorService
from app.retrieval.service import SearchService
from sqlalchemy import delete
from sqlalchemy.orm import Session

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="set RUN_DATABASE_TESTS=1 to test the configured Neon database",
    ),
]


PROFILE = EmbeddingProfile("gemini", "gemini-embedding-2", 768, "retrieval-asymmetric-v1")


class TransactionCheckingEmbedding:
    profile = PROFILE

    def __init__(self, session: Session) -> None:
        self.session = session
        self.query_calls = 0

    def embed_query(self, query: str) -> list[float]:
        assert self.session.in_transaction() is False
        self.query_calls += 1
        return [1.0, *([0.0] * 767)]

    def embed_documents(self, inputs: list[DocumentEmbeddingInput]) -> list[list[float]]:
        raise AssertionError("indexing is not part of this test")


class TransactionCheckingChat:
    profile = "gemini:gemini-3.6-flash:grounded-tutor-v2"

    def __init__(self, session: Session) -> None:
        self.session = session
        self.calls = 0

    def generate(
        self,
        *,
        question: str,
        sources: list[TutorSource],
    ) -> ModelTutorOutput:
        assert self.session.in_transaction() is False
        self.calls += 1
        assert sources[0].excerpt == "Fungsi tanpa return eksplisit menghasilkan None."
        return ModelTutorOutput(
            status="answered",
            sections=[
                ModelAnswerSection(
                    text="Fungsi tersebut mengembalikan None.",
                    reference_ids=["S1"],
                )
            ],
        )


def test_neon_retrieval_and_grounded_citation_without_open_provider_transaction() -> None:
    settings = Settings()
    engine = create_database_engine(settings)
    token = uuid.uuid4().hex
    checksum = sha256(token.encode()).hexdigest()
    content = "Fungsi tanpa return eksplisit menghasilkan None."
    content_hash = sha256(content.encode()).hexdigest()
    corpus_hash = sha256(f"0:{content_hash}\n".encode()).hexdigest()
    try:
        with Session(engine, expire_on_commit=False) as session:
            document = Document(
                source_name=f"phase-6-{token}.txt",
                source_type="text",
                checksum_sha256=checksum,
                extraction_profile="text:utf-8-sig:v1",
                file_size_bytes=len(content.encode()),
                reference_text=content,
                status="processed",
                indexing_status="ready",
                embedding_provider=PROFILE.provider,
                embedding_model=PROFILE.model,
                embedding_dimensions=PROFILE.dimensions,
                embedding_input_version=PROFILE.input_version,
                embedding_profile=PROFILE.key,
                embedding_content_checksum=corpus_hash,
                extra_metadata={"test_token": token},
            )
            session.add(document)
            session.flush()
            session.add(
                DocumentChunk(
                    document_id=document.id,
                    chunk_index=0,
                    content=content,
                    content_sha256=content_hash,
                    embedding=[1.0, *([0.0] * 767)],
                    embedding_content_sha256=content_hash,
                    start_char=0,
                    end_char=len(content),
                    extra_metadata={"test_token": token},
                )
            )
            session.commit()

            embedding = TransactionCheckingEmbedding(session)
            chat = TransactionCheckingChat(session)
            response = RagTutorService(
                SearchService(session, embedding, settings), chat, settings
            ).answer(
                question="Mengapa fungsi dapat mengembalikan None?",
                top_k=1,
                document_ids=[document.id],
            )

            assert response.status == "answered"
            assert response.citations[0].document_id == document.id
            assert response.citations[0].excerpt == content
            assert embedding.query_calls == 1
            assert chat.calls == 1
    finally:
        with engine.begin() as connection:
            connection.execute(delete(Document).where(Document.checksum_sha256 == checksum))
        engine.dispose()
