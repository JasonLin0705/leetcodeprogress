"""Spaced-repetition review scheduling based on a 1-5 confidence score."""

from __future__ import annotations

import datetime

# Confidence -> days until the next review. None means no review is needed.
REVIEW_INTERVALS: dict[int, int | None] = {1: 1, 2: 3, 3: 7, 4: 14, 5: None}


def _validate_confidence(confidence: int) -> None:
    if confidence not in REVIEW_INTERVALS:
        raise ValueError(f"confidence must be in 1..5, got {confidence!r}")


def next_review_date(confidence: int, from_date: datetime.date | None = None) -> str:
    """Return the next review date as "YYYY-MM-DD", or "" if no review is needed.

    `from_date` defaults to today.
    """
    _validate_confidence(confidence)
    interval = REVIEW_INTERVALS[confidence]
    if interval is None:
        return ""
    if from_date is None:
        from_date = datetime.date.today()
    return (from_date + datetime.timedelta(days=interval)).isoformat()


def needs_review(confidence: int) -> str:
    """Return "TRUE" if the problem should be flagged for review, else "FALSE"."""
    _validate_confidence(confidence)
    return "TRUE" if confidence < 4 else "FALSE"
