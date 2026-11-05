# NHL Total Model

Projects NHL game totals, flags overs worth a look, and paper-trades them live.

**Live dashboard:** https://prezbo8.github.io/NHL-total-model/

## The rule

A game is **flagged** when:

1. the consensus line is **6 or 6.5** (never 5.5), and
2. **both teams** are projected at or above the **high-scoring cutoff** (top 40% of last season's team
   projections; about 3.09 goals in 2026-27).

Every game gets a call:

| Call | When | Bet |
|---|---|---|
| **SLAM** | flagged + both teams good or great at 5-on-5 | OVER, 1 unit |
| **1U** | flagged + one team great at 5-on-5 | OVER, 1 unit |
| **PASS** | other flagged games | no bet |
| **AVOID** | not flagged, or both teams face strong goalies | no bet |

Take it at the **best over** book shown on the dashboard. The paper-trading record uses closing
information only: the call at the last run before puck drop, graded at the closing consensus line.
`P(7+)` is the model's chance of 7+ total goals (wins an over 6.5 and an over 6; exactly 6 pushes an
over 6). It comes from the projected total and how evenly matched the teams are; calls don't use it.

## How the model works

Each team's goals are projected separately for:

- **5-on-5**: expected goals + actual goals for/against per 60 (team attack × opponent defense × 5v5 minutes)
- **Power play**: PP efficiency × opponent's penalty kill × power-play time (penalties drawn × penalties taken)
- **Other situations**: 4-on-4, 3-on-3 overtime, empty nets (league average)
- **Shorthanded goals + the shootout winner's goal**: 0.22 a game, league average (counted in betting totals)

then adjusted for:

