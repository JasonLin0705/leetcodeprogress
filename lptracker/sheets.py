"""Google Sheets access via a gspread service account.

`SheetClient` talks to a real spreadsheet; `DryRunSheetClient` implements the
same public interface but only prints what it would do, so no credentials
(and no gspread import) are needed for --dry-run.
"""

from __future__ import annotations

import os

from .models import PROGRESS_HEADERS, Solve

PROGRESS_TAB = "Progress"
STATS_TAB = "Stats"
TOPIC_TAB = "By Topic"
DATE_TAB = "By Date"
SUGGESTIONS_TAB = "Suggestions"
GOOGLE_TAB = "Google Prep"

_BOLD = {"textFormat": {"bold": True}}
# Column letter of the last Progress column ("O" for 15 columns).
_LAST_COL = chr(ord("A") + len(PROGRESS_HEADERS) - 1)
# Columns that identify a real solve. A row with all of these empty is blank,
# regardless of checkbox columns (which read back as "FALSE" when unset).
_IDENTITY_COLS = (
    PROGRESS_HEADERS.index("#"),
    PROGRESS_HEADERS.index("Title"),
    PROGRESS_HEADERS.index("Slug"),
)
# Highest sheet row we manage for per-column formatting/validation.
_MAX_ROWS = 1000


class SheetError(Exception):
    """Raised when the Google Sheet cannot be reached or is misconfigured."""


