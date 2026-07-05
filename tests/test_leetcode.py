"""Tests for lptracker.leetcode — HTTP layer is mocked, no real network calls."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from lptracker import leetcode
from lptracker.leetcode import (
    LeetCodeError,
    fetch_question_details,
    fetch_recent_ac_submissions,
)


def _fake_response(payload, status_code=200, text=None):
    """Build a mock requests.Response-alike."""
    resp = mock.Mock()
    resp.status_code = status_code
    resp.text = text if text is not None else json.dumps(payload)
    if payload is None:
        resp.json.side_effect = json.JSONDecodeError("Expecting value", resp.text, 0)
    else:
        resp.json.return_value = payload
    return resp


def _patch_post(monkeypatch, payload, status_code=200, text=None):
    """Patch the module's session so its .post returns a canned response."""
    session = mock.Mock()
    session.post.return_value = _fake_response(payload, status_code, text)
    monkeypatch.setattr(leetcode, "_session", session)
    return session


# Realistic recorded-style payload from recentAcSubmissionList.
RECENT_AC_PAYLOAD = {
    "data": {
        "recentAcSubmissionList": [
            {
                "id": "1234567890",
                "title": "Two Sum",
                "titleSlug": "two-sum",
                "timestamp": "1719878400",
                "lang": "python3",
            },
            {
                "id": "1234567889",
                "title": "Longest Substring Without Repeating Characters",
                "titleSlug": "longest-substring-without-repeating-characters",
                "timestamp": "1719792000",
                "lang": "cpp",
            },
            {
                "id": "1234567888",
                "title": "Median of Two Sorted Arrays",
                "titleSlug": "median-of-two-sorted-arrays",
                "timestamp": 1719705600,
                "lang": "java",
            },
        ]
    }
}


class TestFetchRecentAcSubmissions:
    def test_successful_parse(self, monkeypatch):
        session = _patch_post(monkeypatch, RECENT_AC_PAYLOAD)

        result = fetch_recent_ac_submissions("lee215", limit=3)

        assert result == [
            {
                "title": "Two Sum",
                "slug": "two-sum",
                "timestamp": 1719878400,
                "lang": "python3",
            },
            {
                "title": "Longest Substring Without Repeating Characters",
                "slug": "longest-substring-without-repeating-characters",
                "timestamp": 1719792000,
                "lang": "cpp",
            },
            {
                "title": "Median of Two Sorted Arrays",
                "slug": "median-of-two-sorted-arrays",
                "timestamp": 1719705600,
                "lang": "java",
            },
        ]

        # Verify the request that went out.
        _, kwargs = session.post.call_args
        body = kwargs["json"]
        assert body["variables"] == {"username": "lee215", "limit": 3}
        assert "recentAcSubmissionList" in body["query"]

    def test_timestamp_coerced_to_int(self, monkeypatch):
        _patch_post(monkeypatch, RECENT_AC_PAYLOAD)
        result = fetch_recent_ac_submissions("lee215")
        # First entry's timestamp is a string in the fixture.
        assert isinstance(result[0]["timestamp"], int)
        assert result[0]["timestamp"] == 1719878400
        assert all(isinstance(item["timestamp"], int) for item in result)

    def test_unknown_user_null_list_raises(self, monkeypatch):
        _patch_post(monkeypatch, {"data": {"recentAcSubmissionList": None}})
        with pytest.raises(LeetCodeError) as excinfo:
            fetch_recent_ac_submissions("no-such-user-xyz")
        assert "no-such-user-xyz" in str(excinfo.value)

    def test_graphql_errors_payload_raises(self, monkeypatch):
        _patch_post(
            monkeypatch,
            {
                "errors": [
                    {"message": "That user does not exist."},
                ],
                "data": None,
            },
        )
        with pytest.raises(LeetCodeError) as excinfo:
            fetch_recent_ac_submissions("someone")
        assert "That user does not exist." in str(excinfo.value)

    def test_lang_rejected_retries_without_lang(self, monkeypatch):
        """If the API rejects the `lang` field, retry without it; lang = ''."""
        error_payload = {
            "errors": [
                {
                    "message": (
                        'Cannot query field "lang" on type "SubmissionDump".'
                    )
                }
            ]
        }
        ok_payload = {
            "data": {
                "recentAcSubmissionList": [
                    {
                        "id": "1",
                        "title": "Two Sum",
                        "titleSlug": "two-sum",
                        "timestamp": "1719878400",
                    }
                ]
            }
        }
        session = mock.Mock()
        session.post.side_effect = [
            _fake_response(error_payload),
            _fake_response(ok_payload),
        ]
        monkeypatch.setattr(leetcode, "_session", session)

        result = fetch_recent_ac_submissions("lee215")
        assert result == [
            {
                "title": "Two Sum",
                "slug": "two-sum",
                "timestamp": 1719878400,
                "lang": "",
            }
        ]
        assert session.post.call_count == 2
        retry_query = session.post.call_args_list[1].kwargs["json"]["query"]
        assert "lang" not in retry_query

    def test_http_error_raises(self, monkeypatch):
        _patch_post(monkeypatch, {}, status_code=403, text="forbidden")
        with pytest.raises(LeetCodeError) as excinfo:
            fetch_recent_ac_submissions("lee215")
        assert "403" in str(excinfo.value)

    def test_json_decode_failure_raises(self, monkeypatch):
        _patch_post(monkeypatch, None, text="<html>not json</html>")
        with pytest.raises(LeetCodeError):
            fetch_recent_ac_submissions("lee215")


class TestFetchQuestionDetails:
    def test_successful_parse_with_topic_tags_flattened(self, monkeypatch):
        session = _patch_post(
            monkeypatch,
            {
                "data": {
                    "question": {
                        "questionFrontendId": "1",
                        "title": "Two Sum",
                        "difficulty": "Easy",
                        "topicTags": [
                            {"name": "Array"},
                            {"name": "Hash Table"},
                        ],
                    }
                }
            },
        )

        result = fetch_question_details("two-sum")

        assert result == {
            "frontend_id": "1",
            "title": "Two Sum",
            "difficulty": "Easy",
            "tags": ["Array", "Hash Table"],
        }
        _, kwargs = session.post.call_args
        assert kwargs["json"]["variables"] == {"titleSlug": "two-sum"}

    def test_unknown_slug_null_question_raises(self, monkeypatch):
        _patch_post(monkeypatch, {"data": {"question": None}})
        with pytest.raises(LeetCodeError) as excinfo:
            fetch_question_details("not-a-real-problem")
        assert "not-a-real-problem" in str(excinfo.value)

    def test_empty_topic_tags(self, monkeypatch):
        _patch_post(
            monkeypatch,
            {
                "data": {
                    "question": {
                        "questionFrontendId": "9999",
                        "difficulty": "Hard",
                        "topicTags": [],
                    }
                }
            },
        )
        result = fetch_question_details("some-problem")
        assert result["tags"] == []
        assert result["difficulty"] == "Hard"
