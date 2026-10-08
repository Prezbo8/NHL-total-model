"""Afternoon games: do matinees (local start before 5 PM) score less than projected?

Start times come from the NHL schedule API (club-schedule-season), cached in data/game_starts.csv.
(1) actual - projected total, afternoon vs evening, by season (with noise range).
(2) SLAM + 1U record in afternoon vs evening games.
(3) If there's an effect: an afternoon factor learned from earlier seasons only, judged on accuracy and bets.

  python3 research/afternoon.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
import json
import os
import time
import urllib.request
from datetime import datetime, timedelta
from math import lgamma

import numpy as np
import pandas as pd

import dashboard
import history as h
import model as m
import paths
import split_model as sm

CACHE = paths.data("game_starts.csv")
TEAMS = ["ANA", "ARI", "UTA", "BOS", "BUF", "CGY", "CAR", "CHI", "COL", "CBJ", "DAL", "DET", "EDM", "FLA", "LAK", "MIN",
         "MTL", "NSH", "NJD", "NYI", "NYR", "OTT", "PHI", "PIT", "SJS", "SEA", "STL", "TBL", "TOR", "VAN", "VGK", "WSH", "WPG"]
AFTERNOON = 17  # local start hour before 5 PM


def starts(seasons=range(2020, 2027)):
    if os.path.exists(CACHE):
        return pd.read_csv(CACHE)
    rows = {}
    for s in seasons:
        for t in TEAMS:
            url = f"https://api-web.nhle.com/v1/club-schedule-season/{t}/{s}{s + 1}"
            try:
                with urllib.request.urlopen(m.fetch(url), timeout=30) as f:
                    games = json.load(f).get("games", [])
            except Exception:
                continue  # team didn't exist that season (ARI after 2023, UTA before 2024, SEA 2020)
            for g in games:
                if g.get("gameType") == 2 and g.get("startTimeUTC"):
                    utc = datetime.fromisoformat(g["startTimeUTC"].replace("Z", "+00:00"))
                    hh, mm = g.get("venueUTCOffset", "-05:00").split(":")
                    local = utc + timedelta(hours=int(hh), minutes=int(mm) if hh[0] != "-" else -int(mm))
                    rows[g["id"]] = (g["id"], g["startTimeUTC"], local.hour + local.minute / 60)
            time.sleep(0.2)
    d = pd.DataFrame(rows.values(), columns=["gameId", "start_utc", "local_hour"])
    d.to_csv(CACHE, index=False)
    return d


def main():
    st = starts()
    g = sm.load_split()
    p = sm.walk_split(g, known_starters=False, record_detail=True).merge(g[["gameId", "hg", "ag"]], on="gameId")
    p = p.merge(st[["gameId", "local_hour"]], on="gameId", how="left")
    a = p[p.season.between(2021, 2025)]
    print(f"start times found for {a.local_hour.notna().mean():.1%} of 2021-26 games")
    a = a.dropna(subset=["local_hour"])
    a["aft"] = a.local_hour < AFTERNOON
    print(f"afternoon games: {a.aft.sum()} of {len(a)} ({a.aft.mean():.1%})\n")

    print(f"{'season':8s} {'aft games':>9s} {'aft: act-proj':>13s} {'eve: act-proj':>13s} {'difference':>10s} {'± 2 SE':>7s} {'aft 7+':>7s} {'eve 7+':>7s}")
    for s, x in list(a.groupby("season")) + [("ALL", a)]:
        af, ev = x[x.aft], x[~x.aft]
        ra, re = (af.total - af.proj), (ev.total - ev.proj)
        se = np.sqrt(ra.var() / len(ra) + re.var() / len(re))
        lab = f"{s}-{str(s + 1)[2:]}" if s != "ALL" else "ALL"
        print(f"{lab:8s} {len(af):9d} {ra.mean():+13.2f} {re.mean():+13.2f} {ra.mean() - re.mean():+10.2f} {2 * se:7.2f} "
              f"{(af.total >= 7).mean():7.1%} {(ev.total >= 7).mean():7.1%}")

    by_hour = a.assign(hr=np.floor(a.local_hour).clip(12, 20)).groupby("hr").apply(
        lambda y: f"{len(y)} games, act-proj {(y.total - y.proj).mean():+.2f}", include_groups=False)
    print("\nby local start hour:\n" + by_hour.to_string())

    d = h.flagged(p).merge(h.lines(), on=["gameDate", "home", "away"])
    d = d[(d.season >= 2021) & d.both & d.local_hour.notna()]
    d = d[np.isin([dashboard.call(r, True) for r in d.itertuples()], ["SLAM", "1U"])]
    print(f"\nSLAM + 1U: {'when':5s} {'bets':>5s} {'W-L':>8s} {'win%':>6s} {'ROI':>6s}")
    for name, sel in (("afternoon", d.local_hour < AFTERNOON), ("evening", d.local_hour >= AFTERNOON)):
        for when in ("open", "close"):
            b = h.bet_results(d[sel], when)
            w, l_ = (b.res > 0).sum(), (b.res < 0).sum()
            print(f"  {name:9s} {when:5s} {len(b):5d} {f'{w}-{l_}':>8s} {w / max(w + l_, 1):6.1%} {b.prof.mean():+6.1%}")

    # (3) afternoon factor from earlier seasons only
    lp = lambda k_, lam: k_ * np.log(lam) - lam - np.array([lgamma(v + 1) for v in k_])
    adj = []
    for s, x in p.groupby("season"):
        tr = p[p.season.between(2021, s - 1) & p.local_hour.notna()]
        f = 1.0
        if len(tr):
            af, ev = tr[tr.local_hour < AFTERNOON], tr[tr.local_hour >= AFTERNOON]
            f = 1 + 0.5 * ((af.total.sum() / af.proj.sum()) / (ev.total.sum() / ev.proj.sum()) - 1)
        k = np.where(x.local_hour < AFTERNOON, f, 1.0)
        adj.append(x.assign(lam_h=x.lam_h * k, lam_a=x.lam_a * k, proj=(x.lam_h + x.lam_a) * k))
    q = pd.concat(adj)
    lines = h.lines()
    print(f"\n{'version':18s} {'goal LL 23-26':>13s}   {'SLAM+1U open':>32s}   {'SLAM+1U close':>32s}")
    for name, v in (("current", p), ("+ afternoon factor", q)):
        t = v[v.season.between(2023, 2025)]
        ll = -np.mean(np.r_[lp(t.hg.values, t.lam_h.values), lp(t.ag.values, t.lam_a.values)])
        dd = h.flagged(v).merge(lines, on=["gameDate", "home", "away"])
        dd = dd[(dd.season >= 2021) & dd.both]
        c = np.array([dashboard.call(r, True) for r in dd.itertuples()])
        out = []
        for when in ("open", "close"):
            b = h.bet_results(dd[np.isin(c, ["SLAM", "1U"])], when)
            hv = [b[b.season.isin(s)].prof.mean() for s in ((2021, 2022), (2023, 2024, 2025))]
            out.append(f"{len(b)} {b.prof.sum():+.1f}u {b.prof.mean():+.1%} ({hv[0]:+.1%}/{hv[1]:+.1%})")
        print(f"{name:18s} {ll:13.4f}   {out[0]:>32s}   {out[1]:>32s}")


if __name__ == "__main__":
    main()