class SheetClient:
    """Lazy gspread client: authorizes and opens the sheet on first use."""

    def __init__(self, sheet_id: str, credentials_file: str):
        self.sheet_id = sheet_id
        self.credentials_file = credentials_file
        self._spreadsheet = None  # cached gspread Spreadsheet

    # -- internal helpers -------------------------------------------------

    def _open(self):
        """Authorize and open the spreadsheet, caching the handle."""
        if self._spreadsheet is not None:
            return self._spreadsheet

        if not os.path.exists(self.credentials_file):
            raise SheetError(
                f"Credentials file not found: {self.credentials_file!r}. "
                "Download a service-account JSON key from Google Cloud and "
                "set GOOGLE_CREDENTIALS_FILE in .env (see README for setup)."
            )

        import gspread

        try:
            gc = gspread.service_account(filename=self.credentials_file)
        except Exception as exc:  # bad/malformed key file
            raise SheetError(
                f"Could not authorize with {self.credentials_file!r}: {exc}. "
                "Make sure it is a valid service-account JSON key."
            ) from exc

        try:
            self._spreadsheet = gc.open_by_key(self.sheet_id)
        except gspread.SpreadsheetNotFound as exc:
            raise SheetError(
                f"Spreadsheet {self.sheet_id!r} not found. Check GOOGLE_SHEET_ID "
                "and make sure the sheet is shared with the service-account "
                "email (client_email in the credentials JSON) as Editor."
            ) from exc
        except gspread.exceptions.APIError as exc:
            raise SheetError(self._describe_api_error(exc)) from exc
        return self._spreadsheet

    def _describe_api_error(self, exc) -> str:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (403, 404):
            return (
                f"Cannot access spreadsheet {self.sheet_id!r} (HTTP {status}). "
                "Check GOOGLE_SHEET_ID, and share the sheet with the "
                "service-account email (client_email in the credentials JSON) "
                "as Editor. Also make sure the Google Sheets and Drive APIs "
                "are enabled for your Google Cloud project."
            )
        return f"Google Sheets API error: {exc}"

    def _worksheet(self, name: str):
        import gspread

        try:
            return self._open().worksheet(name)
        except gspread.WorksheetNotFound as exc:
            raise SheetError(
                f"Tab {name!r} not found in the spreadsheet — "
                "run `python -m lptracker init` first."
            ) from exc

    # -- public API --------------------------------------------------------

    def init_sheet(self) -> None:
        """Create the Progress/Stats tabs and header row. Safe to re-run."""
        import gspread

        spreadsheet = self._open()
        worksheets = {}
        for name, cols in ((PROGRESS_TAB, len(PROGRESS_HEADERS)), (STATS_TAB, 8)):
            try:
                worksheets[name] = spreadsheet.worksheet(name)
            except gspread.WorksheetNotFound:
                worksheets[name] = spreadsheet.add_worksheet(
                    title=name, rows=1000, cols=cols
                )

        progress = worksheets[PROGRESS_TAB]
        progress.update(values=[PROGRESS_HEADERS], range_name="A1")
        progress.format(f"A1:{_LAST_COL}1", _BOLD)
        progress.freeze(rows=1)

        stats = worksheets[STATS_TAB]
        stats.format("A1:B1", _BOLD)
        stats.freeze(rows=1)

        self._format_progress(progress)
        self._apply_checkboxes(progress, len(self.get_rows()))

    def _format_progress(self, progress) -> None:
        """Apply checkboxes, difficulty color-coding, and column widths.

        Runs one batch_update against the Progress tab. Adding conditional
        format rules on re-run simply layers more (harmless) rules, so this
        stays safe to call repeatedly from init_sheet.
        """
        import gspread

        sheet_id = progress.id
        col = PROGRESS_HEADERS.index

        def data_range(column: int) -> dict:
            return {
                "sheetId": sheet_id,
                "startRowIndex": 1,
                "endRowIndex": 1000,
                "startColumnIndex": column,
                "endColumnIndex": column + 1,
            }

        requests = []

        # (a) Color-code the Difficulty text value.
        difficulty_range = data_range(col("Difficulty"))
        difficulty_colors = (
            ("Easy", {"red": 0.85, "green": 0.94, "blue": 0.83}),
            ("Medium", {"red": 1.0, "green": 0.95, "blue": 0.8}),
            ("Hard", {"red": 0.96, "green": 0.8, "blue": 0.8}),
        )
        for index, (value, color) in enumerate(difficulty_colors):
            requests.append(
                {
                    "addConditionalFormatRule": {
                        "rule": {
                            "ranges": [difficulty_range],
                            "booleanRule": {
                                "condition": {
                                    "type": "TEXT_EQ",
                                    "values": [{"userEnteredValue": value}],
                                },
                                "format": {"backgroundColor": color},
                            },
                        },
                        "index": index,
                    }
                }
            )

        # (b) Column widths: narrow Link, wide Title and Notes.
        for name, width in (("Link", 45), ("Title", 320), ("Notes", 360)):
            column = col(name)
            requests.append(
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": column,
                            "endIndex": column + 1,
                        },
                        "properties": {"pixelSize": width},
                        "fields": "pixelSize",
                    }
                }
            )

        try:
            self._open().batch_update({"requests": requests})
        except gspread.exceptions.APIError as exc:
            raise SheetError(self._describe_api_error(exc)) from exc

    def _apply_checkboxes(self, progress, n_data_rows: int) -> None:
        """Make Mastered / Needs Review checkboxes over exactly the data rows.

        Validation is set only on rows 2..n_data_rows+1 and cleared below, so
        unset checkbox cells never leave stray ``FALSE`` values on empty rows
        (which would otherwise defeat blank-row detection in ``get_rows``).
        """
        import gspread

        sheet_id = progress.id
        first_data = 1  # 0-based row index of the first data row (sheet row 2)
        last_data = first_data + max(n_data_rows, 0)
        checkbox_rule = {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}

        requests = []
        for name in ("Mastered", "Needs Review"):
            column = PROGRESS_HEADERS.index(name)
            base = {
                "sheetId": sheet_id,
                "startColumnIndex": column,
                "endColumnIndex": column + 1,
            }
            if n_data_rows > 0:
                requests.append(
                    {
                        "setDataValidation": {
                            "range": {**base, "startRowIndex": first_data, "endRowIndex": last_data},
                            "rule": checkbox_rule,
                        }
                    }
                )
            # Clear validation on every row below the data (no "rule" => cleared).
            requests.append(
                {
                    "setDataValidation": {
                        "range": {**base, "startRowIndex": last_data, "endRowIndex": _MAX_ROWS},
                    }
                }
            )

        try:
            self._open().batch_update({"requests": requests})
        except gspread.exceptions.APIError as exc:
            raise SheetError(self._describe_api_error(exc)) from exc

    def get_rows(self) -> list[tuple[int, "Solve"]]:
        """All non-blank data rows as (sheet_row_number, Solve) pairs.

        The row number is the true 1-based index in the sheet (the header is
        row 1, so the first data row is 2). A row counts as blank when its
        identity columns (#, Title, Slug) are all empty — checkbox columns are
        ignored, since an unticked checkbox reads back as ``FALSE``.
        """
        values = self._worksheet(PROGRESS_TAB).get_all_values()
        rows = []
        for offset, row in enumerate(values[1:]):  # skip the header row
            if not any(str(row[i]).strip() for i in _IDENTITY_COLS if i < len(row)):
                continue
            rows.append((offset + 2, Solve.from_row(row)))
        return rows

    def get_solves(self) -> list[Solve]:
        """All data rows of the Progress tab as Solve objects."""
        return [solve for _, solve in self.get_rows()]

    def sort_progress(self) -> None:
        """Reorder the Progress data rows by topic, difficulty, then id.

        Sort key: primary tag (first of ``solve.tags``, or "" if none), then
        difficulty rank (Easy < Medium < Hard < other), then numeric frontend
        id (non-numeric ids sort last). Rewrites the whole data region in one
        update so every manual field on each Solve is preserved.
        """
        rows = self.get_rows()
        solves = [solve for _, solve in rows]
        if not solves:
            return

        difficulty_rank = {"Easy": 0, "Medium": 1, "Hard": 2}

        def sort_key(solve: Solve):
            primary_tag = solve.tags[0] if solve.tags else ""
            diff = difficulty_rank.get(solve.difficulty, 3)
            fid = int(solve.frontend_id) if solve.frontend_id.isdigit() else 10**9
            return (primary_tag, diff, fid)

        sorted_solves = sorted(solves, key=sort_key)

        worksheet = self._worksheet(PROGRESS_TAB)
        values = [s.to_row() for s in sorted_solves]

        # Clear the whole managed data region first so no stale rows (or rows
        # left over from a previous larger sheet) survive, then write the
        # sorted rows and re-scope the checkboxes to the new row count.
        worksheet.batch_clear([f"A2:{_LAST_COL}{_MAX_ROWS}"])
        worksheet.update(
            values=values,
            range_name=f"A2:{_LAST_COL}{len(values) + 1}",
            value_input_option="USER_ENTERED",
        )
        self._apply_checkboxes(worksheet, len(values))

    def append_solves(self, solves: list[Solve]) -> None:
        """Append rows for the given solves in one batch."""
        if not solves:
            return
        self._worksheet(PROGRESS_TAB).append_rows(
            [s.to_row() for s in solves], value_input_option="USER_ENTERED"
        )

    def update_solve(self, row_number: int, solve: Solve) -> None:
        """Overwrite one sheet row (1-based; header is row 1, data starts at 2)."""
        self._worksheet(PROGRESS_TAB).update(
            values=[solve.to_row()],
            range_name=f"A{row_number}:{_LAST_COL}{row_number}",
            value_input_option="USER_ENTERED",
        )

    def write_stats(self, rows: list[list[str]]) -> None:
        """Replace the entire Stats tab with the given rows (starting at A1)."""
        worksheet = self._worksheet(STATS_TAB)
        worksheet.clear()
        if rows:
            worksheet.update(values=rows, range_name="A1")

    def write_tab(self, name: str, rows: list[list[str]], header: bool = True) -> None:
        """Create the tab if missing, clear it, and write ``rows`` from A1.

        Uses USER_ENTERED so HYPERLINK formulas in cells evaluate. When
        ``header`` is true, the first row is bolded and frozen.
        """
        import gspread

        spreadsheet = self._open()
        try:
            worksheet = spreadsheet.worksheet(name)
        except gspread.WorksheetNotFound:
            width = max((len(r) for r in rows), default=1) or 1
            worksheet = spreadsheet.add_worksheet(title=name, rows=1000, cols=width)

        worksheet.clear()
        if not rows:
            return
        worksheet.update(values=rows, range_name="A1", value_input_option="USER_ENTERED")
        if header:
            worksheet.format("A1:Z1", _BOLD)
            worksheet.freeze(rows=1)


