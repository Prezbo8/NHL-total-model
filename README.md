# NHL Total Model

**Live dashboard:** https://prezbo8.github.io/nhl-total-model/

## Daily (automatic, on GitHub Actions — nothing runs on a local machine)
`.github/workflows/daily.yml` runs every 2 hours from 11 AM to 9 PM Eastern, all year (daylight saving handled):
settles yesterday's paper trades, projects today's games, logs them, rebuilds the dashboard, commits back to the repo.
Run it now: Actions tab -> "Daily NHL run" -> Run workflow (or `gh workflow run daily.yml`). Run logs show the full output.

## Commands
    cd ~/nhl-totals-model
    python3 paper.py report           # paper trading record
    python3 model.py today [DATE]     # projections + OVER flags + best book (logs only for today's date)

## The rule (frozen)
OVER only, consensus line 6 or 6.5 (never 5.5), BOTH teams projected 2.95+ goals
(top 40% of last season's team projections). Bet it at the "best over" book.
P(7+) = model's chance the game has 7+ total goals (wins over 6.5 and over 6; 6 goals pushes an over 6).

## Model
5v5 / power-play split (split_model.py), 2020-21 onward data only (FIRST_SEASON = 2020):
team xG + goals, PP/PK + penalties drawn/taken, starting goalie GSAx, back-to-backs.
Player ratings built (players.py) but OFF (roster_w = 0) — didn't help the rule.

## Backtest (2021-26, 2020+ data, calibrated goalies)
+0.5% ROI at open (620 bets), +2.3% at close (903 bets), 53-55% wins; line shopping ~+2 pts more.
Small and unproven: the live paper-trading record decides.

## Watch
Oct 3: MTL @ PIT flagged (over, best book BetMGM o6 -105 at 2:40 AM) — first paper trade if still
flagged at the 11 AM run (depends on Dobes / Silovs starting).

## Setup on a new machine
    pip install pandas==2.2.3 numpy==2.2.6
    python3 model.py today        # first run downloads MoneyPuck game data (~126 MB, not in the repo)
Scheduled job: GitHub Actions (.github/workflows/daily.yml).

## Files
model.py (daily command, original model, backtest) · split_model.py (5v5/PP model used daily) ·
goalies.py · players.py · paper.py (paper trading log) · odds.py / books.py / sbr.py (line data) ·
grade.py / compare.py / history.py (tests vs real lines) · dashboard.py (builds docs/index.html) · *.csv (downloaded data + paper_trades.csv)
