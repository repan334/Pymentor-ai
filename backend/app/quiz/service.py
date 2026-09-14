from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.chat.models import TutorSource
from app.core.config import Settings
from app.db.models import (
    Quiz,
    QuizAttempt,
    QuizAttemptAnswer,
    QuizOption,
    QuizQuestion,
    QuizQuestionSource,
)
from app.quiz.models import (
    AttemptInputError,
    AttemptNotFound,
    AttemptView,
    GeneratedQuizOutput,
    IdempotencyConflict,
    QuestionReview,
    QuizGenerationAdapter,
    QuizInputError,
    QuizInsufficientContext,
    QuizNotFound,
    QuizOptionView,
    QuizOutputInvalid,
    QuizQuestionView,
    QuizSourceView,
    QuizView,
    SubmittedAnswer,
)
from app.quiz.prompt import QUIZ_SYSTEM_INSTRUCTION, build_quiz_prompt
from app.retrieval.service import SearchHit, SearchService


class QuizService:
    def __init__(
        self,
        session: Session,
        search_service: SearchService,
        chat_adapter: QuizGenerationAdapter,
        settings: Settings,
    ) -> None:
        self.session = session
        self.search_service = search_service
        self.chat_adapter = chat_adapter
        self.settings = settings

    def create_quiz(
        self,
        *,
        topic: str,
        document_ids: Sequence[int] | None,
        question_count: int,
    ) -> QuizView:
        self._validate_create_input(topic, document_ids, question_count)
        search = self.search_service.search(
            query=topic,
            top_k=self.settings.quiz_retrieval_top_k,
            document_ids=document_ids,
        )
        if not search.results:
            raise QuizInsufficientContext("No eligible source context is available")
        sources, metadata = self._build_context(search.results, document_ids)
        if not sources:
            raise QuizInsufficientContext("No usable source context is available")

        output = self.chat_adapter.generate_structured(
            prompt=build_quiz_prompt(topic, question_count, sources),
            system_instruction=QUIZ_SYSTEM_INSTRUCTION,
            response_model=GeneratedQuizOutput,
            max_output_tokens=self.settings.quiz_max_output_tokens,
            thinking_budget=self.settings.quiz_thinking_budget,
            temperature=self.settings.chat_temperature,
        )
        validated = self._validate_generated(output, question_count, sources)
        try:
            quiz = Quiz(
                topic=topic,
                question_count=question_count,
                document_ids=None if document_ids is None else list(document_ids),
                llm_provider=self.settings.llm_provider,
                llm_model=self.settings.llm_model,
                prompt_version=self.settings.quiz_prompt_version,
                generation_profile=self.settings.quiz_generation_profile_key,
            )
            self.session.add(quiz)
            self.session.flush()
            source_map = {source.reference_id: source for source in sources}
            for question_index, generated in enumerate(validated.questions):
                question = QuizQuestion(
                    quiz_id=quiz.id,
                    question_index=question_index,
                    prompt=generated.question.strip(),
                    explanation=generated.explanation.strip(),
                )
                self.session.add(question)
                self.session.flush()
                self.session.add_all(
                    [
                        QuizOption(
                            question_id=question.id,
                            option_index=option_index,
                            text=option.strip(),
                            is_correct=option_index == generated.correct_option_index,
                        )
                        for option_index, option in enumerate(generated.options)
                    ]
                )
                for reference_id in dict.fromkeys(generated.reference_ids):
                    source = source_map[reference_id]
                    self.session.add(
                        QuizQuestionSource(
                            question_id=question.id,
                            reference_id=reference_id,
                            document_id=source.document_id,
                            chunk_id=source.chunk_id,
                            source_name=source.source_name,
                            start_char=source.start_char,
                            end_char=source.end_char,
                            excerpt=source.excerpt,
                            page_number=source.page_number,
                            extra_metadata=metadata[(source.document_id, source.chunk_id)],
                        )
                    )
            self.session.commit()
            return self.get_quiz(quiz.id)
        except Exception:
            self.session.rollback()
            raise

    def get_quiz(self, quiz_id: int) -> QuizView:
        quiz = self._load_quiz(quiz_id)
        return _quiz_view(quiz)

    def submit_attempt(
        self,
        *,
        quiz_id: int,
        idempotency_key: str,
        answers: Sequence[SubmittedAnswer],
    ) -> AttemptView:
        key = idempotency_key.strip()
        if not key or len(key) > 100:
            raise AttemptInputError("Idempotency-Key must contain 1 to 100 characters")
        payload_hash = _answer_payload_hash(answers)
        quiz = self._load_quiz(quiz_id)
        existing = self._find_attempt(quiz_id, key)
        if existing is not None:
            return self._replay_or_conflict(existing, payload_hash)

        selected = self._validate_answers(quiz, answers)
        correct_count, total, percentage = _score_selected(selected)
        try:
            attempt = QuizAttempt(
                quiz_id=quiz.id,
                idempotency_key=key,
                payload_sha256=payload_hash,
                correct_count=correct_count,
                total_questions=total,
                percentage=percentage,
            )
            self.session.add(attempt)
            self.session.flush()
            self.session.add_all(
                [
                    QuizAttemptAnswer(
                        attempt_id=attempt.id,
                        question_id=question.id,
                        selected_option_id=option.id,
                        is_correct=option.is_correct,
                    )
                    for question, option in selected
                ]
            )
            self.session.commit()
            return self.get_attempt(attempt.id)
        except IntegrityError:
            self.session.rollback()
            winner = self._find_attempt(quiz_id, key)
            if winner is None:
                raise
            return self._replay_or_conflict(winner, payload_hash)
        except Exception:
            self.session.rollback()
            raise

    def get_attempt(self, attempt_id: int) -> AttemptView:
        attempt = self.session.get(QuizAttempt, attempt_id)
        if attempt is None:
            raise AttemptNotFound(attempt_id)
        quiz = self._load_quiz(attempt.quiz_id)
        answer_rows = self.session.scalars(
            select(QuizAttemptAnswer).where(QuizAttemptAnswer.attempt_id == attempt.id)
        ).all()
        answer_map = {answer.question_id: answer for answer in answer_rows}
        review: list[QuestionReview] = []
        for question in quiz.questions:
            answer = answer_map.get(question.id)
            if answer is None:
                raise AttemptInputError("Stored attempt is incomplete")
            correct = next(option for option in question.options if option.is_correct)
            review.append(
                QuestionReview(
                    question_id=question.id,
                    selected_option_id=answer.selected_option_id,
                    correct_option_id=correct.id,
                    is_correct=answer.is_correct,
                    explanation=question.explanation,
                    sources=tuple(_source_view(source) for source in question.sources),
                )
            )
        return AttemptView(
            id=attempt.id,
            quiz_id=attempt.quiz_id,
            correct_count=attempt.correct_count,
            question_count=attempt.total_questions,
            percentage=float(attempt.percentage),
            review=tuple(review),
            created_at=attempt.created_at,
        )

    def _validate_create_input(
        self,
        topic: str,
        document_ids: Sequence[int] | None,
        question_count: int,
    ) -> None:
        if not topic.strip() or len(topic) > self.settings.quiz_max_topic_characters:
            raise QuizInputError("Topic is blank or exceeds the configured limit")
        if not 1 <= question_count <= self.settings.quiz_max_question_count:
            raise QuizInputError("question_count exceeds the configured range")
        if document_ids is not None and len(document_ids) > self.settings.chat_max_document_ids:
            raise QuizInputError("document_ids exceeds the configured limit")

    def _build_context(
        self,
        hits: Sequence[SearchHit],
        document_ids: Sequence[int] | None,
    ) -> tuple[tuple[TutorSource, ...], dict[tuple[int, int], dict[str, Any]]]:
        remaining = self.settings.quiz_max_context_characters
        allowed = set(document_ids) if document_ids is not None else None
        seen: set[tuple[int, int]] = set()
        sources: list[TutorSource] = []
        metadata: dict[tuple[int, int], dict[str, Any]] = {}
        for hit in hits:
            identity = (hit.document_id, hit.chunk_id)
            if allowed is not None and hit.document_id not in allowed:
                raise QuizOutputInvalid("Retrieval returned a source outside document scope")
            if identity in seen or remaining <= 0:
                continue
            seen.add(identity)
            take = min(len(hit.content), self.settings.quiz_max_context_chunk_characters, remaining)
            excerpt = hit.content[:take]
            if not excerpt.strip():
                continue
            source = TutorSource(
                reference_id=f"S{len(sources) + 1}",
                document_id=hit.document_id,
                chunk_id=hit.chunk_id,
                source_name=hit.source_name,
                start_char=hit.start_char,
                end_char=hit.start_char + len(excerpt),
                excerpt=excerpt,
                page_number=hit.page_number,
            )
            sources.append(source)
            metadata[identity] = dict(hit.metadata)
            remaining -= len(excerpt)
        return tuple(sources), metadata

    def _validate_generated(
        self,
        output: GeneratedQuizOutput,
        question_count: int,
        sources: Sequence[TutorSource],
    ) -> GeneratedQuizOutput:
        if output.status == "insufficient_context":
            if output.questions:
                raise QuizOutputInvalid("Insufficient output must not contain questions")
            raise QuizInsufficientContext("The model reports insufficient source context")
        if len(output.questions) != question_count:
            raise QuizOutputInvalid("The provider returned an incomplete quiz")
        valid_refs = {source.reference_id for source in sources}
        prompts: set[str] = set()
        for question in output.questions:
            prompt = question.question.strip()
            explanation = question.explanation.strip()
            options = [option.strip() for option in question.options]
            if not prompt or not explanation or any(not option for option in options):
                raise QuizOutputInvalid("Quiz text fields must not be blank")
            if prompt.casefold() in prompts:
                raise QuizOutputInvalid("Quiz questions must be distinct")
            prompts.add(prompt.casefold())
            if len({option.casefold() for option in options}) != 4:
                raise QuizOutputInvalid("Every question must have four distinct options")
            if not set(question.reference_ids) <= valid_refs:
                raise QuizOutputInvalid("A quiz question cited a source outside context")
        return output

    def _load_quiz(self, quiz_id: int) -> Quiz:
        quiz = self.session.scalar(
            select(Quiz)
            .where(Quiz.id == quiz_id)
            .options(
                selectinload(Quiz.questions).selectinload(QuizQuestion.options),
                selectinload(Quiz.questions).selectinload(QuizQuestion.sources),
            )
        )
        if quiz is None:
            raise QuizNotFound(quiz_id)
        return quiz

    def _find_attempt(self, quiz_id: int, key: str) -> QuizAttempt | None:
        return self.session.scalar(
            select(QuizAttempt).where(
                QuizAttempt.quiz_id == quiz_id, QuizAttempt.idempotency_key == key
            )
        )

    def _replay_or_conflict(self, attempt: QuizAttempt, payload_hash: str) -> AttemptView:
        if attempt.payload_sha256 != payload_hash:
            raise IdempotencyConflict("Idempotency-Key was already used with another payload")
        result = self.get_attempt(attempt.id)
        return AttemptView(
            id=result.id,
            quiz_id=result.quiz_id,
            correct_count=result.correct_count,
            question_count=result.question_count,
            percentage=result.percentage,
            review=result.review,
            created_at=result.created_at,
            idempotent_replay=True,
        )

    def _validate_answers(
        self,
        quiz: Quiz,
        answers: Sequence[SubmittedAnswer],
    ) -> list[tuple[QuizQuestion, QuizOption]]:
        if len(answers) != len(quiz.questions):
            raise AttemptInputError("Every quiz question must be answered exactly once")
        if len({answer.question_id for answer in answers}) != len(answers):
            raise AttemptInputError("A question must not be answered more than once")
        answer_map = {answer.question_id: answer.option_id for answer in answers}
        if set(answer_map) != {question.id for question in quiz.questions}:
            raise AttemptInputError("All questions must belong to the submitted quiz")
        selected: list[tuple[QuizQuestion, QuizOption]] = []
        for question in quiz.questions:
            option = next(
                (item for item in question.options if item.id == answer_map[question.id]), None
            )
            if option is None:
                raise AttemptInputError("Selected option does not belong to its question")
            selected.append((question, option))
        return selected


