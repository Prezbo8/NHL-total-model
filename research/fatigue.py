"""Schedule fatigue and travel beyond back-to-backs: do they move scoring beyond what the model expects?

For every team-game 2021-26 (regular season): residual = actual goals - model projection (walk-forward,
no hindsight; the projection already includes the back-to-back adjustment). Each factor's effect is the
average residual in that group vs everyone else.

  python3 research/fatigue.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
import math

import numpy as np
import pandas as pd

import split_model as sm

# arena (lat, lon, UTC offset in standard time)
ARENA = {
    "ANA": (33.81, -117.88, -8), "ARI": (33.53, -112.26, -7), "UTA": (40.77, -111.90, -7), "BOS": (42.37, -71.06, -5),
    "BUF": (42.88, -78.88, -5), "CGY": (51.04, -114.05, -7), "CAR": (35.80, -78.72, -5), "CHI": (41.88, -87.67, -6),
    "COL": (39.75, -105.01, -7), "CBJ": (39.97, -83.01, -5), "DAL": (32.79, -96.81, -6), "DET": (42.34, -83.06, -5),
    "EDM": (53.55, -113.50, -7), "FLA": (26.16, -80.33, -5), "LAK": (34.04, -118.27, -8), "MIN": (44.94, -93.10, -6),
    "MTL": (45.50, -73.57, -5), "NSH": (36.16, -86.78, -6), "NJD": (40.73, -74.17, -5), "NYI": (40.72, -73.59, -5),
    "NYR": (40.75, -73.99, -5), "OTT": (45.30, -75.93, -5), "PHI": (39.90, -75.17, -5), "PIT": (40.44, -79.99, -5),
    "SJS": (37.33, -121.90, -8), "SEA": (47.62, -122.35, -8), "STL": (38.63, -90.20, -6), "TBL": (27.94, -82.45, -5),
    "TOR": (43.64, -79.38, -5), "VAN": (49.28, -123.11, -8), "VGK": (36.10, -115.18, -8), "WSH": (38.90, -77.02, -5),
    "WPG": (49.89, -97.14, -6),
}


def km(a, b):
    (la1, lo1, _), (la2, lo2, _) = ARENA[a], ARENA[b]
    p1, p2, dl = math.radians(la1), math.radians(la2), math.radians(lo2 - lo1)
    return 6371 * math.acos(min(1, math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)))


def team_games():
    g = sm.load_split()
    p = sm.walk_split(g, known_starters=False)
    g = g.merge(p[["gameId", "lam_h", "lam_a"]], on="gameId")
    rows = []
    for r in g.itertuples():
        for side, t, o, goals, lam in (("home", r.home, r.away, r.hg, r.lam_h), ("away", r.away, r.home, r.ag, r.lam_a)):
            rows.append({"gameId": r.gameId, "season": r.season, "date": pd.Timestamp(str(r.gameDate)), "team": t, "opp": o,
                         "home": side == "home", "venue": r.home, "goals": goals, "lam": lam})
    tg = pd.DataFrame(rows).sort_values(["team", "date"]).reset_index(drop=True)
    out = []
    for t, x in tg.groupby("team", sort=False):
        x = x.copy()
        d = x.date.values.astype("datetime64[D]").astype(int)
        prev_venue = x.venue.shift(1)
        x["rest"] = np.r_[99, np.diff(d)] - 1  # days off before this game (0 = back-to-back)
        x["in4"] = [((d[i] - d[:i]) <= 3).sum() + 1 for i in range(len(d))]  # games in the last 4 days incl. this one
        x["in6"] = [((d[i] - d[:i]) <= 5).sum() + 1 for i in range(len(d))]
        x["travel_km"] = [km(a, b) if isinstance(a, str) and a in ARENA and b in ARENA else 0.0 for a, b in zip(prev_venue, x.venue)]
        x["tz_shift"] = [(ARENA[b][2] - ARENA[a][2]) if isinstance(a, str) and a in ARENA and b in ARENA else 0
                         for a, b in zip(prev_venue, x.venue)]  # + = travelled east
        streak, trip = [], 0
        for h in x.home:
            streak.append(trip); trip = 0 if h else trip + 1  # road games played just before this one
        x["road_before"] = streak
        out.append(x)
    tg = pd.concat(out)
    tg = tg[tg.rest < 30]  # first game of a season has no previous game
    o = tg[["gameId", "team", "rest", "in4"]].rename(columns={"team": "opp", "rest": "opp_rest", "in4": "opp_in4"})
    tg = tg.merge(o, on=["gameId", "opp"])
    tg["resid"] = tg.goals - tg.lam
    return tg


def report(tg):
    t = tg[tg.season >= 2021]
    base = t.resid.mean()
    print(f"{len(t)} team-games 2021-26 | avg actual - projected goals: {base:+.3f} (the model's overall lean)\n")
    print(f"{'factor (this team)':44s} {'games':>6s} {'goals vs model':>15s} {'vs rest':>9s} {'± (2 SE)':>9s}  same in 2021-23 / 2024-26")
    groups = [
        ("back-to-back (already in the model)", t.rest == 0),
        ("1 day of rest", t.rest == 1),
        ("2 days of rest", t.rest == 2),
        ("3+ days of rest", t.rest >= 3),
        ("3rd game in 4 nights", t.in4 >= 3),
        ("4th game in 6 nights", t.in6 >= 4),
        ("rest edge: 2+ more days than opponent", (t.rest - t.opp_rest) >= 2),
        ("rest deficit: 2+ fewer days than opponent", (t.rest - t.opp_rest) <= -2),
        ("travelled 1,500+ km since last game", t.travel_km >= 1500),
        ("travelled 2,500+ km", t.travel_km >= 2500),
        ("crossed 2+ time zones going east", t.tz_shift >= 2),
        ("crossed 2+ time zones going west", t.tz_shift <= -2),
        ("travel 1,500+ km on a back-to-back", (t.travel_km >= 1500) & (t.rest == 0)),
        ("on the road, 4th+ straight road game", (~t.home) & (t.road_before >= 3)),
        ("first home game after 4+ road games", t.home & (t.road_before >= 4)),
        ("first home game after 3+ road games", t.home & (t.road_before >= 3)),
    ]
    for name, mask in groups:
        a, b = t[mask].resid, t[~mask].resid
        if len(a) < 30:
            print(f"{name:44s} {len(a):6d}   (too few games)"); continue
        diff = a.mean() - b.mean()
        se = math.sqrt(a.var() / len(a) + b.var() / len(b))
        halves = [t[(t.season.between(*s)) & mask].resid.mean() - t[(t.season.between(*s)) & ~mask].resid.mean()
                  for s in ((2021, 2023), (2024, 2025))]
        sig = " *" if abs(diff) > 2 * se and np.sign(halves[0]) == np.sign(halves[1]) else ""
        print(f"{name:44s} {len(a):6d} {a.mean():+15.3f} {diff:+9.3f} {2 * se:9.3f}  {halves[0]:+.3f} / {halves[1]:+.3f}{sig}")
    print("\n* = bigger than 2 standard errors AND the same direction in both halves (2021-23 and 2024-26)")


if __name__ == "__main__":
    report(team_games())
