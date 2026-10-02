# NHL Total Model

Projects NHL game totals, flags overs worth a look, and paper-trades them live.

**Live dashboard:** https://prezbo8.github.io/nhl-total-model/

## The rule

Bet the **OVER** only when:

1. the consensus line is **6 or 6.5** (never 5.5), and
2. **both teams** are projected **2.95+ goals** (top 40% of last season's team projections).

Take it at the **best over** book shown on the dashboard. These are the only picks that count in
the paper-trading record. `P(7+)` is the model's chance of 7+ total goals (wins an over 6.5 and an
over 6; exactly 6 pushes an over 6).

## How the model works

Each team's goals are projected separately for:

- **5-on-5**: expected goals + actual goals for/against per 60 (team attack × opponent defense × 5v5 minutes)
- **Power play**: PP efficiency × opponent's penalty kill × power-play time (penalties drawn × penalties taken)
- **Other situations**: 4-on-4, 3-on-3 overtime, empty nets (league average)

then adjusted for:

- **Starting goalie**: goals saved above expected, calibrated so ratings match how goalies actually play
- **Back-to-backs**: tired team −8% scoring, its opponent +6.5%
- **Injuries and lineups**: injured, suspended or scratched regulars replaced by a replacement-level player

Only data from the 2020-21 season onward is used.

### Data sources

| What | Source |
|---|---|
| Game stats (xG, goals, ice time by situation) | MoneyPuck |
| Goalie and skater stats | MoneyPuck, NHL stats API |
| Starting goalies | DailyFaceoff (matched actual starters 32/32 to start 2026-27) |
| Injuries | ESPN |
| Projected lineups / scratches | DailyFaceoff line combinations vs the official NHL roster |
| Schedule, scores, rosters | NHL API |
| Betting lines (open, current, 5 sportsbooks) | Action Network |

## Backtest (2021-26, 2020+ data only)

| | Bets | Win % | ROI |
|---|---|---|---|
| At the opening line | 620 | 52.6% | +0.5% |
| At the closing line | 903 | 54.7% | +2.3% |
| Line shopping (best book) | | | about +2 pts more |

The past edge is small (±3–4% uncertainty). The live paper-trading record decides whether it's real.
Injury and lineup adjustments are not backtested (no free history of nightly lineups).

## Repo layout

```
.github/workflows/daily.yml   scheduled run on GitHub Actions
src/                          everything the daily run uses
  model.py                      daily entry point: `today` projects, flags and logs; also the original model
  split_model.py                the 5v5 / power-play model used daily
  goalies.py  players.py        goalie and skater data + ratings
  injuries.py  lineups.py       ESPN injuries, DailyFaceoff projected lineups vs NHL roster
  odds.py  books.py  grade.py   betting lines (consensus, opening, every sportsbook) and line math
  paper.py                      paper-trading log: log, settle, report
  dashboard.py                  builds the website in docs/
  backfill.py                   adds a past day from pre-game data only (marked retroactive)
  teams.py  paths.py            team names, file locations
research/                     backtests (not part of the daily run)
  history.py                    the overs rule on every season with odds
  compare.py                    model versions vs closing / opening lines
  sbr.py                        2007-2022 odds archive
data/                         CSV data
  paper_trades.csv              the paper-trading log (every logged game, picks, results)
  goalie_*.csv  skater_seasons.csv  opening_lineups.csv
  odds_*.csv  sbr_odds.csv      historical lines
docs/                         the website (GitHub Pages)
```

## Schedule

`.github/workflows/daily.yml` runs every 2 hours from **11 AM to 9 PM Eastern**, all year, at :17
past the hour with a :47 backup (GitHub delays or drops on-the-hour runs). Each run settles
yesterday's games, re-downloads stats, goalies, injuries, lineups and lines, projects today's games,
logs them, rebuilds the dashboard and commits everything back. Nothing runs on a local machine.

Run it now: **Actions** tab → **Daily NHL run** → **Run workflow** (or `gh workflow run daily.yml`).

## Running locally

```
pip install pandas==2.2.3 numpy==2.2.6
python3 src/model.py today [YYYY-MM-DD]   # projections + flags (only today's date is logged)
python3 src/paper.py report               # paper-trading record
python3 src/dashboard.py                  # rebuild the website
python3 research/history.py               # backtest the overs rule
```

The first run downloads MoneyPuck's game file (~126 MB, not stored in the repo).

*Paper trading only, not betting advice.*