def _answer_payload_hash(answers: Sequence[SubmittedAnswer]) -> str:
    canonical = sorted(
        ({"question_id": answer.question_id, "option_id": answer.option_id} for answer in answers),
        key=lambda item: (item["question_id"], item["option_id"]),
    )
    return sha256(json.dumps(canonical, separators=(",", ":")).encode()).hexdigest()


def _score_selected(
    selected: Sequence[tuple[QuizQuestion, QuizOption]],
) -> tuple[int, int, Decimal]:
    if not selected:
        raise AttemptInputError("A quiz attempt must contain answers")
    correct_count = sum(option.is_correct for _, option in selected)
    total = len(selected)
    percentage = (Decimal(correct_count) * Decimal(100) / Decimal(total)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return correct_count, total, percentage


def _quiz_view(quiz: Quiz) -> QuizView:
    return QuizView(
        id=quiz.id,
        topic=quiz.topic,
        question_count=quiz.question_count,
        questions=tuple(
            QuizQuestionView(
                id=question.id,
                question=question.prompt,
                options=tuple(
                    QuizOptionView(id=option.id, text=option.text) for option in question.options
                ),
            )
            for question in quiz.questions
        ),
        created_at=quiz.created_at,
    )


def _source_view(source: QuizQuestionSource) -> QuizSourceView:
    return QuizSourceView(
        reference_id=source.reference_id,
        document_id=source.document_id,
        chunk_id=source.chunk_id,
        source_name=source.source_name,
        start_char=source.start_char,
        end_char=source.end_char,
        excerpt=source.excerpt,
        page_number=source.page_number,
        metadata=dict(source.extra_metadata),
    )
