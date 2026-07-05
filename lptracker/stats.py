"""Compute summary statistics from a list of Solve records."""

from __future__ import annotations

import datetime
from collections import Counter

from .models import Solve

DIFFICULTIES = ["Easy", "Medium", "Hard"]
WEEKS_SHOWN = 8


def _parse_date(value: str) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _week_monday(day: datetime.date) -> datetime.date:
    return day - datetime.timedelta(days=day.weekday())


def compute_stats(solves: list[Solve], today: datetime.date | None = None) -> dict:
    """Compute totals, difficulty/tag breakdowns, weekly counts and streak."""
    if today is None:
        today = datetime.date.today()

    by_difficulty: dict[str, int] = {d: 0 for d in DIFFICULTIES}
    tag_counts: Counter[str] = Counter()
    solve_dates: set[datetime.date] = set()

    for solve in solves:
        if solve.difficulty in by_difficulty:
            by_difficulty[solve.difficulty] += 1
        tag_counts.update(solve.tags)
        parsed = _parse_date(solve.date_solved)
        if parsed is not None:
            solve_dates.add(parsed)

    by_tag = sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))

    # Last WEEKS_SHOWN ISO weeks including the current one, oldest first.
    week_counts: Counter[datetime.date] = Counter()
    for solve in solves:
        parsed = _parse_date(solve.date_solved)
        if parsed is not None:
            week_counts[_week_monday(parsed)] += 1

    current_monday = _week_monday(today)
    per_week: list[tuple[str, int]] = []
    for offset in range(WEEKS_SHOWN - 1, -1, -1):
        monday = current_monday - datetime.timedelta(weeks=offset)
        per_week.append((monday.isoformat(), week_counts.get(monday, 0)))

    # Consecutive-day streak counting back from today (or yesterday, so the
    # streak survives until a full day is missed).
    streak = 0
    cursor = today
    if cursor not in solve_dates:
        cursor = today - datetime.timedelta(days=1)
    while cursor in solve_dates:
        streak += 1
        cursor -= datetime.timedelta(days=1)

    return {
        "total": len(solves),
        "by_difficulty": by_difficulty,
        "by_tag": by_tag,
        "per_week": per_week,
        "streak": streak,
    }


def stats_rows(stats: dict) -> list[list[str]]:
    """Rows for the "Stats" sheet tab. All cell values are strings."""
    rows: list[list[str]] = [
        ["Totals"],
        ["Total", str(stats["total"])],
    ]
    for difficulty in DIFFICULTIES:
        rows.append([difficulty, str(stats["by_difficulty"][difficulty])])
    rows.append([])

    rows.append(["By Topic"])
    for tag, count in stats["by_tag"]:
        rows.append([tag, str(count)])
    rows.append([])

    rows.append(["Solves Per Week"])
    for week_of, count in stats["per_week"]:
        rows.append([week_of, str(count)])
    rows.append([])

    rows.append(["Current Streak (days)", str(stats["streak"])])
    return rows


def by_topic_rows(solves: list[Solve]) -> list[list[str]]:
    """Rows for the "By Topic" tab: solved problems grouped under each tag.

    Tags are ordered by how many solves they have (most first, then name).
    A problem with several tags appears under each of them. Within a tag,
    problems are listed by difficulty (Easy -> Medium -> Hard) then number.
    """
    difficulty_rank = {d: i for i, d in enumerate(DIFFICULTIES)}

    by_tag: dict[str, list[Solve]] = {}
    for solve in solves:
        for tag in solve.tags:
            by_tag.setdefault(tag, []).append(solve)

    ordered_tags = sorted(by_tag, key=lambda tag: (-len(by_tag[tag]), tag))

    def _num(solve: Solve) -> int:
        try:
            return int(solve.frontend_id)
        except (TypeError, ValueError):
            return 10**9

    rows: list[list[str]] = []
    for tag in ordered_tags:
        problems = sorted(
            by_tag[tag],
            key=lambda s: (difficulty_rank.get(s.difficulty, len(DIFFICULTIES)), _num(s)),
        )
        rows.append([f"{tag} ({len(problems)})"])
        for solve in problems:
            rows.append(["", solve.frontend_id, solve.title, solve.difficulty, solve.link_cell()])
        rows.append([])
    return rows


def by_date_rows(solves: list[Solve]) -> list[list[str]]:
    """Rows for the "By Date" tab: a solve timeline, newest date first.

    Problems with a valid Date Solved are grouped under a date heading
    (most recent first). Problems without a date — e.g. backfilled history,
    where LeetCode doesn't expose the original solve date — are collected
    under a trailing "Undated (backfilled)" section, sorted by number.
    """
    dated: dict[str, list[Solve]] = {}
    undated: list[Solve] = []
    for solve in solves:
        if _parse_date(solve.date_solved) is not None:
            dated.setdefault(solve.date_solved, []).append(solve)
        else:
            undated.append(solve)

    def _num(solve: Solve) -> int:
        try:
            return int(solve.frontend_id)
        except (TypeError, ValueError):
            return 10**9

    rows: list[list[str]] = []
    for date in sorted(dated, reverse=True):  # newest first
        problems = sorted(dated[date], key=_num)
        rows.append([f"{date} ({len(problems)})"])
        for solve in problems:
            rows.append(["", solve.frontend_id, solve.title, solve.difficulty, solve.link_cell()])
        rows.append([])

    if undated:
        rows.append([f"Undated (backfilled) ({len(undated)})"])
        for solve in sorted(undated, key=_num):
            rows.append(["", solve.frontend_id, solve.title, solve.difficulty, solve.link_cell()])
        rows.append([])
    return rows


def format_stats_text(stats: dict) -> str:
    """Human-readable multi-line summary for terminal output."""
    lines: list[str] = [
        "LeetCode Progress",
        "=================",
        f"Total solved: {stats['total']}",
        "",
        "By difficulty:",
    ]
    for difficulty in DIFFICULTIES:
        lines.append(f"  {difficulty}: {stats['by_difficulty'][difficulty]}")

    lines.append("")
    lines.append("By topic:")
    if stats["by_tag"]:
        for tag, count in stats["by_tag"]:
            lines.append(f"  {tag}: {count}")
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append("Solves per week (week of):")
    for week_of, count in stats["per_week"]:
        lines.append(f"  {week_of}: {count}")

    lines.append("")
    lines.append(f"Current streak: {stats['streak']} day(s)")
    return "\n".join(lines)
