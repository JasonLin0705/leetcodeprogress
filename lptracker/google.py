"""Google-interview problem suggestions.

Backed by a bundled dataset of problems tagged for Google, ordered by how
frequently they're reported in Google interviews. The data lives in
``data/google_problems.csv`` (columns: slug, title, difficulty, frequency,
topics) so the tool stays self-contained and needs no LeetCode Premium.
"""

from __future__ import annotations

import csv
from pathlib import Path

GOOGLE_HEADERS = ["Freq", "Title", "Difficulty", "Topics", "Link"]

_DATA_FILE = Path(__file__).parent / "data" / "google_problems.csv"


def load_google_problems() -> list[dict]:
    """Load the bundled Google problem list (most-frequent first)."""
    problems: list[dict] = []
    with open(_DATA_FILE, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                frequency = float(row.get("frequency") or 0.0)
            except ValueError:
                frequency = 0.0
            problems.append(
                {
                    "slug": (row.get("slug") or "").strip(),
                    "title": (row.get("title") or "").strip(),
                    "difficulty": (row.get("difficulty") or "").strip(),
                    "frequency": frequency,
                    "topics": (row.get("topics") or "").strip(),
                }
            )
    problems.sort(key=lambda p: -p["frequency"])
    return problems


def google_prep_rows(solved_slugs: set[str], limit: int | None = None) -> list[list[str]]:
    """Rows for the "Google Prep" tab: unsolved Google problems, most-asked first.

    Filters out anything already in ``solved_slugs`` and keeps the dataset's
    frequency order so the highest-signal problems for a Google interview come
    first. ``limit`` caps the number of suggestions when set.
    """
    rows: list[list[str]] = [list(GOOGLE_HEADERS)]
    count = 0
    for p in load_google_problems():
        slug = p["slug"]
        if not slug or slug in solved_slugs:
            continue
        rows.append(
            [
                f"{p['frequency']:.0f}",
                p["title"],
                p["difficulty"],
                p["topics"],
                f'=HYPERLINK("https://leetcode.com/problems/{slug}/","↗")',
            ]
        )
        count += 1
        if limit is not None and count >= limit:
            break
    return rows
