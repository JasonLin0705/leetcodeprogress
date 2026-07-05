"""Tests for the bundled Google-interview problem suggestions."""

from __future__ import annotations

from lptracker.google import GOOGLE_HEADERS, google_prep_rows, load_google_problems


def test_load_google_problems_nonempty_and_freq_sorted():
    problems = load_google_problems()
    assert len(problems) > 50
    freqs = [p["frequency"] for p in problems]
    assert freqs == sorted(freqs, reverse=True)  # most-asked first
    assert all(p["slug"] for p in problems)


def test_google_prep_rows_header_and_excludes_solved():
    all_problems = load_google_problems()
    top_slug = all_problems[0]["slug"]

    rows = google_prep_rows(solved_slugs={top_slug})
    assert rows[0] == GOOGLE_HEADERS

    body = rows[1:]
    # The solved top problem is filtered out (match the exact problem URL, not
    # a substring — e.g. "two-sum" is a prefix of "two-sum-ii-...").
    excluded = f'/problems/{top_slug}/"'
    assert all(excluded not in row[4] for row in body)
    # Rows carry a HYPERLINK link cell.
    assert body[0][4].startswith("=HYPERLINK(")


def test_google_prep_rows_respects_limit():
    rows = google_prep_rows(solved_slugs=set(), limit=5)
    assert len(rows) == 6  # header + 5
