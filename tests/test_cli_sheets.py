"""Tests for the CLI and sheet clients. No network, no real Google access."""

from __future__ import annotations

import datetime
import sys
import types

import pytest

from lptracker import cli
from lptracker.models import PROGRESS_HEADERS, Solve
from lptracker.review import needs_review, next_review_date
from lptracker.sheets import DryRunSheetClient, PROGRESS_TAB, STATS_TAB


# -- test doubles -------------------------------------------------------------


class FakeSheetClient:
    """Records every write so tests can assert on them."""

    def __init__(self, solves=None):
        self.solves = list(solves or [])
        self.appended = []
        self.updated = []  # (row_number, solve) pairs
        self.stats_rows = None
        self.init_called = False

    def init_sheet(self):
        self.init_called = True

    def get_solves(self):
        return list(self.solves)

    def append_solves(self, solves):
        self.appended.extend(solves)

    def update_solve(self, row_number, solve):
        self.updated.append((row_number, solve))

    def write_stats(self, rows):
        self.stats_rows = rows


def install_fake_leetcode(monkeypatch, submissions=None, details=None):
    """Inject a fake lptracker.leetcode module and return it.

    `details` maps slug -> question-details dict. Calls are recorded on the
    module as `detail_calls`.
    """
    fake = types.ModuleType("lptracker.leetcode")

    class LeetCodeError(Exception):
        pass

    fake.LeetCodeError = LeetCodeError
    fake.detail_calls = []

    def fetch_recent_ac_submissions(username, limit=20):
        return list(submissions or [])

    def fetch_question_details(slug):
        fake.detail_calls.append(slug)
        if details is None or slug not in details:
            raise AssertionError(f"unexpected fetch_question_details({slug!r})")
        return details[slug]

    fake.fetch_recent_ac_submissions = fetch_recent_ac_submissions
    fake.fetch_question_details = fetch_question_details
    monkeypatch.setitem(sys.modules, "lptracker.leetcode", fake)
    return fake


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("LEETCODE_USERNAME", "tester")
    monkeypatch.setenv("GOOGLE_SHEET_ID", "sheet123")
    monkeypatch.setenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")


def use_fake_client(monkeypatch, client):
    monkeypatch.setattr(cli, "_make_client", lambda args: client)
    return client


# -- DryRunSheetClient ---------------------------------------------------------


class TestDryRunSheetClient:
    def test_get_solves_is_empty(self):
        assert DryRunSheetClient().get_solves() == []

    def test_init_sheet_prints_plan(self, capsys):
        DryRunSheetClient().init_sheet()
        out = capsys.readouterr().out
        assert "[dry-run]" in out
        assert PROGRESS_TAB in out and STATS_TAB in out
        for header in PROGRESS_HEADERS:
            assert header in out

    def test_append_solves_prints_rows(self, capsys):
        solves = [Solve(slug="two-sum", title="Two Sum"), Solve(slug="lru-cache")]
        DryRunSheetClient().append_solves(solves)
        out = capsys.readouterr().out
        assert "would append 2 row(s)" in out
        assert "two-sum" in out and "lru-cache" in out

    def test_update_solve_prints_row_number(self, capsys):
        DryRunSheetClient().update_solve(7, Solve(slug="two-sum"))
        out = capsys.readouterr().out
        assert "row 7" in out and "two-sum" in out

    def test_write_stats_prints_rows(self, capsys):
        DryRunSheetClient().write_stats([["Total", "3"], ["Easy", "1"]])
        out = capsys.readouterr().out
        assert "would write 2 row(s)" in out
        assert "Total | 3" in out


# -- sync ----------------------------------------------------------------------


