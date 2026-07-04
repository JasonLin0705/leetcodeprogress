"""Shared data model: a solved problem and its mapping to a sheet row."""

from __future__ import annotations

from dataclasses import dataclass, field

# Column order of the "Progress" tab. Everything that reads or writes rows
# goes through Solve.to_row / Solve.from_row so this is the single source
# of truth.
PROGRESS_HEADERS = [
    "#",
    "Title",
    "Slug",
    "Difficulty",
    "Tags",
    "Date Solved",
    "Language",
    "Link",
    "Time (min)",
    "Attempts",
    "Confidence (1-5)",
    "Needs Review",
    "Next Review",
    "Notes",
]


@dataclass
class Solve:
    frontend_id: str = ""
    title: str = ""
    slug: str = ""
    difficulty: str = ""
    tags: list[str] = field(default_factory=list)
    date_solved: str = ""  # YYYY-MM-DD
    language: str = ""
    time_min: str = ""
    attempts: str = ""
    confidence: str = ""
    needs_review: str = ""  # "TRUE" / "FALSE" / ""
    next_review: str = ""  # YYYY-MM-DD or ""
    notes: str = ""

    @property
    def link(self) -> str:
        return f"https://leetcode.com/problems/{self.slug}/" if self.slug else ""

    def to_row(self) -> list[str]:
        return [
            self.frontend_id,
            self.title,
            self.slug,
            self.difficulty,
            ", ".join(self.tags),
            self.date_solved,
            self.language,
            self.link,
            self.time_min,
            self.attempts,
            self.confidence,
            self.needs_review,
            self.next_review,
            self.notes,
        ]

    @classmethod
    def from_row(cls, row: list[str]) -> "Solve":
        # Rows read back from the sheet may be shorter than the header if
        # trailing cells are empty.
        padded = list(row) + [""] * (len(PROGRESS_HEADERS) - len(row))
        return cls(
            frontend_id=str(padded[0]),
            title=str(padded[1]),
            slug=str(padded[2]),
            difficulty=str(padded[3]),
            tags=[t.strip() for t in str(padded[4]).split(",") if t.strip()],
            date_solved=str(padded[5]),
            language=str(padded[6]),
            time_min=str(padded[8]),
            attempts=str(padded[9]),
            confidence=str(padded[10]),
            needs_review=str(padded[11]),
            next_review=str(padded[12]),
            notes=str(padded[13]),
        )
