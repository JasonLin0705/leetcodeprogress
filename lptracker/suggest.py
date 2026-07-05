"""Weakest-topic problem suggestions."""

from __future__ import annotations

SUGGESTION_HEADERS = ["Topic", "#", "Title", "Difficulty", "Link", "Acceptance"]


def weakest_tags(stats: dict, k: int | None = None) -> list[str]:
    """Return tag names ordered weakest (fewest-solved) first.

    ``stats`` is the dict from lptracker.stats.compute_stats; its "by_tag"
    value is a list of (tag_name, count) tuples already sorted by count
    descending then name ascending. When ``k`` is None (the default) every
    tag is returned, weakest first; otherwise only the ``k`` weakest. Empty
    by_tag -> [].
    """
    by_tag = stats.get("by_tag") or []
    if not by_tag:
        return []
    if k is None:
        weakest = by_tag
    elif k > 0:
        weakest = by_tag[-k:]
    else:
        return []
    # by_tag is count-descending, so its tail is weakest-last; reverse for
    # weakest-first order.
    return [name for name, _count in reversed(weakest)]


def build_suggestions(
    weak_tags: list[str],
    solved_slugs: set[str],
    per_tag: int = 3,
    fetcher=None,
) -> list[list[str]]:
    """Build rows for a "Suggestions" sheet tab.

    For each tag in ``weak_tags`` (in order), fetch its problems, drop the
    ones that are paid-only, already solved (status == "ac"), or whose slug
    is in ``solved_slugs``, sort the rest by acceptance rate descending
    (most approachable first), and keep the first ``per_tag``. Returns a
    header row followed by the suggestion rows.

    ``fetcher`` defaults to lptracker.leetcode.fetch_problems_by_tag and is
    injectable for testing. leetcode is imported lazily so no network call
    happens at import time.
    """
    from . import leetcode

    if fetcher is None:
        fetcher = leetcode.fetch_problems_by_tag

    rows: list[list[str]] = [list(SUGGESTION_HEADERS)]

    for tag in weak_tags:
        problems = fetcher(leetcode.slugify(tag))
        candidates = [
            p
            for p in problems
            if not p.get("paid_only")
            and p.get("status") != "ac"
            and p.get("slug") not in solved_slugs
        ]
        candidates.sort(key=lambda p: p.get("ac_rate", 0.0), reverse=True)
        for p in candidates[:per_tag]:
            slug = p.get("slug", "")
            rows.append(
                [
                    tag,
                    str(p.get("frontend_id", "")),
                    str(p.get("title", "")),
                    str(p.get("difficulty", "")),
                    f'=HYPERLINK("https://leetcode.com/problems/{slug}/","↗")',
                    f"{float(p.get('ac_rate', 0.0)):.1f}%",
                ]
            )

    return rows
