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

_BOLD = {"textFormat": {"bold": True}}
# Column letter of the last Progress column ("N" for 14 columns).
_LAST_COL = chr(ord("A") + len(PROGRESS_HEADERS) - 1)


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

    def get_solves(self) -> list[Solve]:
        """All data rows of the Progress tab as Solve objects."""
        values = self._worksheet(PROGRESS_TAB).get_all_values()
        solves = []
        for row in values[1:]:  # skip the header row
            if not any(str(cell).strip() for cell in row):
                continue
            solves.append(Solve.from_row(row))
        return solves

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

    def get_solves(self) -> list[Solve]:
        return []

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
