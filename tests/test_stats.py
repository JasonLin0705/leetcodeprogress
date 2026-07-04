"""Tests for lptracker.stats."""

import datetime

from lptracker.models import Solve
from lptracker.stats import compute_stats, format_stats_text, stats_rows

TODAY = datetime.date(2026, 7, 1)  # a fixed Wednesday; week Monday is 2026-06-29


def make_solve(**kwargs) -> Solve:
    return Solve(**kwargs)


def test_empty_list():
    stats = compute_stats([], today=TODAY)
    assert stats["total"] == 0
    assert stats["by_difficulty"] == {"Easy": 0, "Medium": 0, "Hard": 0}
    assert stats["by_tag"] == []
    assert stats["streak"] == 0
    assert len(stats["per_week"]) == 8
    assert all(count == 0 for _, count in stats["per_week"])


def test_totals_and_difficulty_counts():
    solves = [
        make_solve(difficulty="Easy", date_solved="2026-06-30"),
        make_solve(difficulty="Easy", date_solved="2026-06-30"),
        make_solve(difficulty="Medium", date_solved="2026-06-29"),
        make_solve(difficulty="Hard", date_solved="2026-06-28"),
        make_solve(difficulty="", date_solved="2026-06-27"),  # unknown difficulty
    ]
    stats = compute_stats(solves, today=TODAY)
    assert stats["total"] == 5
    assert stats["by_difficulty"] == {"Easy": 2, "Medium": 1, "Hard": 1}


def test_by_tag_sorted_count_desc_then_name_asc():
    solves = [
        make_solve(tags=["Array", "Hash Table"], date_solved="2026-06-30"),
        make_solve(tags=["Array", "Two Pointers"], date_solved="2026-06-30"),
        make_solve(tags=["Hash Table"], date_solved="2026-06-29"),
        make_solve(tags=["Binary Search"], date_solved="2026-06-29"),
    ]
    stats = compute_stats(solves, today=TODAY)
    assert stats["by_tag"] == [
        ("Array", 2),
        ("Hash Table", 2),
        ("Binary Search", 1),
        ("Two Pointers", 1),
    ]


def test_per_week_last_8_weeks_oldest_first():
    stats = compute_stats([], today=TODAY)
    expected_mondays = [
        "2026-05-11",
        "2026-05-18",
        "2026-05-25",
        "2026-06-01",
        "2026-06-08",
        "2026-06-15",
        "2026-06-22",
        "2026-06-29",
    ]
    assert [week for week, _ in stats["per_week"]] == expected_mondays


def test_per_week_bucketing_across_week_boundary():
    solves = [
        # Sunday 2026-06-28 -> week of Monday 2026-06-22.
        make_solve(date_solved="2026-06-28"),
        # Monday 2026-06-29 -> current week 2026-06-29.
        make_solve(date_solved="2026-06-29"),
        make_solve(date_solved="2026-07-01"),
        # Older solve within the window: week of 2026-05-11.
        make_solve(date_solved="2026-05-13"),
        # Outside the 8-week window: ignored.
        make_solve(date_solved="2026-01-01"),
        # Empty / unparseable dates are skipped.
        make_solve(date_solved=""),
        make_solve(date_solved="not-a-date"),
    ]
    stats = compute_stats(solves, today=TODAY)
    per_week = dict(stats["per_week"])
    assert per_week["2026-06-22"] == 1
    assert per_week["2026-06-29"] == 2
    assert per_week["2026-05-11"] == 1
    assert per_week["2026-05-18"] == 0
    assert "2026-01-01" not in per_week
    assert len(stats["per_week"]) == 8


def test_streak_active_today():
    solves = [
        make_solve(date_solved="2026-07-01"),
        make_solve(date_solved="2026-06-30"),
        make_solve(date_solved="2026-06-29"),
        make_solve(date_solved="2026-06-27"),  # gap on 06-28 stops the count
    ]
    stats = compute_stats(solves, today=TODAY)
    assert stats["streak"] == 3


def test_streak_active_as_of_yesterday():
    # No solve today, but yesterday and the day before count.
    solves = [
        make_solve(date_solved="2026-06-30"),
        make_solve(date_solved="2026-06-29"),
    ]
    stats = compute_stats(solves, today=TODAY)
    assert stats["streak"] == 2


def test_streak_broken():
    # Most recent solve was two days ago: streak is 0.
    solves = [
        make_solve(date_solved="2026-06-29"),
        make_solve(date_solved="2026-06-28"),
    ]
    stats = compute_stats(solves, today=TODAY)
    assert stats["streak"] == 0


def test_streak_multiple_solves_same_day_count_once():
    solves = [
        make_solve(date_solved="2026-07-01"),
        make_solve(date_solved="2026-07-01"),
    ]
    stats = compute_stats(solves, today=TODAY)
    assert stats["streak"] == 1


def _sample_stats():
    solves = [
        make_solve(difficulty="Easy", tags=["Array"], date_solved="2026-07-01"),
        make_solve(difficulty="Hard", tags=["Graph", "Array"], date_solved="2026-06-30"),
    ]
    return compute_stats(solves, today=TODAY)


def test_stats_rows_structure():
    rows = stats_rows(_sample_stats())
    assert all(all(isinstance(cell, str) for cell in row) for row in rows)
    assert rows[0] == ["Totals"]
    assert rows[1] == ["Total", "2"]
    assert rows[2] == ["Easy", "1"]
    assert rows[3] == ["Medium", "0"]
    assert rows[4] == ["Hard", "1"]
    assert rows[5] == []
    assert rows[6] == ["By Topic"]
    assert rows[7] == ["Array", "2"]
    assert rows[8] == ["Graph", "1"]
    assert rows[9] == []
    assert rows[10] == ["Solves Per Week"]
    week_rows = rows[11:19]
    assert len(week_rows) == 8
    assert week_rows[0] == ["2026-05-11", "0"]
    assert week_rows[-1] == ["2026-06-29", "2"]
    assert rows[19] == []
    assert rows[20] == ["Current Streak (days)", "2"]


def test_format_stats_text_contains_all_sections():
    text = format_stats_text(_sample_stats())
    assert "Total solved: 2" in text
    assert "Easy: 1" in text
    assert "Medium: 0" in text
    assert "Hard: 1" in text
    assert "Array: 2" in text
    assert "Graph: 1" in text
    assert "2026-06-29: 2" in text
    assert "streak: 2" in text
