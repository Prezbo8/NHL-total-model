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
| `injury_off_def.py` | Injury adjustment split: offense side vs defense side, each on its own | **Kept both.** Offense slope 1.19 ± 0.32 (>1 every season) carries the accuracy gain; defense 1.47 ± 0.77 but swings by season (0.5-2.6) and alone is no better than nothing; both together slightly best in 2024-26. Dashboard flags defender 'If out' as a rough guide (Oct 13 2026). |
| `injury_baseline.py` | Who replaces a missing player: call-up (live 0.90/1.10) vs a 2nd/3rd-line player (average 1.00/1.00) vs in between / worse | **Kept call-up.** Best or tied on accuracy (team dev 2024-26 1.0739, LL close 0.6956), size 1.07; average baseline worst (21-26 dev 1.0689, size 0.89) because it makes benching a below-average player a boost. All variants within 0.0006 (Oct 13 2026). |
| `injury_top5.py` | How the model did when a top-5 attacker / defender (Key players ranking) was out, with vs without the injury adjustment | **Adjustment helps but is about half the needed size for top players.** Backtest 2021-26 (who dressed): top-5 attacker out -> team goals miss -0.126 -> -0.069 (no-absence teams ~0), deviance 1.0396 -> 1.0349; 2+ out -0.195 -> -0.078; top-5 defender out -> opponent +0.015 -> -0.004 vs -0.04 for teams with none out; same in both halves. Live Oct 3-15 (77 / 64 team-games): attacker out miss -0.040 -> +0.005; defender out, opponents +0.24 over projection, adjustment +0.01. Follow-up tested in `injury_top5_size.py` (rejected) (Oct 16 2026). |
| `injury_top5_size.py` | Bigger injury size for top-5 players only (attackers / defenders x1.15-3.0, others stay 1.15) | **Rejected, live 1.15x kept.** Picked on 2021-23: attackers x2.5 -> worse on 2023-26 (team-goal deviance 1.0804 -> 1.0818, overshoots: top-5-out teams then score +0.06 over projection). x1.3-1.5 ties 2023-26 (1.08036 / 1.08042) because recent seasons want less: 2023-24 prefers bigger, 2024-26 prefers live. Defenders: right-sized in 2023-26 (the gap in injury_top5 comes from 2021-23); bigger makes it worse. Log loss vs close / open moves <= 0.0002 (Oct 16 2026). |
| `proj_vs_p7_thresholds.py` | Pick high-scoring games by projected total (>= 6.5 .. 7.0) or by P(7+) (>= 47% .. 51%)? | **Projection wins out of sample** (P(7+) fit 2021-23, judged 2023-26): proj >= 6.7 went 7+ 55.4% (184 games) vs P(7+) >= 50% 46.6%; top 100/200/400 by projection 55/55/51% vs by P(7+) 43/48/47%. No threshold beats the closing line alone (best -1.0%). Model unchanged (Oct 13 2026). |
| `recent_form.py` | Recent form like the MLB model: last 30 / 14 / 7 days vs the model, in goals and xG | **Not added to the projection.** Goal form makes accuracy worse (carry-over ~0); xG form carries over ~6-9% in both halves, last-7-days xG improves team-goal deviance 1.0818 -> 1.0805; all windows together no gain. Shown as context: rankings tab 'Form' view (trends.team_form). Possible follow-up: recency weighting inside the ratings (Oct 13 2026). |
| `recency_ratings.py` | Recency weighting inside the live 5v5 / power-play ratings (older games faded 0.995-0.95 per game) | **Rejected.** Slightly better 2021-23 (team-goal deviance 1.0515 -> 1.0496) but worse 2023-26 at every setting (1.0818 -> 1.0819-1.0857), no gain vs closing / opening lines, closing-line bets +2.4% -> -0.3% to +2.3% (Oct 15 2026). |
| `faceoffs.py` | Faceoff % (overall, and offensive-zone draws vs the opponent's defensive zone), NHL stats API per game (`research/lib/faceoffs_hist.py` -> `data/faceoffs.csv`, sorted download: unsorted pages repeat rows) | **Rejected.** Faceoff skill is real (team first-half vs second-half r = 0.68) but doesn't make totals more accurate: overall % is zero-sum and its effect flips sign (2021-23 +0.08, 2023-26 -0.20; team-goal deviance 1.0818 -> 1.0819-1.0820); offensive-zone draws point the wrong way in both halves and are tiny (~0.2% of goals across the real team spread), log loss vs close 0.6963 -> 0.6962; both together: signs flip between halves. Each team's own goals 2023-26 (MAE 1.3792 / RMSE 1.7153 / Poisson LL 1.9313): no variant better, all equal or slightly worse. Bet changes (close +2.4% -> +1.3% to +3.0%) are noise around the cutoff (Oct 16 2026). |
| `hits.py` | Hits (both teams' hits in a team's games, MoneyPuck; all games and road-only to remove rink scorer bias) | **Rejected.** A real team trait (first half vs second half r = 0.71, road-only 0.56) and physical games scored ~5% under projection per 10 extra hits in 2021-23, but the effect faded to ~0-1.5% in 2023-26: fitted on 2021-23 it makes 2023-26 worse for each team's goals (MAE 1.3792 -> 1.3809-1.3815) and game totals (team-goal deviance 1.0818 -> 1.0824-1.0832, log loss vs closing / opening no better). Bet ROI swings (close +1.9% to +4.1%) are noise around the cutoff (Oct 16 2026). |
| `player_weights.py` | Player ratings behind injuries: season weights (1.0/0.7/0.4), stat mix (50/50), shrink (400 min) | **Kept.** Every variant within 0.0002 on accuracy; with the current ratings the 1.15× injury adjustment measures 1.04 (right size). |
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
| `score_adj_xg.py` | Score-and-venue-adjusted / flurry-adjusted MoneyPuck xG in the 5v5 / power-play ratings instead of raw xG (goalie GSAx kept on raw xG), as published and rescaled to raw xG's league total | **Rejected.** No real accuracy gain: team-goal deviance 2021-23 1.0515 -> 1.0486-1.0514, 2023-26 1.0818 -> 1.0816-1.0833 (flurry versions worse there), log loss vs close 0.6963 -> 0.6962-0.6963 and open 0.6866 -> 0.6865-0.6867. Flag-rule bets at close +2.4% -> +1.2% to +3.2%, mostly fewer bets (noise around the cutoff) (Oct 16 2026). |
| `pp_injuries.py` | Power-play / penalty-kill-specific injuries: share of last season's 5on4 / 4on5 time missing (who dressed, `data/skater_special_teams.csv` from MoneyPuck season summaries) on top of the live 1.15x adjustment | **Rejected.** Teams missing PP time don't score below the live injury-adjusted projection: 2023-26 residual none +0.03 / 0-15% +0.07 / 15-40% -0.04 / 40%+ -0.02 (no slope); 2021-23 the 'none' bucket is the worst (-0.16). Fitted on 2021-23 (b = 0.04 per share of PP time) it makes 2023-26 worse (team-goal deviance 1.0777 -> 1.0786; PP-only 1.0792); PK side ~0 (1.0777). The live all-situations adjustment already covers PP players (Oct 16 2026). |
| `pp_shrink.py` | Separate K / REGRESS for the power-play and penalty-kill ratings only (`split_model.walk_split` pp_k / pp_regress; was 15 / 0.33 like 5v5) | **Adopted Oct 16 2026: PP/PK K = 25 (`model.K_PP`), REGRESS 0.33.** Better in every accuracy split: team-goal deviance 2021-23 1.05152 -> 1.05086, 2023-26 1.08183 -> 1.08161, first 20 games 2021-23 1.04728 -> 1.04714, 2023-26 1.09365 -> 1.09222; log loss vs close 0.6963 -> 0.6961, open 0.6866 -> 0.6865. SLAM+1U open +24.3u -> +27.6u, close +45.0u -> +44.2u. K 40-60 best on 2021-23 but slip on 2023-26; higher REGRESS worse on 2021-23 (Oct 16 2026). |
| `early_handoff.py` | Faster early-season handoff from last season's ratings: 5v5 / penalties K 5-12 (live 15) and summer pull 0.45-0.60 (live 0.33), PP / PK held at live | **Rejected.** Lower K is worse everywhere (first 20 games 2021-23 1.04728 -> 1.0488-1.0630, rest of season worse too) and early SLAM+1U doesn't improve (first 150 league games 15-24 live vs 14-26 to 33-39). A stronger pull at K 15 helps the first 20 games a little (2023-26 1.09365 -> 1.09238) but hurts the rest of the season (1.07786 -> 1.07819) and SLAM+1U (+45.0u -> +42.0u). The weak early record isn't from carry-over being too strong (Oct 16 2026). |
| `other_goals.py` | The flat 'other' part (4v4, 3-on-3 OT, empty nets, shorthanded, shootout winner) by game type: depends on the projected gap, and the favourite's share | **Not adopted (accuracy +, bets -).** Lopsided games really get fewer of these goals (top gap fifth 0.86-0.88 vs ~1.0 a game, both halves) and favourites more. Gap-dependent part (0.994 - 0.095 x gap, fit 2021-23): team-goal deviance 2021-23 1.05152 -> 1.05086, 2023-26 1.08183 -> 1.08151, but SLAM+1U open +24.3u -> +11.7u, close +45.0u -> +34.7u (~35 fewer bets as the cutoff moves). Favourite share fitted on 2021-23 (s = 1.0) makes 2023-26 worse (1.0826). Live part runs 0.055 a game above actual, but a lower flat level is worse on 2023-26 (Oct 16 2026). |

Also tested before these scripts existed, all rejected: player-based starting ratings, recent trends and
head-to-head, player speed, shorthanded goals as a team skill, team-specific "other situations" goals,
save % instead of GSAx, betting the day's top P(7+) or unflagged high-P(7+) games, higher projection cutoffs.

## Open checkpoints

- **75 settled picks:** `src/rule_check.py` runs the SLAM rule check by itself (current rule vs combined 5v5 > 4.20).
- **100 settled picks:** live SLAM/1U by pace third (`pace.py`).
- **End of season:** recheck goalie shrink 150 (K / REGRESS tested Oct 10 2026: keep).
