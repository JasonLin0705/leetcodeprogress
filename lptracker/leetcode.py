"""Client for LeetCode's public GraphQL API.

Import-safe: no network calls happen at import time. All requests go
through the module-level ``_graphql`` helper, which tests can monkeypatch.
"""

from __future__ import annotations

import json
import re

import requests

GRAPHQL_URL = "https://leetcode.com/graphql"

_HEADERS = {
    "Content-Type": "application/json",
    "Referer": "https://leetcode.com",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

_TIMEOUT = 15

# Lazily created so importing the module never touches the network stack.
_session: requests.Session | None = None


class LeetCodeError(Exception):
    """Raised for HTTP errors, GraphQL error payloads, or malformed responses."""


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(_HEADERS)
    return _session


def _graphql(query: str, variables: dict) -> dict:
    """POST a GraphQL query and return the ``data`` dict.

    Raises LeetCodeError on non-200 responses, JSON decode failures, or a
    top-level "errors" list in the response.
    """
    try:
        resp = _get_session().post(
            GRAPHQL_URL,
            json={"query": query, "variables": variables},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise LeetCodeError(f"Request to LeetCode GraphQL API failed: {exc}") from exc

    if resp.status_code != 200:
        raise LeetCodeError(
            f"LeetCode GraphQL API returned HTTP {resp.status_code}: "
            f"{resp.text[:200]}"
        )

    try:
        payload = resp.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise LeetCodeError(
            f"LeetCode GraphQL API returned invalid JSON: {resp.text[:200]}"
        ) from exc

    if not isinstance(payload, dict):
        raise LeetCodeError(
            f"Unexpected response shape from LeetCode GraphQL API: {payload!r}"
        )

    if payload.get("errors"):
        messages = "; ".join(
            str(err.get("message", err)) if isinstance(err, dict) else str(err)
            for err in payload["errors"]
        )
        raise LeetCodeError(f"LeetCode GraphQL API returned errors: {messages}")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise LeetCodeError(
            f"LeetCode GraphQL API response missing 'data': {payload!r}"
        )
    return data


_RECENT_AC_QUERY_WITH_LANG = """
query recentAcSubmissions($username: String!, $limit: Int!) {
  recentAcSubmissionList(username: $username, limit: $limit) {
    id
    title
    titleSlug
    timestamp
    lang
  }
}
"""

_RECENT_AC_QUERY_NO_LANG = """
query recentAcSubmissions($username: String!, $limit: Int!) {
  recentAcSubmissionList(username: $username, limit: $limit) {
    id
    title
    titleSlug
    timestamp
  }
}
"""

_QUESTION_QUERY = """
query questionDetails($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    questionFrontendId
    title
    difficulty
    topicTags {
      name
    }
  }
}
"""


def slugify(name: str) -> str:
    """Convert a topic-tag display name to its LeetCode tag slug.

    Lowercase, collapse every run of non-alphanumeric characters into a
    single hyphen, and strip leading/trailing hyphens. For example,
    "Heap (Priority Queue)" -> "heap-priority-queue".
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


_PROBLEMS_BY_TAG_QUERY = """
query problemsetQuestionList($categorySlug: String, $limit: Int, $skip: Int, $filters: QuestionListFilterInput) {
  problemsetQuestionList: questionList(categorySlug: $categorySlug, limit: $limit, skip: $skip, filters: $filters) {
    questions: data {
      frontendQuestionId: questionFrontendId
      title
      titleSlug
      difficulty
      acRate
      paidOnly: isPaidOnly
      status
    }
  }
}
"""


def fetch_problems_by_tag(tag_slug: str, limit: int = 30) -> list[dict]:
    """Return problems tagged with ``tag_slug`` from the public problem list.

    Each item is {"frontend_id": str, "title": str, "slug": str,
    "difficulty": str, "ac_rate": float, "paid_only": bool,
    "status": str|None}. ``status`` is None when not logged in; "ac" means
    the problem is already solved. Raises LeetCodeError on API failures or a
    malformed response.
    """
    variables = {
        "categorySlug": "",
        "limit": limit,
        "skip": 0,
        "filters": {"tags": [tag_slug]},
    }
    data = _graphql(_PROBLEMS_BY_TAG_QUERY, variables)

    problem_list = data.get("problemsetQuestionList")
    if problem_list is None:
        raise LeetCodeError(
            f"No problem list returned for tag {tag_slug!r} "
            "(problemsetQuestionList is null). Check the tag slug."
        )
    if not isinstance(problem_list, dict):
        raise LeetCodeError(
            f"Malformed problem list for tag {tag_slug!r}: {problem_list!r}"
        )

    questions = problem_list.get("questions")
    if questions is None:
        raise LeetCodeError(
            f"No questions returned for tag {tag_slug!r} (questions is null)."
        )
    if not isinstance(questions, list):
        raise LeetCodeError(
            f"Malformed questions for tag {tag_slug!r}: {questions!r}"
        )

    results: list[dict] = []
    for item in questions:
        if not isinstance(item, dict):
            raise LeetCodeError(
                f"Malformed question entry for tag {tag_slug!r}: {item!r}"
            )
        try:
            ac_rate = float(item.get("acRate") or 0.0)
        except (TypeError, ValueError):
            ac_rate = 0.0
        status = item.get("status")
        results.append(
            {
                "frontend_id": str(item.get("frontendQuestionId", "")),
                "title": str(item.get("title", "")),
                "slug": str(item.get("titleSlug", "")),
                "difficulty": str(item.get("difficulty", "")),
                "ac_rate": ac_rate,
                "paid_only": bool(item.get("paidOnly")),
                "status": None if status is None else str(status),
            }
        )
    return results


def fetch_recent_ac_submissions(username: str, limit: int = 20) -> list[dict]:
    """Return the user's most recent accepted submissions, newest first.

    Each item is {"title": str, "slug": str, "timestamp": int, "lang": str}.
    Raises LeetCodeError for unknown usernames or API failures.
    """
    variables = {"username": username, "limit": limit}
    try:
        data = _graphql(_RECENT_AC_QUERY_WITH_LANG, variables)
    except LeetCodeError as exc:
        # Some API versions reject the `lang` field on this query; retry
        # without it and default lang to "".
        if "lang" not in str(exc):
            raise
        data = _graphql(_RECENT_AC_QUERY_NO_LANG, variables)

    submissions = data.get("recentAcSubmissionList")
    if submissions is None:
        raise LeetCodeError(
            f"LeetCode user {username!r} not found (recentAcSubmissionList is "
            "null). Check the username spelling."
        )
    if not isinstance(submissions, list):
        raise LeetCodeError(
            f"Malformed recentAcSubmissionList for user {username!r}: "
            f"{submissions!r}"
        )

    results: list[dict] = []
    for item in submissions:
        if not isinstance(item, dict):
            raise LeetCodeError(
                f"Malformed submission entry for user {username!r}: {item!r}"
            )
        try:
            timestamp = int(item["timestamp"])
        except (KeyError, TypeError, ValueError) as exc:
            raise LeetCodeError(
                f"Malformed submission timestamp for user {username!r}: "
                f"{item!r}"
            ) from exc
        results.append(
            {
                "title": str(item.get("title", "")),
                "slug": str(item.get("titleSlug", "")),
                "timestamp": timestamp,
                "lang": str(item.get("lang") or ""),
            }
        )
    return results


def fetch_question_details(slug: str) -> dict:
    """Return details for a question by slug.

    Result is {"frontend_id": str, "title": str, "difficulty": str,
    "tags": list[str]}. Raises LeetCodeError if the question doesn't exist or
    the API fails.
    """
    data = _graphql(_QUESTION_QUERY, {"titleSlug": slug})

    question = data.get("question")
    if question is None:
        raise LeetCodeError(
            f"LeetCode question {slug!r} not found (question is null). "
            "Check the problem slug."
        )
    if not isinstance(question, dict):
        raise LeetCodeError(f"Malformed question payload for {slug!r}: {question!r}")

    raw_tags = question.get("topicTags") or []
    if not isinstance(raw_tags, list):
        raise LeetCodeError(f"Malformed topicTags for {slug!r}: {raw_tags!r}")
    tags = [
        str(tag.get("name", ""))
        for tag in raw_tags
        if isinstance(tag, dict) and tag.get("name")
    ]

    return {
        "frontend_id": str(question.get("questionFrontendId", "")),
        "title": str(question.get("title", "")),
        "difficulty": str(question.get("difficulty", "")),
        "tags": tags,
    }


_ALL_PROBLEMS_URL = "https://leetcode.com/api/problems/all/"


def fetch_solved_slugs(session_cookie: str) -> list[str]:
    """Return the title-slugs of every problem the user has solved.

    Uses the ``/api/problems/all/`` endpoint authenticated with the account's
    ``LEETCODE_SESSION`` cookie, which tags each problem with the caller's
    personal status. This is the only way to see solves older than the ~20
    most recent that ``fetch_recent_ac_submissions`` returns.
    """
    cookie = (session_cookie or "").strip()
    if not cookie:
        raise LeetCodeError(
            "No LEETCODE_SESSION cookie provided. Copy the LEETCODE_SESSION "
            "cookie value from your browser (DevTools -> Application -> Cookies) "
            "into LEETCODE_SESSION in .env to backfill your full history."
        )
    try:
        resp = _get_session().get(
            _ALL_PROBLEMS_URL,
            cookies={"LEETCODE_SESSION": cookie},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise LeetCodeError(f"Request to {_ALL_PROBLEMS_URL} failed: {exc}") from exc

    if resp.status_code != 200:
        raise LeetCodeError(
            f"{_ALL_PROBLEMS_URL} returned HTTP {resp.status_code}. Your "
            "LEETCODE_SESSION cookie may be missing or expired."
        )
    try:
        payload = resp.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise LeetCodeError(
            f"{_ALL_PROBLEMS_URL} returned invalid JSON: {resp.text[:200]}"
        ) from exc

    pairs = payload.get("stat_status_pairs")
    if not isinstance(pairs, list):
        raise LeetCodeError(
            "Unexpected response from LeetCode: no 'stat_status_pairs'. "
            "Check that your LEETCODE_SESSION cookie is valid."
        )
    slugs = [
        p["stat"]["question__title_slug"]
        for p in pairs
        if isinstance(p, dict)
        and p.get("status") == "ac"
        and isinstance(p.get("stat"), dict)
        and p["stat"].get("question__title_slug")
    ]
    return slugs
