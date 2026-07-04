"""Client for LeetCode's public GraphQL API.

Import-safe: no network calls happen at import time. All requests go
through the module-level ``_graphql`` helper, which tests can monkeypatch.
"""

from __future__ import annotations

import json

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
    difficulty
    topicTags {
      name
    }
  }
}
"""


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

    Result is {"frontend_id": str, "difficulty": str, "tags": list[str]}.
    Raises LeetCodeError if the question doesn't exist or the API fails.
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
        "difficulty": str(question.get("difficulty", "")),
        "tags": tags,
    }