class TestSync:
    def test_sync_dedupes_and_appends_in_header_order(self, monkeypatch, env, capsys):
        existing = [Solve(frontend_id="1", title="Two Sum", slug="two-sum")]
        # two-sum already in the sheet; valid-anagram appears twice in the
        # batch (the older timestamp must win).
        t_old = 1_700_000_000
        t_new = 1_700_500_000
        install_fake_leetcode(
            monkeypatch,
            submissions=[
                {"title": "Two Sum", "slug": "two-sum", "timestamp": t_new, "lang": "python3"},
                {"title": "Valid Anagram", "slug": "valid-anagram", "timestamp": t_new, "lang": "python3"},
                {"title": "Valid Anagram", "slug": "valid-anagram", "timestamp": t_old, "lang": "cpp"},
            ],
            details={
                "valid-anagram": {
                    "frontend_id": "242",
                    "difficulty": "Easy",
                    "tags": ["Hash Table", "String"],
                }
            },
        )
        client = use_fake_client(monkeypatch, FakeSheetClient(existing))

        assert cli.main(["sync"]) == 0

        # Existing slug skipped; details fetched only for the new slug.
        fake = sys.modules["lptracker.leetcode"]
        assert fake.detail_calls == ["valid-anagram"]

        assert len(client.appended) == 1
        row = client.appended[0].to_row()
        assert len(row) == len(PROGRESS_HEADERS)
        idx = PROGRESS_HEADERS.index
        assert row[idx("#")] == "242"
        assert row[idx("Title")] == "Valid Anagram"
        assert row[idx("Slug")] == "valid-anagram"
        assert row[idx("Difficulty")] == "Easy"
        assert row[idx("Tags")] == "Hash Table, String"
        # Oldest submission kept: date and language come from the t_old entry.
        expected_date = datetime.date.fromtimestamp(t_old).isoformat()
        assert row[idx("Date Solved")] == expected_date
        assert row[idx("Language")] == "cpp"
        assert row[idx("Link")] == "https://leetcode.com/problems/valid-anagram/"
        # Manual fields left blank.
        for col in ("Time (min)", "Attempts", "Confidence (1-5)", "Notes"):
            assert row[idx(col)] == ""

        # Stats recomputed over existing + new solves.
        assert client.stats_rows is not None
        assert ["Total", "2"] in client.stats_rows

        out = capsys.readouterr().out
        assert "3 recent accepted submission(s)" in out
        assert "1 new" in out

    def test_sync_with_no_new_solves_still_writes_stats(self, monkeypatch, env, capsys):
        existing = [Solve(frontend_id="1", title="Two Sum", slug="two-sum")]
        install_fake_leetcode(
            monkeypatch,
            submissions=[
                {"title": "Two Sum", "slug": "two-sum", "timestamp": 1_700_000_000, "lang": "python3"}
            ],
        )
        client = use_fake_client(monkeypatch, FakeSheetClient(existing))

        assert cli.main(["sync"]) == 0
        assert client.appended == []
        assert ["Total", "1"] in client.stats_rows
        assert "0 new" in capsys.readouterr().out

    def test_sync_requires_username(self, monkeypatch, env, capsys):
        monkeypatch.delenv("LEETCODE_USERNAME")
        install_fake_leetcode(monkeypatch)
        use_fake_client(monkeypatch, FakeSheetClient())

        assert cli.main(["sync"]) == 1
        assert "LEETCODE_USERNAME" in capsys.readouterr().err

    def test_sync_reports_leetcode_error(self, monkeypatch, env, capsys):
        fake = install_fake_leetcode(monkeypatch)

        def boom(username, limit=20):
            raise fake.LeetCodeError("LeetCode API is unreachable")

        fake.fetch_recent_ac_submissions = boom
        use_fake_client(monkeypatch, FakeSheetClient())

        assert cli.main(["sync"]) == 1
        assert "LeetCode API is unreachable" in capsys.readouterr().err


# -- annotate ------------------------------------------------------------------


