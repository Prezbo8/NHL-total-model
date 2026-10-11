# Research

Backtests and one-off studies. None of this runs in the daily job, but `lib/` is imported by the daily run
(`src/rule_check.py`) and the Tests workflow, so keep its function names stable.

```
research/
  lib/        shared helpers
  studies/    one question per script: what was tested, and what the model did about it
```

Run any script from the repo root (or anywhere): `python3 research/studies/<name>.py`.
Every study uses 2020-21+ data only and judges changes on **both** opening and closing lines and in
**both halves** (2021-23 and 2023-26). A change that wins only one of those is treated as luck.

## lib/

| File | What it does |
|---|---|
| `history.py` | The overs rule on every season with odds: `flagged()`, `lines()`, `bet_results()`. Used by the Tests workflow's "backtest unchanged" check and the 75-pick SLAM rule check. |
| `sbr.py` | 2007-2022 odds archive (SportsBookReview), the lines before Action Network. |
| `lineups_hist.py` | Downloads who dressed in every game since 2020 into `data/dressed.csv` (~10 MB, gitignored). Needed by the injury studies. |

## studies/

**Adopted** = in the live model. **Kept** = current setting confirmed. **Rejected** = tested, made nothing better.

| Study | Question | Result |
|---|---|---|
| `close_p7_seasons.py` | Should P(7+) use closeness (\|home − away projection\|) as well as the projected total? | **Adopted Oct 8 2026.** Better every season since 2023-24 and better calibrated by closeness (evenly matched games get more OT, shootout and empty-net goals). Flags and calls unchanged. |
| `close_games.py` | Do evenly matched games go 7+ more often? | Yes, slightly: even games +0.09 vs projection, lopsided −0.06; led to the study above. No pattern in SLAM/1U. |
| `p7_calibration.py` | Is P(7+) calibrated? | Produces the backtest bins on the dashboard's calibration chart (`dashboard.CALIBRATION_BACKTEST`). Re-run after any P(7+) change. |
| `injury_backtest.py` | Is the injury/lineup adjustment the right size? | **Kept** (on who actually dressed, 2021-26). |
| `injury_scale.py` | 1.0× vs 1.15× vs 1.3× injury strength | Effect measures ~1.2× every season; the range includes 1.0 and bets barely move. |
| `injury_115.py` | 1.0× vs 1.15×, projection accuracy first | **Adopted Oct 10 2026 (`injuries.SCALE = 1.15`).** Better team-goal accuracy in all 5 seasons and in 4 of 5 for big-injury games; P(7+) slightly better; SLAM+1U +1.2u at close. |
| `goalie_retune.py` | Goalie shrink / carry-over / re-centering | **Kept** shrink 200, decay 0.7, no re-centering. Shrink 150 slightly better on bets: recheck after the season. |
| `b2b_retune.py` | Back-to-back factors with 2025-26 | **Kept** −8% tired / +6.5% opponent (measured −8.7% / +6.9%). |
| `stakes.py` | Should SLAM and 1U be staked differently? | **Kept** 1 unit each. 1U has done better than SLAM, but not reliably (ahead in only ~70% of resamples). Don't size SLAMs up. |
| `compare.py` | Model versions vs closing / opening lines | The 5v5 / power-play split model won; score-venue xG, recency weighting and player-based starts didn't. |
| `offense_weights.py` | How to weight the 9 stats in the rankings tab | Sets `split_model.WEIGHTS` (predictive r² of each stat). |
| `grade_test.py` | Rankings: does "Model" or "Total" predict future goals better? | Model (0.646 vs 0.587); Total kept as the default view anyway. |
| `home_ice.py` | League-wide home-ice factor | **Rejected.** Slightly better goal accuracy, SLAM+1U at close +45u → +9u. Team home/road splits don't repeat either. |
| `rolling_cutoff.py` | High-scoring cutoff from this season instead of last | **Rejected.** ~35% fewer bets, SLAM+1U at close +45u → +31u. |
| `goalie_blend.py` | Blend possible starters when the goalie isn't confirmed | **Rejected.** SLAM+1U at close +45u → +24u. The last pre-game run had the right goalie 94/94 times. |
| `pace.py` | Do high-pace (shot attempts) games go 7+ more often? | **Rejected** for P(7+). But fast-pace SLAM/1U were the weakest group (+3.1% vs +11-14%): **recheck at 100 settled picks.** |
| `fatigue.py` | Rest days, 3-in-4, travel, time zones, road trips | **Rejected** beyond back-to-backs. |
| `refs.py` | Referees | **Rejected:** they change penalties, not goals. |
| `month_effect.py` | Does scoring vs projection follow the calendar? | **Rejected.** No month repeats across seasons; adjustment changed nothing. |
| `afternoon.py` | Do matinee games score less? | **Rejected.** Afternoon games +0.15 vs evening (noise, flips by season). Start times cached in `data/game_starts.csv`. |
| `goalie_b2b.py` | Starter playing both nights of a back-to-back | **Rejected.** Only 281 times in 2021-26; opponent +1% vs projection. |
| `altitude.py` | Denver / Salt Lake | **Rejected.** Totals there come in exactly as projected. |
| `combo_search.py` | Which 1-3 signal combos find the most 7+ games (searched 2020-23, checked 2023-26)? | Best: flagged + a great 5v5 team + P(7+) 50%+ (55% / 63% went 7+). Current SLAM+1U is close (53% / 62%). Back-to-back and weak-goalie combos don't hold up. |
| `rating_shrink.py` | Pull team ratings toward average (K, REGRESS) to fix weak-vs-weak / strong-vs-strong misses | **Kept** K=15, REGRESS=0.33: accuracy unchanged at every setting and the extreme misses don't shrink. |
| `matchup_damp.py` | Dampen the attack × defense matchup math (exponent < 1) | **Rejected.** Team-goal and P(7+) accuracy get worse the more it's dampened; fewer bets, fewer units. The extreme-group misses are mostly regression to the mean from picking games by their projection. |
| `zone_time.py` | Offensive / defensive zone time (NHL EDGE, last season) | **Rejected.** No gain in team-goal or P(7+) accuracy; xG already covers it. Data cached in `data/team_zone_time.csv`. |

Also tested before these scripts existed, all rejected: player-based starting ratings, recent trends and
head-to-head, player speed, shorthanded goals as a team skill, team-specific "other situations" goals,
save % instead of GSAx, betting the day's top P(7+) or unflagged high-P(7+) games, higher projection cutoffs.

## Open checkpoints

- **75 settled picks:** `src/rule_check.py` runs the SLAM rule check by itself (current rule vs combined 5v5 > 4.20).
- **100 settled picks:** live SLAM/1U by pace third (`pace.py`).
- **End of season:** recheck goalie shrink 150 (K / REGRESS tested Oct 10 2026: keep).
