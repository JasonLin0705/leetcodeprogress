# LeetCode Progress Tracker

Turn your LeetCode grind into a living Google Sheet: every solve synced
automatically, organized by topic, scheduled for spaced-repetition review, and
paired with suggestions for what to practice next.

It runs as a small Python CLI (`lptracker`) that reads from LeetCode's API and
writes to a Google Sheet you own.

- [Features](#features)
- [Requirements](#requirements)
- [Setup](#setup)
- [Commands](#commands)
- [Backfilling your full history](#backfilling-your-full-history)
- [Automating a daily sync](#automating-a-daily-sync)
- [What the sheet looks like](#what-the-sheet-looks-like)
- [Limitations](#limitations)
- [Development](#development)
- [Security](#security)

## Features

- **Auto-sync from LeetCode** — pulls your recent accepted submissions
  (title, difficulty, tags, language, solve date, link) from LeetCode's public
  API. No login required for day-to-day syncing.
- **Full-history backfill** — import *every* problem you've ever solved, not
  just the recent window (see [Backfilling](#backfilling-your-full-history)).
- **Google Sheets as the database** — one row per problem, readable and
  editable anywhere, on any device.
- **Organized by topic and date** — the Progress tab is grouped by topic, plus
  a **By Topic** tab (solves under each tag) and a **By Date** tab (a solve
  timeline, newest first).
- **Spaced repetition** — rate each solve 1–5 with `annotate`; low confidence
  schedules a `Next Review` date (1 → tomorrow, 2 → 3 days, 3 → 1 week,
  4 → 2 weeks, 5 → no review). Confidence 5 also ticks `Mastered`. See what's
  due with `review`.
- **Topic-based suggestions** — a **Suggestions** tab recommends unsolved
  problems across *every* topic, weakest topics first, pulled live from LeetCode.
- **Google interview prep** — a **Google Prep** tab lists the unsolved problems
  most frequently asked at Google (from a bundled company-tag dataset), ranked
  by frequency. No LeetCode Premium required.
- **Readable sheet** — `Mastered` / `Needs Review` are checkboxes, `Link` is a
  compact ↗ hyperlink, and difficulty is color-coded.
- **Stats tab** — totals, difficulty and topic breakdowns, solves per week,
  and your current daily streak, recomputed on every sync.

## Requirements

- **Python 3.10+**
- A **Google account** (to hold the sheet) and a free **Google Cloud** project
  (for the service-account credentials — one-time setup below).
- A **LeetCode account** (only the public username is needed for syncing; a
  session cookie is optional and only used for full-history backfill).

## Setup

### 1. Install

```bash
git clone <this-repo> && cd leetcodeprogress
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # fill this in as you go
```

### 2. Create Google service-account credentials

The tracker writes to your sheet as a *service account* — a robot Google
identity with its own email address.

1. Open the [Google Cloud Console](https://console.cloud.google.com/) and
   create a new project (any name).
2. Enable the **Google Sheets API** *and* the **Google Drive API**
   (APIs & Services → Library).
3. Create a **service account** (APIs & Services → Credentials → Create
   Credentials → Service account). No roles are needed.
4. Open the service account → **Keys** → Add key → **JSON**. Save the
   downloaded file as `credentials.json` in the repo root. *(It is gitignored —
   never commit it.)*

### 3. Create and share the sheet

1. Create a new, blank Google Sheet in your own account.
2. Click **Share** and share it with the service account's email — the
   `client_email` value inside `credentials.json` — as **Editor**.
3. Copy the sheet ID from its URL:
   `https://docs.google.com/spreadsheets/d/`**`<SHEET_ID>`**`/edit`.

### 4. Fill in `.env`

```dotenv
LEETCODE_USERNAME=your_leetcode_username
GOOGLE_SHEET_ID=your_sheet_id
GOOGLE_CREDENTIALS_FILE=credentials.json
# Optional — only needed for `backfill` via cookie (see below). Keep it secret.
# LEETCODE_SESSION=your_leetcode_session_cookie
```

### 5. Initialize and do a first sync

```bash
python -m lptracker init    # creates the tabs, checkboxes, formatting
python -m lptracker sync    # pulls your recent solves
```

## Commands

Run everything as `python -m lptracker <command>`. Every writing command
accepts `--dry-run`, which prints what *would* be written without touching the
sheet (and needs no Google credentials).

| Command | What it does |
| --- | --- |
| `init` | Create the `Progress` / `Stats` tabs and apply formatting. Idempotent. |
| `sync` | Fetch recent accepted submissions, append new ones, and rebuild all derived tabs. |
| `backfill` | Import your entire solved history (see next section). |
| `annotate <slug\|#>` | Fill in the manual fields for a problem. |
| `review` | List problems whose review date has arrived (read-only). |
| `suggest` | Rebuild the Suggestions tab (every topic, weakest first). |
| `stats` | Print a progress summary to the terminal (read-only). |

```bash
# Sync (optionally limit how many recent submissions to fetch)
python -m lptracker sync
python -m lptracker sync --limit 15

# Annotate by slug or problem number
python -m lptracker annotate two-sum --time 25 --attempts 2 --confidence 3 \
    --notes "hash map; watch the duplicate-index case"
python -m lptracker annotate 146 --confidence 5     # confidence 5 => Mastered ✓

# Suggestions: --count weak topics, --per-tag problems each
python -m lptracker suggest --count 5 --per-tag 4

# What's due for review today
python -m lptracker review
```

## Backfilling your full history

LeetCode's public API only exposes your **~20 most recent** accepted
submissions. To import everything you've *ever* solved, `backfill` reads your
full solved list one of two ways:

### Option A — session cookie (fully automatic)

1. Log into LeetCode in your browser.
2. Copy your `LEETCODE_SESSION` cookie value (DevTools → Application → Cookies →
   `https://leetcode.com` → `LEETCODE_SESSION`).
3. Put it in `.env` as `LEETCODE_SESSION=...` **(this is a credential — keep it
   private, never commit it; it expires periodically and can be re-copied).**
4. Run:

   ```bash
   python -m lptracker backfill
   ```

### Option B — a slugs file (no cookie needed)

If you'd rather not store the cookie, generate a list of solved slugs yourself.
While logged into LeetCode, open the browser console and run:

```js
const d = await fetch('/api/problems/all/', {credentials:'include'}).then(r=>r.json());
copy(d.stat_status_pairs.filter(p=>p.status==='ac')
      .map(p=>p.stat.question__title_slug).join('\n'));
// the slug list is now on your clipboard — paste it into slugs.txt
```

Then:

```bash
python -m lptracker backfill --file slugs.txt
python -m lptracker backfill --file slugs.txt --limit 20   # trial run
```

`backfill` skips problems already in the sheet, fetches each new problem's
title/difficulty/tags, appends it, and rebuilds the derived tabs. Historical
solves have a **blank `Date Solved`** (LeetCode doesn't expose per-problem solve
dates), so they don't affect your streak or weekly counts — but they *do* count
toward totals, topic breakdowns, and suggestions.

## Automating a daily sync

Because `sync` only sees the recent window, running it regularly keeps you from
missing solves. A daily cron job (macOS/Linux):

```cron
0 21 * * * cd /path/to/leetcodeprogress && ./.venv/bin/python -m lptracker sync >> sync.log 2>&1
```

Cron won't wake a sleeping machine — on macOS, use a `launchd` LaunchAgent with
`StartCalendarInterval` if you want catch-up-after-wake behavior.

## What the sheet looks like

Six tabs, all rebuilt on every `sync` / `backfill`:

- **Progress** — one row per solved problem, grouped by topic. Columns:

  | Column | Filled by |
  | --- | --- |
  | `#`, `Title`, `Slug`, `Difficulty`, `Tags`, `Date Solved`, `Language`, `Link` | sync / backfill |
  | `Time (min)`, `Attempts`, `Confidence (1-5)`, `Notes` | annotate |
  | `Mastered` (checkbox) | annotate — auto-ticked at confidence 5 |
  | `Needs Review` (checkbox), `Next Review` | annotate — from confidence |

  `Link` is a compact ↗ hyperlink; difficulty is color-coded.
- **Stats** — totals, difficulty/topic breakdowns, solves per week, streak.
- **By Topic** — your solves grouped under each tag.
- **By Date** — a solve timeline, newest first; backfilled (undated) solves are
  grouped in a trailing "Undated" section.
- **Suggestions** — unsolved problems across every topic (weakest first), with
  acceptance rates.
- **Google Prep** — unsolved problems most frequently asked at Google, ranked
  by frequency.

### Google Prep data

The Google Prep tab is powered by a bundled snapshot of Google's company-tagged
problems (`lptracker/data/google_problems.csv`), derived from the public
[leetcode-company-wise-problems](https://github.com/liquidslr/leetcode-company-wise-problems)
dataset — so it works without LeetCode Premium. It's a frequency-ranked proxy
for Google's interview set, not live company data.

## Limitations

- `sync` sees only the ~20 most recent submissions; use `backfill` for history
  and run `sync` regularly.
- `Time`, `Attempts`, `Confidence`, and `Notes` are manual by design — LeetCode
  doesn't expose them. Record them with `annotate` while the solve is fresh.
- Backfilled problems have no solve date, so they don't contribute to streaks or
  per-week stats.
- `annotate --dry-run` reads no sheet data, so its row lookup always reports
  "not found" — it's mainly for checking your arguments.

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest -q
```

The code is organized as: `leetcode.py` (API client), `sheets.py` (Google
Sheets I/O), `models.py` (the `Solve` row model), `stats.py`, `review.py`,
`suggest.py`, and `cli.py` (command wiring). Tests run fully offline — no
network and no Google access required.

## Security

`credentials.json`, `.env`, and any slugs/cookie files are **gitignored** —
keep them that way. Your `LEETCODE_SESSION` cookie and service-account key are
secrets; never commit or share them. The service account only has access to the
one sheet you explicitly shared with it.