- **Starting goalie**: goals saved above expected, calibrated so ratings match how goalies actually play
- **Back-to-backs**: tired team −8% scoring, its opponent +6.5%
- **Team skating speed** (NHL EDGE, last season's 20+ mph bursts): +2% own scoring and −1.7% to the opponent per step above average
- **Injuries and lineups**: injured, suspended or scratched regulars replaced by a replacement-level player (effect sized 1.15×, from the backtest on who dressed)
- **Eliminated teams** (from about March): a team already out of the playoffs allows ~4% more goals and scores 1% fewer

Only data from the 2020-21 season onward is used.

### Data sources

| What | Source |
|---|---|
| Game stats (xG, goals, ice time by situation) | MoneyPuck (downloaded once a day) |
| Goalie and skater stats | MoneyPuck, NHL stats API |
| Starting goalies | DailyFaceoff + Rotowire + GoaliePost, combined (Confirmed / Likely / Conflict); actual starters from the NHL box score |
| Injuries | ESPN + Rotowire |
| Projected lineups / scratches | DailyFaceoff line combinations vs the official NHL roster |
| Schedule, scores, rosters | NHL API |
| Team skating speed | NHL EDGE (NHL API) |
| Betting lines (open, current, 5 sportsbooks) | Action Network |

## Backtest (2021-26, 2020+ data only)

| | Bets | Win % | ROI |
|---|---|---|---|
| At the opening line | 580 | 53.7% | +2.6% |
| At the closing line | 840 | 55.1% | +3.0% |
| Line shopping (best book) | | | about +2 pts more |

The past edge is small (±3–4% uncertainty). The live paper-trading record decides whether it's real.
Injury and lineup adjustments were backtested on who actually dressed (2021-26, research/studies/injury_backtest.py): they make projections more accurate and are about the right size.

Every idea tested so far (adopted, kept or rejected, with the numbers) is listed in
[research/README.md](research/README.md). Check it before testing something new.

## Repo layout

```
.github/workflows/            daily.yml (hourly run) + moneypuck.yml (once-a-day MoneyPuck data) + keeper.yml (starts both on time)
                              + tests.yml (checks) + monthly.yml (check-up)
.github/scripts/              next_slot.py (the keeper's next slot) + summary.py (every run's last step: Summary)
src/                          everything the daily run uses
  model.py                      entry points: `today` projects, flags and logs (hourly); `stats` = the once-a-day run; also the original model
  split_model.py                the 5v5 / power-play model used daily
  goalies.py  players.py        goalie and skater data + ratings
  speed.py                      team skating speed (NHL EDGE)
  injuries.py  lineups.py       ESPN injuries, DailyFaceoff projected lineups vs NHL roster
  confirm.py                    starting goalies from DailyFaceoff + Rotowire + GoaliePost combined; Rotowire injuries; actual starters (NHL box score)
  odds.py  books.py  grade.py   betting lines (consensus, opening, every sportsbook) and line math
  paper.py                      paper-trading log: log, settle, report
  health.py                     retries every data source (not a 403), re-runs in 5 min if one still fails, GitHub issue alerts
  retune.py                     monthly check-up: tier cutoffs, call record, calibration, goalie predictions (GitHub issue)
  store.py                      Supabase: every run's projections (history) + the once-a-day results (replaced daily); skipped without the key
  rule_check.py                 one-time SLAM rule check at 75 settled picks (data/rule_check.json)
  trends.py                     last-10 and head-to-head context shown on the dashboard
  moves.py                      how each game's projection moved during the day, and why (data/moves/)
  dashboard.py                  builds the website in docs/ (slate, record, accuracy + P(7+) chart, rankings)
  backfill.py                   adds a past day from pre-game data only (marked retroactive)
  teams.py  paths.py            team names, file locations
research/                     backtests, not part of the daily run (index: research/README.md)
  lib/                          shared helpers: history.py (overs rule on every season), sbr.py (2007-22 odds), lineups_hist.py
  studies/                      one script per tested idea
data/                         CSV data
  paper_trades.csv              the paper-trading log (every logged game, picks, results)
  goalie_*.csv  skater_seasons.csv  opening_lineups.csv  team_speed.csv
  team_rankings*.csv            rankings tab (current + as of each game day)
  odds_*.csv  sbr_odds.csv      historical lines
  game_starts.csv  referees.csv research inputs (start times, referees)
  monthly/                      monthly check-up reports
  stats_status.json             outcome of the once-a-day run (dashboard header + hourly "Daily stats" alert)
  key_players/  moves/          per-day key players and projection-move snapshots (dashboard)
docs/                         the website (GitHub Pages)
supabase/schema.sql           Supabase tables (nhl_*): run history + once-a-day results; paste once into the SQL Editor
tests/check_model.py          91 component checks (paper log, settling, goalies, model, injuries, odds, dashboard, projection moves, daily stats, run summaries, game notes)
```

## Schedule: two kinds of runs

Everything runs on GitHub Actions; nothing runs on a local machine. The dashboard's top-right corner shows
both: **MoneyPuck data** (the once-a-day run, with the newest game in the data) and **Odds, lineups &
projections** (the hourly run), each with ✓ or ⚠.

- **Hourly: odds, lineups & projections** (`.github/workflows/daily.yml`): **12:01 AM and every hour from
  11:17 AM to 10:17 PM Eastern, plus 15 minutes before each game** (a pre-game slot within 5 minutes of a
  :17 run is covered by it), all year, daylight saving handled. Settles finished games, re-checks
  starting goalies, lineups, injuries and lines, re-projects every game that hasn't started, logs, rebuilds
  the dashboard and commits everything back. It never downloads from MoneyPuck: it uses the saved copy and
  the files the once-a-day run commits, and only asks MoneyPuck whether it has newer data (one request).
- **Once a day: MoneyPuck data** (`.github/workflows/moneypuck.yml`, `python3 src/model.py stats`):
  **8:00 AM Eastern**, then every 10 minutes until MoneyPuck's data includes last night's games (MoneyPuck posts
  around 7:30 AM), up to 11:10 AM so the 11:17 AM run has them; and again whenever an hourly run sees MoneyPuck
  has newer data. Downloads MoneyPuck's game file (up to 5 hours if MoneyPuck is slow; kept
  in GitHub's Actions cache), refreshes goalie history, skater stats and team speed, commits them with
  `data/stats_status.json`, and **replaces** the Supabase daily tables (`nhl_daily_teams`, `_goalies`,
  `_skaters`, `_meta`). (Nov 3, 2026: MoneyPuck served ~30 KB/s and every run that downloaded it timed out.)
  When it brings in new data it **starts a model run right away**, so the dashboard and projections use the
  new data within minutes instead of at the next hourly run (that model run never starts a stats run back).
- **Game notes, written by AI** (`src/notes.py`, Google Gemini's free tier, GitHub secret `GEMINI_API_KEY`): each of
  today's games gets a paragraph (about 150-230 words) written before it starts from the model's and the dashboard's
  numbers for both teams: record and last-10 record, the projection (each team, the total vs the line, the chance of
  7+), 5-on-5 and power play (rating, projected goals, attack rank vs the opposing defense's), the goalie each faces
  (tag, grade, his season and last-5 numbers), the Team rankings (total offense / defense, the nine stats) and Form over
  the season and the last 30 / 14 / 7 days, and the model's call and reasons. Each note opens on a different angle, so
  they don't all read alike. Today's slate only: the Tomorrow preview tab, finished games and past days show the fixed
  template. A check rejects any note that leaves out a team's record, last-10 record or projected goals or the total,
  uses a number not in the facts, names a different call, says "cutoff" or copies the topic it was given to open on,
  and a note is rewritten only when its game's facts change. Numbers are colored as the dashboard colors them
  (breakdown tiers, matchup ranks, Form numbers; last 10 records and streaks hot / cold). Without the key, or when
  Gemini fails, the fixed template shows, as before.
- **Every run ends with a Summary step**: what the job is for, what it did (✓ done, ✗ failed, – nothing
  to do) and the final result. It's the last step in the log and is also shown on the run's page on the
  Actions tab (under the job diagram). Steps add their lines with `health.note()` (Python) or `echo ... >> "$RUN_SUMMARY"`;
  `.github/scripts/summary.py` prints them.
- `.github/workflows/keeper.yml` stays running on GitHub and starts both on time. GitHub stops any run
  after 6 hours, so the keeper starts a fresh copy of itself every 5.5 hours; only one keeper runs at a time.
  (GitHub's own scheduler was too unreliable for this repo: on Oct 2, 2026 seven slots in a row never
  fired.) The hourly run's own :17 schedule stays as a fallback.
- **Alerts** (GitHub issues, which email you, and close themselves on recovery): a data source failing 2
  runs in a row; "Daily stats" when the once-a-day run failed or hasn't worked for 30 hours; "Model runs
  failing" when a run fails and none has finished for 2 hours. A source failing re-runs the hourly job
  every 5 minutes, only between 11 AM and 11 PM Eastern; a site answering 403 (refusing us) isn't retried within a run.

Run it now: **Actions** tab → **Daily NHL run** (or **Daily stats (once a day)**) → **Run workflow**
(`gh workflow run daily.yml` / `gh workflow run moneypuck.yml`). If the keeper ever stops (no "Keeper"
run in progress on the Actions tab), restart it with **Keeper** → **Run workflow** (`gh workflow run keeper.yml`).

## Checks and commands

Checks run on GitHub, not on a local machine: every push runs the **Tests** workflow (pyflakes, a syntax
check of every workflow's shell scripts, the 91 component checks, a projection run for tomorrow, a dashboard
build, and a check that the backtest is unchanged). Change code on a branch, open a pull request, and merge once Tests pass.

What the workflows run:

```
pip install pandas==3.0.6 numpy==2.5.3   # Python 3.14
python3 src/model.py stats                # once a day: MoneyPuck, goalie history, skater stats, speed, Supabase daily tables
python3 src/model.py today [YYYY-MM-DD]   # hourly: projections + flags (only today's date is logged)
python3 src/paper.py report               # paper-trading record
python3 src/dashboard.py                  # rebuild the website
python3 tests/check_model.py              # 91 component checks (Tests workflow)
python3 research/lib/history.py           # backtest the overs rule
python3 research/studies/<name>.py        # any study (see research/README.md)
```

MoneyPuck's game file (~127 MB) isn't stored in the repo: the once-a-day run keeps it in GitHub's Actions cache.

*Paper trading only, not betting advice.*