class DryRunSheetClient:
    """Same interface as SheetClient, but prints instead of writing."""

    def __init__(self, sheet_id: str = "", credentials_file: str = ""):
        self.sheet_id = sheet_id
        self.credentials_file = credentials_file

    def init_sheet(self) -> None:
        print(
            f"[dry-run] would create tabs {PROGRESS_TAB!r} and {STATS_TAB!r} "
            "(if missing), freeze and bold row 1 on both, and write the header:"
        )
        print("  " + " | ".join(PROGRESS_HEADERS))

    def get_rows(self) -> list[tuple[int, "Solve"]]:
        return []

    def get_solves(self) -> list[Solve]:
        return []

    def sort_progress(self) -> None:
        print(f"[dry-run] would sort the {PROGRESS_TAB!r} tab by topic")

    def append_solves(self, solves: list[Solve]) -> None:
        print(f"[dry-run] would append {len(solves)} row(s) to {PROGRESS_TAB!r}:")
        for solve in solves:
            print("  " + " | ".join(solve.to_row()))

    def update_solve(self, row_number: int, solve: Solve) -> None:
        print(f"[dry-run] would update row {row_number} of {PROGRESS_TAB!r}:")
        print("  " + " | ".join(solve.to_row()))

    def write_stats(self, rows: list[list[str]]) -> None:
        print(f"[dry-run] would write {len(rows)} row(s) to {STATS_TAB!r}:")
        for row in rows:
            print("  " + " | ".join(row))

    def write_tab(self, name: str, rows: list[list[str]], header: bool = True) -> None:
        print(f"[dry-run] would write {len(rows)} row(s) to {name!r}:")
        for row in rows:
            print("  " + " | ".join(row))
