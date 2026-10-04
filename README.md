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
- **Team skating speed** (NHL EDGE, last season's 20+ mph bursts): +2% own scoring and −1.7% to the opponent per step above average
- **Injuries and lineups**: injured, suspended or scratched regulars replaced by a replacement-level player

Only data from the 2020-21 season onward is used.

### Data sources

| What | Source |
|---|---|
| Game stats (xG, goals, ice time by situation) | MoneyPuck |
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
| At the opening line | 585 | 53.0% | +1.3% |
| At the closing line | 840 | 54.7% | +2.4% |
| Line shopping (best book) | | | about +2 pts more |

The past edge is small (±3–4% uncertainty). The live paper-trading record decides whether it's real.
Injury and lineup adjustments are not backtested (no free history of nightly lineups).

## Repo layout

```
.github/workflows/            daily.yml (the run) + keeper.yml (starts it on time) + tests.yml (checks)
src/                          everything the daily run uses
  model.py                      daily entry point: `today` projects, flags and logs; also the original model
  split_model.py                the 5v5 / power-play model used daily
  goalies.py  players.py        goalie and skater data + ratings
  speed.py                      team skating speed (NHL EDGE)
  injuries.py  lineups.py       ESPN injuries, DailyFaceoff projected lineups vs NHL roster
  confirm.py                    starting goalies from DailyFaceoff + Rotowire + GoaliePost combined; Rotowire injuries; actual starters (NHL box score)
  odds.py  books.py  grade.py   betting lines (consensus, opening, every sportsbook) and line math
  paper.py                      paper-trading log: log, settle, report
  store.py                      run history in Supabase (every run's projections; skipped without the key)
  dashboard.py                  builds the website in docs/
  backfill.py                   adds a past day from pre-game data only (marked retroactive)
  teams.py  paths.py            team names, file locations
research/                     backtests (not part of the daily run)
  history.py                    the overs rule on every season with odds
  compare.py                    model versions vs closing / opening lines
  sbr.py                        2007-2022 odds archive
data/                         CSV data
  paper_trades.csv              the paper-trading log (every logged game, picks, results)
  goalie_*.csv  skater_seasons.csv  opening_lineups.csv  team_speed.csv
  odds_*.csv  sbr_odds.csv      historical lines
docs/                         the website (GitHub Pages)
supabase/schema.sql           Supabase tables (nhl_*) for the run history: paste once into the SQL Editor
tests/check_model.py          44 component checks (paper log, settling, goalies, model, injuries, odds, dashboard)
```

## Schedule

Runs **every hour from 11:17 AM to 10:17 PM Eastern, plus 15 minutes before each game**, all year (daylight saving handled). The time of the last run is shown in the top-right corner of the dashboard.

- `.github/workflows/keeper.yml` stays running on GitHub and starts **Daily NHL run** at each slot.
  GitHub stops any run after 6 hours, so the keeper starts a fresh copy of itself every 5.5 hours;
  only one keeper runs at a time. (GitHub's own scheduler was too unreliable for this repo: on
  Oct 2, 2026 seven slots in a row never fired.)
- `.github/workflows/daily.yml` does the work: settles yesterday's games, re-downloads stats,
  goalies, injuries, lineups and lines, projects today's games, logs them, rebuilds the dashboard
  and commits everything back. Its own hourly :17 schedule stays as a fallback.
- Nothing runs on a local machine.

Run it now: **Actions** tab → **Daily NHL run** → **Run workflow** (or `gh workflow run daily.yml`).
If the keeper ever stops (no "Keeper" run in progress on the Actions tab), restart it with
**Keeper** → **Run workflow** (or `gh workflow run keeper.yml`).

## Running locally

```
pip install pandas==3.0.6 numpy==2.5.3   # Python 3.14
python3 src/model.py today [YYYY-MM-DD]   # projections + flags (only today's date is logged)
python3 src/paper.py report               # paper-trading record
python3 src/dashboard.py                  # rebuild the website
python3 research/history.py               # backtest the overs rule
python3 tests/check_model.py              # 44 component checks (also run on GitHub: Tests workflow)
```

The first run downloads MoneyPuck's game file (~126 MB, not stored in the repo).

*Paper trading only, not betting advice.*
