from decimal import Decimal

import pytest
from app.progress.models import TopicInputError
from app.progress.service import (
    calculate_topic_progress,
    derive_difficulty,
    validate_topic_id,
)


@pytest.mark.parametrize(
    ("correct", "total", "score", "recommendation"),
    [
        (0, 0, None, "insufficient_evidence"),
        (1, 4, Decimal("25.00"), "insufficient_evidence"),
        (2, 5, Decimal("40.00"), "review_material"),
        (3, 5, Decimal("60.00"), "practice_more"),
        (2, 3, Decimal("66.67"), "insufficient_evidence"),
        (4, 5, Decimal("80.00"), "try_advanced"),
        (5, 5, Decimal("100.00"), "try_advanced"),
    ],
)
def test_progress_rounding_evidence_and_recommendation_boundaries(
    correct: int,
    total: int,
    score: Decimal | None,
    recommendation: str,
) -> None:
    assert calculate_topic_progress(correct_questions=correct, counted_questions=total) == (
        score,
        recommendation,
    )


@pytest.mark.parametrize("correct,total", [(-1, 0), (1, -1), (6, 5)])
def test_progress_rejects_inconsistent_counts(correct: int, total: int) -> None:
    with pytest.raises(ValueError):
        calculate_topic_progress(correct_questions=correct, counted_questions=total)


@pytest.mark.parametrize(
    ("recommendation", "difficulty"),
    [
        ("insufficient_evidence", "basic"),
        ("review_material", "basic"),
        ("practice_more", "intermediate"),
        ("try_advanced", "advanced"),
    ],
)
def test_difficulty_derivation_is_rule_based_without_model_call(
    recommendation: str, difficulty: str
) -> None:
    assert derive_difficulty(recommendation) == difficulty


@pytest.mark.parametrize(
    "value", ["Python", "python functions", "-python", "python-", "python--functions", "a" * 65]
)
def test_topic_id_must_be_a_stable_lowercase_slug(value: str) -> None:
    with pytest.raises(TopicInputError):
        validate_topic_id(value)


def test_valid_topic_id_is_preserved() -> None:
    assert validate_topic_id("python-functions") == "python-functions"
