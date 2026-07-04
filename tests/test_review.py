"""Tests for lptracker.review."""

import datetime

import pytest

from lptracker.review import REVIEW_INTERVALS, needs_review, next_review_date

FROM_DATE = datetime.date(2026, 6, 15)  # a fixed Monday


def test_review_intervals_mapping():
    assert REVIEW_INTERVALS == {1: 1, 2: 3, 3: 7, 4: 14, 5: None}


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [
        (1, "2026-06-16"),
        (2, "2026-06-18"),
        (3, "2026-06-22"),
        (4, "2026-06-29"),
    ],
)
def test_next_review_date_intervals(confidence, expected):
    assert next_review_date(confidence, FROM_DATE) == expected


def test_next_review_date_confidence_5_is_empty():
    assert next_review_date(5, FROM_DATE) == ""


def test_next_review_date_crosses_month_boundary():
    assert next_review_date(4, datetime.date(2026, 1, 25)) == "2026-02-08"


def test_next_review_date_defaults_to_today():
    expected = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    assert next_review_date(1) == expected


@pytest.mark.parametrize("bad", [0, 6, -1, 100])
def test_next_review_date_invalid_confidence(bad):
    with pytest.raises(ValueError):
        next_review_date(bad, FROM_DATE)


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [
        (1, "TRUE"),
        (2, "TRUE"),
        (3, "TRUE"),
        (4, "FALSE"),
        (5, "FALSE"),
    ],
)
def test_needs_review_boundaries(confidence, expected):
    assert needs_review(confidence) == expected


@pytest.mark.parametrize("bad", [0, 6])
def test_needs_review_invalid_confidence(bad):
    with pytest.raises(ValueError):
        needs_review(bad)