class TestAnnotate:
    def make_solves(self):
        return [
            Solve(frontend_id="1", title="Two Sum", slug="two-sum"),
            Solve(frontend_id="242", title="Valid Anagram", slug="valid-anagram"),
            Solve(frontend_id="146", title="LRU Cache", slug="lru-cache"),
        ]

    def test_annotate_updates_correct_row_and_review_fields(self, monkeypatch, env):
        client = use_fake_client(monkeypatch, FakeSheetClient(self.make_solves()))

        rc = cli.main(
            ["annotate", "valid-anagram", "--time", "25", "--attempts", "2",
             "--confidence", "2", "--notes", "sort both strings"]
        )
        assert rc == 0
        assert len(client.updated) == 1
        row_number, solve = client.updated[0]
        # Second data row -> sheet row 4 would be wrong; header offset is +2.
        assert row_number == 3
        assert solve.slug == "valid-anagram"
        assert solve.time_min == "25"
        assert solve.attempts == "2"
        assert solve.notes == "sort both strings"
        assert solve.confidence == "2"
        assert solve.needs_review == needs_review(2) == "TRUE"
        assert solve.next_review == next_review_date(2)
        assert solve.next_review  # confidence 2 always schedules a review

    def test_annotate_high_confidence_clears_review(self, monkeypatch, env):
        client = use_fake_client(monkeypatch, FakeSheetClient(self.make_solves()))

        assert cli.main(["annotate", "lru-cache", "--confidence", "5"]) == 0
        row_number, solve = client.updated[0]
        assert row_number == 4  # third data row
        assert solve.needs_review == "FALSE"
        assert solve.next_review == ""

    def test_annotate_matches_frontend_id(self, monkeypatch, env):
        client = use_fake_client(monkeypatch, FakeSheetClient(self.make_solves()))

        assert cli.main(["annotate", "1", "--time", "10"]) == 0
        row_number, solve = client.updated[0]
        assert row_number == 2  # first data row
        assert solve.slug == "two-sum"
        assert solve.time_min == "10"

    def test_annotate_not_found(self, monkeypatch, env, capsys):
        use_fake_client(monkeypatch, FakeSheetClient(self.make_solves()))

        assert cli.main(["annotate", "no-such-slug", "--time", "5"]) == 1
        assert "No row found" in capsys.readouterr().err

    def test_annotate_requires_a_field(self, monkeypatch, env, capsys):
        use_fake_client(monkeypatch, FakeSheetClient(self.make_solves()))

        assert cli.main(["annotate", "two-sum"]) == 1
        assert "Nothing to update" in capsys.readouterr().err

    def test_annotate_dry_run_explains_empty_lookup(self, monkeypatch, env, capsys):
        # With the real DryRunSheetClient, get_solves() is empty, so the
        # lookup misses; the error should explain the dry-run limitation.
        assert cli.main(["annotate", "two-sum", "--time", "5", "--dry-run"]) == 1
        err = capsys.readouterr().err
        assert "No row found" in err
        assert "dry-run" in err


# -- stats / init ---------------------------------------------------------------


class TestOtherCommands:
    def test_stats_prints_summary(self, monkeypatch, env, capsys):
        solves = [
            Solve(frontend_id="1", title="Two Sum", slug="two-sum",
                  difficulty="Easy", tags=["Array"], date_solved="2026-07-01"),
        ]
        use_fake_client(monkeypatch, FakeSheetClient(solves))

        assert cli.main(["stats"]) == 0
        out = capsys.readouterr().out
        assert "Total solved: 1" in out
        assert "Easy: 1" in out

    def test_init_calls_init_sheet(self, monkeypatch, env):
        client = use_fake_client(monkeypatch, FakeSheetClient())
        assert cli.main(["init"]) == 0
        assert client.init_called

    def test_init_dry_run_needs_no_google_config(self, monkeypatch, capsys):
        monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
        monkeypatch.delenv("GOOGLE_CREDENTIALS_FILE", raising=False)

        assert cli.main(["init", "--dry-run"]) == 0
        assert "[dry-run]" in capsys.readouterr().out

    def test_init_without_sheet_id_errors(self, monkeypatch, capsys):
        monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)

        assert cli.main(["init"]) == 1
        assert "GOOGLE_SHEET_ID" in capsys.readouterr().err
