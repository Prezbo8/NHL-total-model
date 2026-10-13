"""Recent form like the MLB model: how a team has played over the last 30 / 14 / 7 days, on top of the season-long
ratings. Does it make the projection more accurate?

For every team-game 2021-26: the team's recent residuals vs the model (goals scored - projected, and its opponents'
goals - projected against it) over the last 30 / 14 / 7 days before the game, plus the same in expected goals (xG,
less luck). If a team running hot/cold vs the model keeps doing so, these predict the next game's miss.
  1. slope of next-game miss on each window (0 = form adds nothing; the model already knows it)
  2. accuracy: projection adjusted by form (size fitted on 2021-23) judged on 2023-26 (team-goal deviance, lower = better)
  3. how noisy each window is: game-to-game goal swings vs how much teams really differ

  python3 research/studies/recent_form.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))

import numpy as np
import pandas as pd

import split_model as sm

WINDOWS = (30, 14, 7)  # calendar days, like the MLB model


def team_rows(games, proj):
    x = proj.merge(games[["gameId", "hg", "ag", "hxg", "axg"]], on="gameId")
    x["date"] = pd.to_datetime(x.gameDate.astype(str))
    h = pd.DataFrame({"gameId": x.gameId, "season": x.season, "date": x.date, "team": x.home, "opp": x.away,
                      "gf": x.hg, "lam": x.lam_h, "xgf": x.hxg, "ga": x.ag, "lam_opp": x.lam_a, "xga": x.axg})
    a = pd.DataFrame({"gameId": x.gameId, "season": x.season, "date": x.date, "team": x.away, "opp": x.home,
                      "gf": x.ag, "lam": x.lam_a, "xgf": x.axg, "ga": x.hg, "lam_opp": x.lam_h, "xga": x.hxg})
    t = pd.concat([h, a]).sort_values(["date", "gameId"]).reset_index(drop=True)
    t["r_off"], t["r_def"] = t.gf - t.lam, t.ga - t.lam_opp          # goal misses: scored / allowed vs model
    t["rx_off"], t["rx_def"] = t.xgf - t.lam, t.xga - t.lam_opp      # same in xG
    return t


def form(t):
    """Average miss over the last N days before each game (same season only), per team."""
    out = []
    for (team, season), x in t.groupby(["team", "season"]):
        x = x.sort_values("date")
        for w in WINDOWS:
            for c in ("r_off", "r_def", "rx_off", "rx_def"):
                s = x.set_index("date")[c]
                x[f"{c}_{w}"] = s.shift(1).rolling(f"{w}D").mean().values  # strictly before the game
            x[f"n_{w}"] = x.set_index("date").gf.shift(1).rolling(f"{w}D").count().values
        out.append(x)
    return pd.concat(out)


def dev(y, lam):
    lam = np.maximum(lam, 1e-6)
    return (2 * (np.where(y > 0, y * np.log(np.maximum(y, 1e-9) / lam), 0) - (y - lam))).mean()


def main():
    games = sm.load_split()
    proj = sm.walk_split(games, known_starters=False)
    proj = proj[proj.season >= 2021]
    f = form(team_rows(games, proj))
    # each team-game: own offense form + opponent's defense form (what should move this team's goals)
    opp = f[["gameId", "team"] + [c for c in f.columns if c.startswith(("r_def_", "rx_def_", "n_"))]].rename(columns={"team": "opp"})
    opp = opp.rename(columns={c: f"o_{c}" for c in opp.columns if c not in ("gameId", "opp")})
    d = f.merge(opp, on=["gameId", "opp"])
    d["miss"] = d.gf - d.lam
    train, test = d[d.season.between(2021, 2022)], d[d.season.between(2023, 2025)]
    print(f"team-games: {len(d)} (fit 2021-23: {len(train)}, judged 2023-26: {len(test)})")

    print("\n1. Does recent form predict the next game's miss?  (slope; 0 = no, 1 = the miss carries over fully)")
    print(f"   {'window':10s} {'kind':6s} {'2021-23 slope':>14s} {'2023-26 slope':>14s} {'2023-26 corr':>13s}")
    for w in WINDOWS:
        for kind, a, b in (("goals", "r_off", "o_r_def"), ("xG", "rx_off", "o_rx_def")):
            fx = lambda x: x[f"{a}_{w}"].fillna(0) + x[f"{b}_{w}"].fillna(0)
            s1, s2 = np.polyfit(fx(train), train.miss, 1)[0], np.polyfit(fx(test), test.miss, 1)[0]
            print(f"   last {w:2d} d  {kind:6s} {s1:14.3f} {s2:14.3f} {np.corrcoef(fx(test), test.miss)[0, 1]:13.3f}")

    print("\n2. Accuracy, 2023-26 (team-goal deviance, lower = better; form size fitted on 2021-23)")
    base = dev(test.gf.values, test.lam.values)
    print(f"   {'model as is (season-long ratings)':44s} {base:.4f}")
    for w in WINDOWS:
        for kind, a, b in (("goals", "r_off", "o_r_def"), ("xG", "rx_off", "o_rx_def")):
            fx = lambda x: x[f"{a}_{w}"].fillna(0) + x[f"{b}_{w}"].fillna(0)
            beta = np.polyfit(fx(train), train.miss, 1)[0]
            print(f"   {f'+ last {w} days {kind} form (x{beta:.2f})':44s} {dev(test.gf.values, (test.lam + beta * fx(test)).values):.4f}")
    fx3 = np.column_stack([test[f"{a}_{w}"].fillna(0) + test[f"{b}_{w}"].fillna(0) for w in WINDOWS for a, b in (("rx_off", "o_rx_def"),)])
    fx3t = np.column_stack([train[f"{a}_{w}"].fillna(0) + train[f"{b}_{w}"].fillna(0) for w in WINDOWS for a, b in (("rx_off", "o_rx_def"),)])
    coef = np.linalg.lstsq(np.column_stack([np.ones(len(train)), fx3t]), train.miss, rcond=None)[0]
    print(f"   {'+ all three xG windows together':44s} {dev(test.gf.values, (test.lam + coef[0] + fx3 @ coef[1:]).values):.4f}")

    print("\n3. How noisy is each window? (goals per game; 2021-26)")
    g_sd = d.gf.std()
    true_sd = proj.groupby("season").apply(lambda x: np.r_[x.lam_h, x.lam_a].std()).mean()
    for w in WINDOWS:
        n = d[f"n_{w}"].median()
        noise = g_sd / np.sqrt(n)
        print(f"   last {w:2d} days: ~{n:.0f} games -> luck swings a team's goals/game by ±{noise:.2f}; real team differences ±{true_sd:.2f} "
              f"(signal share {true_sd ** 2 / (true_sd ** 2 + noise ** 2):.0%})")
    print(f"   one game: goals per team swing ±{g_sd:.2f}")


if __name__ == "__main__":
    main()
