# LeetCode Progress Tracker

Sync your LeetCode solves into a Google Sheet and keep them fresh with
spaced-repetition review scheduling.

## Features

- **Auto-sync from LeetCode** — pulls your recent accepted submissions
  (title, difficulty, tags, language, solve date, link) from LeetCode's
  public API. No LeetCode login required.
- **Google Sheets as the database** — a `Progress` tab with one row per
  problem, readable and editable anywhere.
- **Spaced repetition** — rate each solve 1–5 with `annotate`; low
  confidence schedules a `Next Review` date (1 → tomorrow, 2 → 3 days,
  3 → 1 week, 4 → 2 weeks, 5 → no review needed).
- **Stats tab** — totals, difficulty and topic breakdowns, solves per week,
  and your current daily streak, recomputed on every sync.

## Quick start

```bash
git clone <this-repo> && cd leetcodeprogress
pip install -r requirements.txt
cp .env.example .env   # then fill it in (see below)
```

## Google service-account setup

The tracker writes to your sheet as a *service account* — a robot Google
identity with its own email address. One-time setup:

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and
   create a new project (any name).
2. Enable the **Google Sheets API** and the **Google Drive API** for the
   project (APIs & Services → Library).
3. Create a **service account** (APIs & Services → Credentials → Create
   Credentials → Service account). No special roles are needed.
4. Open the service account → Keys → Add key → **JSON**, and save the
   downloaded file as `credentials.json` in the repo root (it is
   gitignored — never commit it).
5. Create a new Google Sheet in your own account.
6. **Share the sheet** with the service account's email address (the
   `client_email` value inside `credentials.json`) with **Editor** access.
7. Copy the sheet ID from the URL
   (`https://docs.google.com/spreadsheets/d/<SHEET_ID>/edit`) into `.env`:

```dotenv
LEETCODE_USERNAME=your_username
GOOGLE_SHEET_ID=your_sheet_id
GOOGLE_CREDENTIALS_FILE=credentials.json
```

## Usage

```bash
# One-time: create the Progress and Stats tabs (safe to re-run)
python -m lptracker init

# Pull recent accepted submissions and append anything new
python -m lptracker sync
python -m lptracker sync --limit 15

# Fill in the manual fields for a problem (by slug or problem number)
python -m lptracker annotate two-sum --time 25 --attempts 2 --confidence 3 \
    --notes "hash map; watch the duplicate-index case"
python -m lptracker annotate 146 --confidence 5

# Print a progress summary to the terminal
python -m lptracker stats
```

Every writing command accepts `--dry-run`, which prints what would be
written without touching the sheet (and needs no Google credentials):

```bash
python -m lptracker sync --dry-run
```

Note: `annotate --dry-run` reads no sheet data, so its row lookup always
reports "not found" — it is mainly useful for checking your arguments.

### Progress columns

| Column | Filled by |
| --- | --- |
| `#` (problem number) | sync |
| `Title` | sync |
| `Slug` | sync |
| `Difficulty` | sync |
| `Tags` | sync |
| `Date Solved` | sync |
| `Language` | sync |
| `Link` | sync |
| `Time (min)` | annotate |
| `Attempts` | annotate |
| `Confidence (1-5)` | annotate |
| `Needs Review` | annotate (from confidence) |
| `Next Review` | annotate (from confidence) |
| `Notes` | annotate |

## Notes and limitations

- LeetCode's public API only returns roughly the **20 most recent accepted
  submissions**, so run `sync` regularly to avoid gaps — e.g. daily via cron:

  ```
  0 21 * * * cd /path/to/leetcodeprogress && python -m lptracker sync
  ```

- `sync` dedupes by slug: a problem already in the sheet is never added
  twice, and re-solves within a batch keep the earliest solve date.
- Time, attempts, confidence and notes are manual by design — record them
  with `annotate` while the solve is fresh.
- Full-history backfill (importing solves older than the recent-submission
  window using a logged-in session cookie) is a planned future enhancement.
