"""Tests for lptracker.suggest and the leetcode helpers it relies on.

No network access: build_suggestions is driven with an injected fetcher.
"""

from __future__ import annotations

from lptracker.leetcode import slugify
from lptracker.suggest import SUGGESTION_HEADERS, build_suggestions, weakest_tags


# -- slugify ------------------------------------------------------------------


def test_slugify_examples():
    assert slugify("Heap (Priority Queue)") == "heap-priority-queue"
    assert slugify("Depth-First Search") == "depth-first-search"
    assert slugify("Union-Find") == "union-find"
    assert slugify("Dynamic Programming") == "dynamic-programming"


# -- weakest_tags -------------------------------------------------------------


def _stats(by_tag):
    return {"by_tag": by_tag}


def test_weakest_tags_returns_lowest_count_weakest_first():
    by_tag = [
        ("Array", 10),
        ("Hash Table", 8),
        ("Graph", 5),
        ("Two Pointers", 3),
        ("Trie", 2),
        ("Union-Find", 1),
    ]
    # Weakest 4, weakest first.
    assert weakest_tags(_stats(by_tag), k=4) == [
        "Union-Find",
        "Trie",
        "Two Pointers",
        "Graph",
    ]


def test_weakest_tags_empty():
    assert weakest_tags(_stats([]), k=4) == []
    assert weakest_tags({}, k=4) == []


def test_weakest_tags_fewer_than_k():
    by_tag = [("Array", 3), ("Graph", 1)]
    assert weakest_tags(_stats(by_tag), k=4) == ["Graph", "Array"]


def test_weakest_tags_all_topics_when_k_none():
    by_tag = [("Array", 10), ("Hash Table", 8), ("Graph", 5), ("Trie", 2)]
    # Default (k=None) covers every topic, weakest first.
    assert weakest_tags(_stats(by_tag)) == ["Trie", "Graph", "Hash Table", "Array"]


# -- build_suggestions --------------------------------------------------------


def _problem(fid, slug, title, diff, ac_rate, paid_only=False, status=None):
    return {
        "frontend_id": fid,
        "title": title,
        "slug": slug,
        "difficulty": diff,
        "ac_rate": ac_rate,
        "paid_only": paid_only,
        "status": status,
    }


def test_build_suggestions_filters_sorts_and_formats():
    canned = {
        "graph": [
            _problem("1", "solved-already", "Solved Already", "Easy", 90.0),
            _problem("2", "acd-problem", "AC Problem", "Easy", 80.0, status="ac"),
            _problem("3", "paid-problem", "Paid Problem", "Easy", 70.0, paid_only=True),
            _problem("4", "low-ac", "Low AC", "Hard", 30.0),
            _problem("5", "high-ac", "High AC", "Medium", 65.0),
            _problem("6", "mid-ac", "Mid AC", "Medium", 50.0),
        ],
    }

    calls = []

    def fetcher(tag_slug):
        calls.append(tag_slug)
        return canned[tag_slug]

    rows = build_suggestions(
        ["Graph"], solved_slugs={"solved-already"}, per_tag=2, fetcher=fetcher
    )

    # slugify was applied to the tag before fetching.
    assert calls == ["graph"]

    # Header first.
    assert rows[0] == SUGGESTION_HEADERS
    assert rows[0] == ["Topic", "#", "Title", "Difficulty", "Link", "Acceptance"]

    body = rows[1:]
    # paid, ac, and solved_slugs excluded; per_tag=2 keeps top-2 by ac desc:
    # high-ac (65) then mid-ac (50); low-ac (30) dropped by the limit.
    assert len(body) == 2
    assert [r[2] for r in body] == ["High AC", "Mid AC"]

    high = body[0]
    assert high == [
        "Graph",
        "5",
        "High AC",
        "Medium",
        '=HYPERLINK("https://leetcode.com/problems/high-ac/","↗")',
        "65.0%",
    ]


def test_build_suggestions_multiple_tags_in_order():
    canned = {
        "trie": [_problem("10", "t1", "Trie One", "Medium", 55.0)],
        "graph": [_problem("20", "g1", "Graph One", "Hard", 45.0)],
    }

    def fetcher(tag_slug):
        return canned[tag_slug]

    rows = build_suggestions(
        ["Trie", "Graph"], solved_slugs=set(), per_tag=3, fetcher=fetcher
    )
    body = rows[1:]
    assert [r[0] for r in body] == ["Trie", "Graph"]
    assert [r[1] for r in body] == ["10", "20"]


def test_build_suggestions_only_header_when_all_filtered():
    def fetcher(tag_slug):
        return [_problem("1", "s", "S", "Easy", 90.0, status="ac")]

    rows = build_suggestions(["Graph"], solved_slugs=set(), fetcher=fetcher)
    assert rows == [SUGGESTION_HEADERS]
