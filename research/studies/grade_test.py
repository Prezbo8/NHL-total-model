"""Which ranking predicts future goals best: Model, Total, their blend, with or without the schedule correction?

For each season 2021-22 to 2025-26 and checkpoint (10 / 20 / 41 team games played), ratings are rebuilt from
games before that date only (as the live site would have them), then compared with each team's goals for /
against per game over the REST of that season. Correlations use z-scores within each season-checkpoint.

  python3 research/studies/grade_test.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers
import numpy as np
import pandas as pd

import split_model as sm

CHECKPOINTS = (10, 20, 41)


def samples():
    games = sm.load_split()
    tg = sm.team_games(2020)
    out = []
    for season in range(2021, 2026):
        sg = games[games.season == season].sort_values("gameDate")
        for cp in CHECKPOINTS:
            # first date by which the median team has played cp games
            cnt, day = {}, None
            for r in sg.itertuples():
                cnt[r.home] = cnt.get(r.home, 0) + 1
                cnt[r.away] = cnt.get(r.away, 0) + 1
                if len(cnt) >= 30 and np.median(list(cnt.values())) >= cp:
                    day = r.gameDate
                    break
            g = games[games.gameDate < day]
            p, project = sm.walk_split(g, known_starters=False, with_projector=True, live_season=season)
            rk = sm.team_rankings(project, set(g[g.season >= season - 1].home), season, g)
            fut = tg[(tg.season == season) & (tg.date >= day)].groupby("team")[["goalsF", "goalsA"]].mean().rename(columns={"goalsF": "futF", "goalsA": "futA"})
            d = rk.set_index("team").join(fut, how="inner")
            d["season"], d["cp"] = season, cp
            out.append(d.reset_index())
            print(f"  {season}-{str(season + 1)[2:]} after ~{cp} games ({day}): {len(d)} teams", flush=True)
    return pd.concat(out, ignore_index=True)


def z(x):
    return (x - x.mean()) / x.std(ddof=0)


def corr(d, pred, target):
    zz = d.groupby(["season", "cp"], group_keys=False).apply(lambda x: pd.DataFrame({"p": z(x[pred]), "t": z(x[target])}))
    return zz.p.corr(zz.t)


if __name__ == "__main__":
    d = samples()
    for side, model, model_adj, total, total_adj, target, sign in (
            ("OFFENSE", "gf", "gf_adj", "score_off", "score_off_adj", "futF", 1),
            ("DEFENSE", "ga", "ga_adj", "score_def", "score_def_adj", "futA", 1)):
        print(f"\n{side}: correlation with goals per game over the rest of the season (higher = better)")
        g = d.groupby(["season", "cp"], group_keys=False)
        d["zm"], d["zt"] = g[model].transform(z), g[total].transform(z)
        d["zma"], d["zta"] = g[model_adj].transform(z), g[total_adj].transform(z)
        for name, col in (("Model", "zm"), ("Total", "zt"), ("Model, schedule-adjusted", "zma"), ("Total, schedule-adjusted (Adj #)", "zta")):
            by = {cp: round(corr(d[d.cp == cp], col, target), 3) for cp in CHECKPOINTS}
            print(f"  {name:34s} all {corr(d, col, target):.3f}   by checkpoint {by}")
        best = {}
        for adj in (False, True):
            m, t = ("zma", "zta") if adj else ("zm", "zt")
            res = []
            for a in np.round(np.arange(0, 1.01, 0.1), 1):
                d["blend"] = a * d[m] + (1 - a) * d[t]
                res.append((corr(d, "blend", target), a))
            r, a = max(res)
            best[adj] = (r, a)
            print(f"  best blend{' (schedule-adjusted)' if adj else '':22s} {a:.1f} x Model + {1 - a:.1f} x Total -> {r:.3f}   "
                  "(curve: " + " ".join(f"{aa:.1f}:{rr:.3f}" for rr, aa in res) + ")")
        # stability: best weight in each half of the seasons
        for seasons in ((2021, 2022), (2023, 2024, 2025)):
            sub = d[d.season.isin(seasons)]
            res = []
            for a in np.round(np.arange(0, 1.01, 0.1), 1):
                sub = sub.assign(blend=a * sub.zm + (1 - a) * sub.zt)
                res.append((corr(sub, "blend", target), a))
            print(f"  seasons {seasons}: best blend {max(res)[1]:.1f} x Model (r {max(res)[0]:.3f}); Model alone {corr(sub, 'zm', target):.3f}, Total alone {corr(sub, 'zt', target):.3f}")
