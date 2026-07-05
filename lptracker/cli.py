"""Command-line interface for the LeetCode progress tracker."""

from __future__ import annotations

import argparse
import datetime
import importlib
import os
import sys

from dotenv import load_dotenv

from . import google, suggest
from .models import Solve
from .review import needs_review, next_review_date
from .sheets import (
    DATE_TAB,
    GOOGLE_TAB,
    SUGGESTIONS_TAB,
    TOPIC_TAB,
    DryRunSheetClient,
    SheetClient,
    SheetError,
)
from .stats import (
    by_date_rows,
    by_topic_rows,
    compute_stats,
    format_stats_text,
    stats_rows,
)

DEFAULT_SYNC_LIMIT = 20


class CliError(Exception):
    """Configuration or usage error reported to stderr with exit code 1."""


def _leetcode():
    """Import lptracker.leetcode lazily (patchable via sys.modules in tests)."""
    return importlib.import_module("lptracker.leetcode")


def _require_env(name: str, hint: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise CliError(
            f"{name} is not set. {hint} (copy .env.example to .env and fill it in)"
        )
    return value


def _make_client(args: argparse.Namespace):
    """Build the sheet client for a command. Kept small so tests can patch it."""
    if getattr(args, "dry_run", False):
        return DryRunSheetClient()
    sheet_id = _require_env("GOOGLE_SHEET_ID", "Set it to your Google Sheet's ID")
    credentials_file = os.environ.get("GOOGLE_CREDENTIALS_FILE", "").strip() or "credentials.json"
    return SheetClient(sheet_id, credentials_file)


# -- subcommand handlers -----------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    client = _make_client(args)
    client.init_sheet()
    if not args.dry_run:
        print("Sheet initialized: Progress and Stats tabs are ready.")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    username = _require_env("LEETCODE_USERNAME", "Set it to your LeetCode username")
    leetcode = _leetcode()

    submissions = leetcode.fetch_recent_ac_submissions(username, limit=args.limit)

    client = _make_client(args)
    existing = client.get_solves()
    existing_slugs = {solve.slug for solve in existing}

    # Dedupe within the fetched batch, keeping the OLDEST submission per slug
    # so date_solved reflects the first solve date in the batch.
    oldest_by_slug: dict[str, dict] = {}
    for sub in submissions:
        slug = sub["slug"]
        if slug not in oldest_by_slug or sub["timestamp"] < oldest_by_slug[slug]["timestamp"]:
            oldest_by_slug[slug] = sub

    new_subs = sorted(
        (sub for slug, sub in oldest_by_slug.items() if slug not in existing_slugs),
        key=lambda sub: sub["timestamp"],
    )

    new_solves: list[Solve] = []
    for sub in new_subs:
        details = leetcode.fetch_question_details(sub["slug"])
        new_solves.append(
            Solve(
                frontend_id=str(details["frontend_id"]),
                title=sub["title"],
                slug=sub["slug"],
                difficulty=details["difficulty"],
                tags=list(details["tags"]),
                date_solved=datetime.date.fromtimestamp(sub["timestamp"]).isoformat(),
                language=sub["lang"],
            )
        )

    if new_solves:
        client.append_solves(new_solves)

    all_solves = existing + new_solves
    stats = compute_stats(all_solves)
    _write_derived(client, stats, all_solves)

    print(
        f"Fetched {len(submissions)} recent accepted submission(s); "
        f"{len(new_solves)} new. Appended {len(new_solves)} row(s); "
        "stats, By Topic and Suggestions updated."
    )
    return 0


def _write_derived(client, stats: dict, all_solves: list[Solve]) -> None:
    """Write Stats, re-sort Progress, and rebuild every derived tab."""
    solved_slugs = {solve.slug for solve in all_solves}
    client.write_stats(stats_rows(stats))
    client.sort_progress()
    client.write_tab(TOPIC_TAB, by_topic_rows(all_solves))
    client.write_tab(DATE_TAB, by_date_rows(all_solves))
    client.write_tab(GOOGLE_TAB, google.google_prep_rows(solved_slugs))
    _refresh_suggestions(client, stats, all_solves)


def _refresh_suggestions(client, stats: dict, all_solves: list[Solve]) -> None:
    """Rebuild the Suggestions tab; never let a fetch failure break the caller."""
    solved_slugs = {solve.slug for solve in all_solves}
    weak = suggest.weakest_tags(stats)
    try:
        rows = suggest.build_suggestions(weak, solved_slugs)
    except Exception as exc:  # network/API hiccup shouldn't abort a sync
        print(f"warning: could not refresh suggestions: {exc}", file=sys.stderr)
        return
    client.write_tab(SUGGESTIONS_TAB, rows)


def _backfill_slugs(args: argparse.Namespace, leetcode) -> list[str]:
    """Resolve the list of solved slugs from --file or the LEETCODE_SESSION cookie."""
    if args.file:
        try:
            with open(args.file, encoding="utf-8") as handle:
                text = handle.read()
        except OSError as exc:
            raise CliError(f"Could not read --file {args.file!r}: {exc}")
        return [s.strip() for s in text.replace(",", "\n").split() if s.strip()]

    cookie = os.environ.get("LEETCODE_SESSION", "").strip()
    if cookie:
        return leetcode.fetch_solved_slugs(cookie)

    raise CliError(
        "Nothing to backfill from. Pass --file <slugs.txt>, or set "
        "LEETCODE_SESSION in .env to pull your full solved history (see README)."
    )


def cmd_backfill(args: argparse.Namespace) -> int:
    leetcode = _leetcode()
    slugs = _backfill_slugs(args, leetcode)

    client = _make_client(args)
    existing = client.get_solves()
    existing_slugs = {solve.slug for solve in existing}

    todo: list[str] = []
    seen: set[str] = set()
    for slug in slugs:
        if slug in existing_slugs or slug in seen:
            continue
        seen.add(slug)
        todo.append(slug)
    if args.limit is not None:
        todo = todo[: args.limit]

    print(
        f"{len(slugs)} solved found; {len(existing_slugs)} already tracked; "
        f"backfilling {len(todo)}."
    )

    new_solves: list[Solve] = []
    for i, slug in enumerate(todo, 1):
        try:
            details = leetcode.fetch_question_details(slug)
        except Exception as exc:  # one bad slug shouldn't abort the whole run
            print(f"  skip {slug}: {exc}", file=sys.stderr)
            continue
        new_solves.append(
            Solve(
                frontend_id=str(details["frontend_id"]),
                title=details.get("title") or slug,
                slug=slug,
                difficulty=details["difficulty"],
                tags=list(details["tags"]),
                date_solved="",  # historical solve date isn't available
                language="",
            )
        )
        if i % 25 == 0:
            print(f"  fetched {i}/{len(todo)} ...")

    if new_solves:
        client.append_solves(new_solves)

    all_solves = existing + new_solves
    _write_derived(client, compute_stats(all_solves), all_solves)

    if not args.dry_run:
        print(
            f"Backfilled {len(new_solves)} problem(s); the sheet now tracks "
            f"{len(all_solves)}. (Historical solves have a blank Date Solved.)"
        )
    return 0


def cmd_annotate(args: argparse.Namespace) -> int:
    if (
        args.time is None
        and args.attempts is None
        and args.confidence is None
        and args.notes is None
    ):
        raise CliError(
            "Nothing to update: pass at least one of "
            "--time, --attempts, --confidence, --notes."
        )

    client = _make_client(args)
    rows = client.get_rows()

    key = args.problem
    match = next(
        ((row_number, s) for row_number, s in rows if key in (s.slug, s.frontend_id)),
        None,
    )
    if match is None:
        message = f"No row found for {key!r} (matched against slug and #)."
        if args.dry_run:
            message += " Note: --dry-run reads no sheet data, so lookups always miss."
        raise CliError(message)

    row_number, solve = match
    if args.time is not None:
        solve.time_min = str(args.time)
    if args.attempts is not None:
        solve.attempts = str(args.attempts)
    if args.notes is not None:
        solve.notes = args.notes
    if args.confidence is not None:
        solve.confidence = str(args.confidence)
        solve.needs_review = needs_review(args.confidence)
        solve.next_review = next_review_date(args.confidence)
        if args.confidence == 5:
            solve.mastered = "TRUE"  # top confidence auto-ticks Mastered

    client.update_solve(row_number, solve)
    if not args.dry_run:
        print(f"Updated row {row_number} ({solve.slug}).")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    client = _make_client(args)
    solves = client.get_solves()
    print(format_stats_text(compute_stats(solves)))
    return 0


def cmd_suggest(args: argparse.Namespace) -> int:
    client = _make_client(args)
    solves = client.get_solves()
    stats = compute_stats(solves)
    solved_slugs = {solve.slug for solve in solves}
    weak = suggest.weakest_tags(stats, k=args.count)
    rows = suggest.build_suggestions(weak, solved_slugs, per_tag=args.per_tag)
    client.write_tab(SUGGESTIONS_TAB, rows)
    if not args.dry_run:
        scope = f"{len(weak)} topic(s), weakest first" if weak else "no topics solved yet"
        print(f"Suggestions updated ({scope}).")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    client = _make_client(args)
    solves = client.get_solves()
    today = datetime.date.today().isoformat()
    due = [
        s
        for s in solves
        if s.needs_review == "TRUE" and s.next_review and s.next_review <= today
    ]
    due.sort(key=lambda s: s.next_review)
    if not due:
        print("Nothing is due for review right now. ")
        return 0
    print(f"{len(due)} problem(s) due for review (as of {today}):")
    for s in due:
        print(f"  {s.next_review}  #{s.frontend_id}  {s.title}  ({s.difficulty})  {s.link}")
    return 0


# -- parser / entry point -----------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lptracker",
        description="Track LeetCode progress in a Google Sheet.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser(
        "init", help="Create the Progress and Stats tabs (idempotent)."
    )
    p_init.add_argument(
        "--dry-run", action="store_true", help="Print actions instead of writing."
    )
    p_init.set_defaults(func=cmd_init)

    p_sync = sub.add_parser(
        "sync", help="Fetch recent accepted submissions and append new solves."
    )
    p_sync.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_SYNC_LIMIT,
        metavar="N",
        help=f"Max recent submissions to fetch (default {DEFAULT_SYNC_LIMIT}).",
    )
    p_sync.add_argument(
        "--dry-run", action="store_true", help="Print actions instead of writing."
    )
    p_sync.set_defaults(func=cmd_sync)

    p_ann = sub.add_parser(
        "annotate", help="Fill in manual fields (time/attempts/confidence/notes)."
    )
    p_ann.add_argument(
        "problem", metavar="slug_or_id", help="Problem slug (e.g. two-sum) or number."
    )
    p_ann.add_argument("--time", type=int, metavar="MIN", help="Minutes spent.")
    p_ann.add_argument("--attempts", type=int, metavar="N", help="Number of attempts.")
    p_ann.add_argument(
        "--confidence",
        type=int,
        choices=range(1, 6),
        metavar="1-5",
        help="Confidence score; also sets Needs Review and Next Review.",
    )
    p_ann.add_argument("--notes", metavar="TEXT", help="Free-form notes.")
    p_ann.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print the change instead of writing. Note: reads no sheet data, "
            "so the row lookup will report 'not found'."
        ),
    )
    p_ann.set_defaults(func=cmd_annotate)

    p_stats = sub.add_parser("stats", help="Print a progress summary (read-only).")
    p_stats.set_defaults(func=cmd_stats)

    p_suggest = sub.add_parser(
        "suggest",
        help="Rebuild the Suggestions tab with problems in your weakest topics.",
    )
    p_suggest.add_argument(
        "--count", type=int, default=None, metavar="N",
        help="How many of your weakest topics to cover (default: every topic).",
    )
    p_suggest.add_argument(
        "--per-tag", type=int, default=3, metavar="N",
        help="How many problems to suggest per topic (default 3).",
    )
    p_suggest.add_argument(
        "--dry-run", action="store_true", help="Print actions instead of writing."
    )
    p_suggest.set_defaults(func=cmd_suggest)

    p_review = sub.add_parser(
        "review", help="List problems due for review today (read-only)."
    )
    p_review.set_defaults(func=cmd_review)

    p_backfill = sub.add_parser(
        "backfill",
        help="Import your full solved history (beyond the recent-submissions window).",
    )
    p_backfill.add_argument(
        "--file",
        metavar="PATH",
        help="File of solved slugs (newline- or comma-separated). "
        "If omitted, uses the LEETCODE_SESSION cookie to fetch them.",
    )
    p_backfill.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help="Only backfill the first N missing problems (useful for a trial run).",
    )
    p_backfill.add_argument(
        "--dry-run", action="store_true", help="Print actions instead of writing."
    )
    p_backfill.set_defaults(func=cmd_backfill)

    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (CliError, SheetError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # LeetCodeError is caught by name via its (lazily imported) module so
        # that --dry-run and tests work without the module's dependencies.
        leetcode_error = getattr(
            sys.modules.get("lptracker.leetcode"), "LeetCodeError", None
        )
        if leetcode_error is not None and isinstance(exc, leetcode_error):
            print(f"error: {exc}", file=sys.stderr)
            return 1
        raise
